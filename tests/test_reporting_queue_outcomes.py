import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch
from tests import test_reporting_queries as fixtures
from sanequeue.reporting.queries import Scope
from sanequeue.reporting.queue_outcomes import report


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
        self.assertNotIn('09123456789',str(r))
        self.assertTrue(r['contract']['exit_empty_is_not_proof_no_staff'])

    def test_limit_and_scope(self):
        with patch('sanequeue.reporting.queue_outcomes.MAX_VISITS',2):
            r=report(self.case.archive,Scope(('8001',)),self.case.stamp,self.case.stamp+100)
        self.assertEqual(r['state'],'limited');self.assertNotIn('totals',r)
        self.assertEqual(report(self.case.archive,Scope(('8002',)),self.case.stamp,self.case.stamp+100)['totals']['abandoned'],1)
        self.assertEqual(report(self.case.archive,Scope(()),self.case.stamp,self.case.stamp+100)['totals']['visits'],0)

    def test_api_enforces_queue_scope(self):
        client=self.case.client(role='supervisor',menus=('reports',))
        response=client.get('/api/history/queue-outcomes'+self.case.dates)
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json['totals']['visits'],8)
        self.assertEqual(response.headers['Cache-Control'],'private, no-store')
        self.assertEqual(client.get('/api/history/queue-outcomes'+self.case.dates+'&queue=8002').status_code,403)
        self.assertNotIn('09123456789',response.text)

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


if __name__=='__main__':unittest.main()
