import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import csv
import io
import os
from zipfile import ZipFile
from unittest.mock import patch
from tests import test_reporting_queries as fixtures
from sanequeue.reporting.queries import Scope,visits
from sanequeue.reporting.queue_outcomes import report
from sanequeue.reporting import visit_snapshots
from sanequeue.reporting.export_jobs import JobStore,ExportWorker,Limits,projection_watermark


class QueueOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.ReportTests();self.case.setUp();self.addCleanup(self.case.doCleanups);self.case.seed()
        with self.case.archive.writer() as db:
            db.execute('DELETE FROM report_visits')
            rows=[]
            for i,(queue,outcome,answer,coverage) in enumerate([
                ('8001','answered',10,'observed'),('8001','transferred',12,'observed'),
                ('8001','abandoned',None,'observed'),('8001','exitwithtimeout',None,'observed'),
                ('8001','exitwithkey',None,'observed'),('8001','exitempty',None,'observed'),
                ('8001','waiting',None,'missing_end'),('8001','abandoned',20,'observed'),
                ('8001','answered',None,'missing_entry'),('8002','abandoned',None,'observed')]):
                rows.append(('primary',format(i+1,'064x'),'call'+str(i),queue,self.case.stamp+i,
                    self.case.stamp+answer if answer is not None else None,self.case.stamp+40,
                    '09123456789','PJSIP/100',outcome,10,30,'agent',coverage))
            db.executemany('INSERT INTO report_visits VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',rows)

    def test_separate_outcomes_and_conflicts_from_queue_visits(self):
        r=report(self.case.archive,Scope(('8001',)),self.case.stamp,self.case.stamp+100)
        total=r['totals']
        self.assertEqual((total['visits'],total['answered'],total['unanswered'],total['unresolved']),(8,2,4,2))
        self.assertEqual(total['known_outcomes'],6)
        self.assertAlmostEqual(total['answered_percent_of_known'],100/3)
        self.assertEqual([total[k] for k in ('abandoned','exitwithtimeout','exitwithkey','exitempty')],[1,1,1,1])
        self.assertEqual(r['missing_entry_visits'],1)
        self.assertEqual(total['average_wait_seconds'],10)
        self.assertEqual((total['answered_wait_samples'],total['average_answered_wait_seconds']),(2,10))
        self.assertEqual((total['unanswered_wait_samples'],total['average_unanswered_wait_seconds']),(4,10))
        self.assertEqual(sum(x['visits'] for x in r['hours']),total['visits'])
        self.assertEqual(sum(x['visits'] for x in r['weekdays']),total['visits'])
        self.assertEqual(sum(x['answered_wait_samples'] for x in r['weekdays']),total['answered_wait_samples'])
        self.assertNotIn('09123456789',str(r))
        self.assertTrue(r['contract']['exit_empty_is_not_proof_no_staff'])

    def test_weekdays_use_tehran_entry_day_and_weighted_samples(self):
        from datetime import datetime, timezone
        from sanequeue.reporting.analytics import ZONE
        base=datetime(2026,10,23,20,40,tzinfo=timezone.utc).timestamp() # Saturday in Tehran
        with self.case.archive.writer() as db:
            db.execute('UPDATE report_visits SET entered=?, wait_seconds=4 WHERE id=?',(base,format(1,'064x')))
            db.execute('UPDATE report_visits SET entered=?, wait_seconds=10 WHERE id=?',(base+7*86400,format(2,'064x')))
            db.execute('UPDATE report_visits SET entered=? WHERE id=?',(base+86400,format(3,'064x')))
        result=report(self.case.archive,Scope(('8001',)),base,base+8*86400)
        saturday=next(row for row in result['weekdays'] if row['weekday']==5)
        self.assertEqual((saturday['answered'],saturday['answered_wait_samples']),(2,2))
        self.assertEqual(saturday['average_answered_wait_seconds'],7)
        self.assertEqual([row['weekday'] for row in result['weekdays']],[5,6])
        self.assertEqual(datetime.fromtimestamp(base,ZONE).weekday(),5)
        from sanequeue.reporting.queue_outcomes import aggregate_csv
        rows=list(csv.DictReader(io.StringIO(aggregate_csv(result,'answered','weekdays','en',('8001',)).decode('utf-8-sig'))))
        self.assertEqual(rows[0]['weekday'],"'Saturday");self.assertEqual(rows[0]['mean_wait_seconds'],'7.0')

    def test_limit_and_scope(self):
        with patch('sanequeue.reporting.queue_outcomes.MAX_VISITS',2):
            r=report(self.case.archive,Scope(('8001',)),self.case.stamp,self.case.stamp+100)
        self.assertEqual(r['state'],'limited');self.assertNotIn('totals',r)
        self.assertEqual(report(self.case.archive,Scope(('8002',)),self.case.stamp,self.case.stamp+100)['totals']['abandoned'],1)
        self.assertEqual(report(self.case.archive,Scope(()),self.case.stamp,self.case.stamp+100)['totals']['visits'],0)

    def test_wait_distribution_csv_matches_summary_and_checks_permissions(self):
        denied=[];client=self.case.client(role='supervisor',menus=('reports',),denied=denied)
        with client.session_transaction() as state:state['csrf_token']='token'
        url='/api/history/queue-outcomes/wait-distribution.csv'+self.case.dates+'&kind=unanswered&lang=en'
        self.assertEqual(client.post(url).status_code,403)
        result=client.post(url,headers={'X-CSRF-Token':'token'});self.assertEqual(result.status_code,200)
        rows=list(csv.DictReader(io.StringIO(result.data.decode('utf-8-sig'))))
        self.assertEqual(len(rows),8);self.assertEqual(sum(int(row['visits']) for row in rows),4)
        self.assertTrue(all(row['queues'].startswith("'") for row in rows))
        self.assertNotIn('09123456789',result.get_data(as_text=True))
        denied.append('report_export');self.assertEqual(client.post(url,headers={'X-CSRF-Token':'token'}).status_code,403)

    def test_aggregate_csv_tables_match_visible_summary_and_scope(self):
        denied=[];client=self.case.client(role='supervisor',menus=('reports',),denied=denied)
        with client.session_transaction() as state:state['csrf_token']='token'
        base='/api/history/queue-outcomes/aggregate.csv'+self.case.dates+'&lang=en'
        self.assertEqual(client.post(base+'&kind=answered&table=queues').status_code,403)
        for kind,table,expected in [('answered','queues',2),('answered','hours',2),('answered','weekdays',2),('unanswered','weekdays',4),('unanswered','hours',4),('unanswered','days',4),('unanswered','reasons',4)]:
            with self.subTest(kind=kind,table=table):
                response=client.post(base+'&kind='+kind+'&table='+table,headers={'X-CSRF-Token':'token'})
                self.assertEqual(response.status_code,200)
                rows=list(csv.DictReader(io.StringIO(response.data.decode('utf-8-sig'))))
                self.assertEqual(sum(int(row['visits']) for row in rows),expected)
                self.assertTrue(all(row['queues'].startswith("'") for row in rows))
                self.assertNotIn('09123456789',response.get_data(as_text=True))
                self.assertEqual(response.headers['Cache-Control'],'private, no-store')
        self.assertEqual(client.post(base+'&kind=answered&table=reasons',headers={'X-CSRF-Token':'token'}).status_code,400)
        self.assertEqual(client.post(base+'&kind=answered&table=queues&queue=8002',headers={'X-CSRF-Token':'token'}).status_code,403)
        denied.append('report_export')
        self.assertEqual(client.post(base+'&kind=answered&table=days',headers={'X-CSRF-Token':'token'}).status_code,403)

    def test_aggregate_csv_revocation_and_empty_are_not_false_zero(self):
        denied=[];client=self.case.client(role='supervisor',menus=('reports',),denied=denied)
        with client.session_transaction() as state:state['csrf_token']='token'
        from sanequeue.reporting.queue_outcomes import aggregate_csv
        def revoke(*args,**kwargs):
            value=aggregate_csv(*args,**kwargs);denied.append('report_export');return value
        url='/api/history/queue-outcomes/aggregate.csv'+self.case.dates+'&kind=answered&table=days&lang=en'
        with patch('sanequeue.api.reports.queue_outcomes.aggregate_csv',side_effect=revoke):
            self.assertEqual(client.post(url,headers={'X-CSRF-Token':'token'}).status_code,403)
        empty=report(self.case.archive,Scope(('8001',)),self.case.stamp+1000,self.case.stamp+1100)
        rows=list(csv.DictReader(io.StringIO(aggregate_csv(empty,'answered','days','en',('8001',)).decode('utf-8-sig'))))
        self.assertEqual(rows[0]['day'],'No records');self.assertEqual(rows[0]['visits'],'')

    def test_wait_distribution_csv_rechecks_revoked_export_grant(self):
        denied=[];client=self.case.client(role='supervisor',menus=('reports',),denied=denied)
        with client.session_transaction() as state:state['csrf_token']='token'
        from sanequeue.reporting.queue_outcomes import distribution_csv
        def revoke(*args,**kwargs):
            value=distribution_csv(*args,**kwargs);denied.append('report_export');return value
        with patch('sanequeue.api.reports.queue_outcomes.distribution_csv',side_effect=revoke):
            result=client.post('/api/history/queue-outcomes/wait-distribution.csv'+self.case.dates+'&kind=answered',headers={'X-CSRF-Token':'token'})
        self.assertEqual(result.status_code,403);self.assertNotIn('09123456789',result.get_data(as_text=True))

    def test_wait_distribution_uses_half_open_boundaries_unknown_and_scope(self):
        archive=self.case.archive
        with archive.writer() as db:
            for index,value in enumerate((0,10,20,30,60,None,120,300,4,9)):
                db.execute('UPDATE report_visits SET wait_seconds=? WHERE id=?',(value,format(index+1,'064x')))
        result=report(archive,Scope(('8001',)),self.case.stamp,self.case.stamp+100)
        answered=result['wait_distribution']['answered'];unanswered=result['wait_distribution']['unanswered']
        self.assertEqual([b['count'] for b in answered['buckets']],[1,1,0,0,0,0,0])
        self.assertEqual([b['count'] for b in unanswered['buckets']],[0,0,1,1,1,0,0])
        self.assertEqual((answered['known'],answered['unknown'],unanswered['known'],unanswered['unknown']),(2,0,3,1))
        self.assertEqual(answered['buckets'][-1],dict(start_seconds=300,end_seconds=None,count=0))
        self.assertEqual(result['missing_entry_visits'],1)
        self.assertNotIn('09123456789',str(result['wait_distribution']))
        with archive.writer() as db:
            db.execute('UPDATE report_visits SET wait_seconds=300 WHERE id=?',(format(1,'064x'),))
            db.execute('UPDATE report_visits SET wait_seconds=120 WHERE id=?',(format(3,'064x'),))
        result=report(archive,Scope(('8001',)),self.case.stamp,self.case.stamp+100)
        self.assertEqual(result['wait_distribution']['answered']['buckets'][-1]['count'],1)
        self.assertEqual(result['wait_distribution']['unanswered']['buckets'][-2]['count'],1)

    def test_api_enforces_queue_scope(self):
        client=self.case.client(role='supervisor',menus=('reports',))
        response=client.get('/api/history/queue-outcomes'+self.case.dates)
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json['totals']['visits'],8)
        self.assertEqual(response.headers['Cache-Control'],'private, no-store')
        self.assertEqual(client.get('/api/history/queue-outcomes'+self.case.dates+'&queue=8002').status_code,403)
        self.assertNotIn('09123456789',response.text)

    def test_category_details_match_summary_across_pages_and_scope(self):
        archive=self.case.archive;scope=Scope(('8001',));start=self.case.stamp;end=start+100
        totals=report(archive,scope,start,end)['totals']
        for kind in ('answered','unanswered'):
            cursor=None;rows=[]
            while True:
                page=visits(archive,scope,start,end,before=cursor,limit=2,outcome_class=kind)
                rows.extend(page['rows']);cursor=page['next']
                if cursor is None:break
            self.assertEqual(len(rows),totals[kind]);self.assertEqual(len({row['id'] for row in rows}),len(rows))
            self.assertEqual({row['queue'] for row in rows},{'8001'})
        client=self.case.client(role='supervisor',menus=('reports',),details=False)
        result=client.get('/api/history/visits'+self.case.dates+'&outcome_class=unanswered')
        self.assertEqual(result.status_code,200,result.json);self.assertEqual(len(result.json['rows']),4)
        self.assertNotIn('09123456789',result.text);self.assertEqual(result.json['consistency'],'current_page_not_snapshot')
        self.assertEqual(client.get('/api/history/visits'+self.case.dates+'&outcome_class=unanswered&queue=8002').status_code,403)
        self.assertEqual(client.get('/api/history/visits'+self.case.dates+'&outcome_class=bogus').status_code,400)
        self.assertEqual(client.get('/api/history/visits'+self.case.dates+'&outcome_class=answered&outcome=abandoned').status_code,400)

    def test_concurrent_aggregate_is_rejected_without_blocking(self):
        first=self.case.client(role='supervisor',menus=('reports',),details=True);second=first.application.test_client()
        with second.session_transaction() as state:state.update(_user_id='test',_fresh=True)
        entered=Event();release=Event();path='/api/history/queue-outcomes'+self.case.dates
        def held(*args):
            entered.set();self.assertTrue(release.wait(5));return {'state':'available'}
        with patch('sanequeue.api.reports.queue_outcomes.report',side_effect=held), ThreadPoolExecutor(max_workers=1) as pool:
            running=pool.submit(first.get,path)
            try:
                self.assertTrue(entered.wait(5))
                response=second.get(path);self.assertEqual(response.status_code,429)
                self.assertEqual(response.json['error'],'queue_outcomes_busy')
                response=second.get('/api/history/unique-callers'+self.case.dates)
                self.assertEqual(response.status_code,429)
                self.assertEqual(response.json['error'],'report_aggregate_busy')
            finally:release.set()
            self.assertEqual(running.result().status_code,200)

    def test_category_export_matches_summary_and_masks_numbers(self):
        archive=self.case.archive;scope=Scope(('8001',));start=self.case.stamp;end=start+100
        snapshot=visit_snapshots.capture(archive);totals=report(archive,scope,start,end)['totals']
        store=JobStore(self.case.root/'jobs.db',self.case.root/'private');store.initialize()
        worker=ExportWorker(store,archive,limits=Limits(min_free_bytes=0,max_load_per_cpu=0),authorize=lambda spec:True,
                            disabled_file=self.case.root/'disabled')
        for kind in ('answered','unanswered'):
            for fmt in ('csv','xlsx','pdf'):
                with self.subTest(kind=kind,format=fmt):
                    ident=store.create('test',scope,start,end,watermark=projection_watermark(archive),
                        number_modes={'8001':'masked'},snapshot=snapshot,format=fmt,language='en',outcome_class=kind)
                    result=worker.run_once();self.assertEqual(result['state'],'completed',result)
                    self.assertEqual(result['rows'],totals[kind]);fd,_=store.open_output(ident,'test')
                    with os.fdopen(fd,'rb') as stream:data=stream.read()
                    self.assertNotIn(b'09123456789',data)
                    if fmt=='csv':
                        rows=list(csv.reader(io.StringIO(data.decode('utf-8-sig'))))
                        self.assertEqual(len(rows),totals[kind]+1)
                        self.assertEqual({r[3] for r in rows[1:]},{'answered','transferred'} if kind=='answered' else {'abandoned','exitwithtimeout','exitwithkey','exitempty'})
                    elif fmt=='xlsx':
                        with ZipFile(io.BytesIO(data)) as book:
                            sheet=book.read('xl/worksheets/sheet1.xml')
                            self.assertIn(('answered with evidence' if kind=='answered' else 'unanswered exits').encode(),sheet)
                    else:self.assertTrue(data.startswith(b'%PDF-'))
        with self.assertRaises(ValueError):
            store.create('test',scope,start,end,watermark=0,number_modes={'8001':'masked'},snapshot=snapshot,outcome='answered',outcome_class='unanswered')

    def test_category_export_api_checks_csrf_and_conflicts(self):
        JobStore(self.case.root/'export-jobs.sqlite3',self.case.root/'private-exports').initialize()
        client=self.case.client(role='admin',menus=('reports',),details=False)
        with client.session_transaction() as state:state['csrf_token']='token'
        url='/api/history/export-jobs'+self.case.dates+'&format=csv&outcome_class=unanswered'
        self.assertEqual(client.post(url).status_code,403)
        response=client.post(url,headers={'X-CSRF-Token':'token'})
        self.assertEqual(response.status_code,202,response.json)
        self.assertEqual(response.json['outcome_class'],'unanswered')
        self.assertEqual(client.post(url+'&outcome=abandoned',headers={'X-CSRF-Token':'token'}).status_code,400)

    def test_category_export_pins_old_facts_even_after_correction(self):
        archive=self.case.archive;scope=Scope(('8001',));start=self.case.stamp;end=start+100
        snapshot=visit_snapshots.capture(archive);before=report(archive,scope,start,end)['totals']['unanswered']
        store=JobStore(self.case.root/'jobs.db',self.case.root/'private');store.initialize()
        ident=store.create('test',scope,start,end,watermark=projection_watermark(archive),number_modes={'8001':'masked'},
                           snapshot=snapshot,format='csv',outcome_class='unanswered')
        with archive.writer() as db:db.execute("UPDATE report_visits SET outcome='answered',answered=entered+1 WHERE queue='8001'")
        worker=ExportWorker(store,archive,limits=Limits(min_free_bytes=0,max_load_per_cpu=0),authorize=lambda spec:True,
                            disabled_file=self.case.root/'disabled')
        result=worker.run_once();self.assertEqual(result['state'],'completed',result)
        self.assertEqual(result['rows'],before)
        fd,_=store.open_output(ident,'test')
        with os.fdopen(fd,'rb') as stream:rows=list(csv.reader(io.StringIO(stream.read().decode('utf-8-sig'))))
        self.assertEqual(len(rows)-1,before)


if __name__=='__main__':unittest.main()
