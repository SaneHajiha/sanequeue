import csv
import io
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from tests import test_reporting_queries as fixtures
from sanequeue.reporting.store import Event
from sanequeue.reporting.facts import project_batch


class CDRAPITests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.ReportTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        case=self.case;case.seed()
        case.archive.append([Event('cdr','segment',case.stamp+10,'CDR',dict(
            src='02199999999',dst='09123456789',channel='PJSIP/100-000000aa',
            dstchannel='PJSIP/provider-000000ab',uniqueid='private',linkedid='private',
            outbound_cnum='02112345678',did='02188888888',duration=30,billsec=20,disposition='ANSWERED',recordingfile='test.wav'))])
        project_batch(case.archive,inventory=dict(observed_at=case.stamp,endpoints=[
            dict(technology='PJSIP',endpoint='100',category='extension'),
            dict(technology='PJSIP',endpoint='provider',category='trunk')]))
        self.query='?from=2026-10-24&to=2026-10-25'

    def test_supervisor_and_queue_only_admin_cannot_get_global_cdr(self):
        for client in (self.case.client(),self.case.client(role='supervisor',menus=('reports','users')),
                       self.case.client(role='admin'),self.case.client(role='admin',menus=('users',))):
            self.assertEqual(client.get('/api/history/cdr'+self.query).status_code,403)

    def test_partial_queue_grants_are_not_global_authorization(self):
        # The fixture allows queue 8001 only. 8002 existing in the archive
        # prevents global CDR access even when the selected request is 8001.
        client=self.case.client(role='admin',menus=('reports','users'),details=True)
        self.assertEqual(client.get('/api/history/cdr'+self.query).status_code,403)

    def test_recording_requires_current_proof_and_separate_grants(self):
        with self.case.archive.writer() as db:db.execute("DELETE FROM report_visits WHERE queue='8002'")
        audio=self.case.root/'audio';audio.mkdir();(audio/'test.wav').write_bytes(b'RIFF0123456789')
        client=self.case.client(role='admin',menus=('reports','users'),details=True)
        url='/api/history/cdr/segment/recording'+self.query
        with patch('sanequeue.api.reports.recording_ownership',return_value=frozenset({'8001'})):
            page=client.get('/api/history/cdr'+self.query).json
            self.assertTrue(page['rows'][0]['can_play'])
            self.assertTrue(page['rows'][0]['can_download'])
            self.assertEqual(client.get(url).status_code,200)
            denied=self.case.client(role='admin',menus=('reports','users'),details=True,denied=('recording_play',))
            self.assertEqual(denied.get(url).status_code,403)
            self.assertEqual(denied.get(url+'&download=1').status_code,200)
            self.assertEqual(client.get(url+'&origin=999').status_code,404)
        with patch('sanequeue.api.reports.recording_ownership',return_value=False):
            self.assertFalse(client.get('/api/history/cdr'+self.query).json['rows'][0]['can_play'])
            self.assertEqual(client.get(url).status_code,403)
        self.assertEqual(self.case.client(role='supervisor',menus=('reports','users')).get(url).status_code,403)

    def test_cdr_classification_is_global_authorized_audited_and_not_guessed(self):
        with self.case.archive.writer() as db:db.execute("DELETE FROM report_visits WHERE queue='8002'")
        url='/api/history/cdr/segment/classification'+self.query
        self.assertEqual(self.case.client(role='supervisor',menus=('reports','users')).get(url).status_code,403)
        self.assertEqual(self.case.client(role='admin',menus=('reports','users')).get(url).status_code,403)
        client=self.case.client(role='admin',menus=('reports','users'),details=True)
        self.assertEqual(client.get(url).json['classification']['reason'],'')
        payload={'reason':'پشتیبانی','subreason':'نصب','outcome':'حل شد'}
        self.assertEqual(client.post(url,json=payload).status_code,403)
        with client.session_transaction() as state:state['csrf_token']='token'
        result=client.post(url,json=payload,headers={'X-CSRF-Token':'token'})
        self.assertEqual(result.status_code,200,result.get_data(as_text=True))
        self.assertEqual(client.get(url).json['classification'],payload)
        analysis='/api/history/cdr/classification/analysis'+self.query
        data=client.get(analysis)
        self.assertEqual(data.status_code,200,data.get_data(as_text=True))

        self.assertEqual((data.json['segments'],data.json['labelled'],data.json['unlabelled']),(1,1,0))
        self.assertEqual(data.json['rows'][0]['reason'],'پشتیبانی')
        self.assertEqual(client.get(analysis+'&party=100').json['segments'],1)
        self.assertEqual(client.get(analysis+'&party=999').json['segments'],0)
        timeline=client.get(analysis+'&bucket=hour')
        self.assertEqual(timeline.status_code,200,timeline.get_data(as_text=True))
        self.assertEqual(timeline.json['timeline'],[{'period':'03','reason':'پشتیبانی','count':1}])
        self.assertEqual(client.get(analysis+'&bucket=year').status_code,400)
        self.assertNotIn('09123456789',data.get_data(as_text=True))
        self.assertEqual(self.case.client(role='admin',menus=('reports','users')).get(analysis).status_code,403)
        self.assertEqual(client.get(url.replace('/segment/','/missing/')).status_code,404)
        invalid={'reason':'','subreason':'نامعتبر','outcome':''}
        self.assertEqual(client.post(url,json=invalid,headers={'X-CSRF-Token':'token'}).status_code,400)
        client.post(url,json={'reason':'','subreason':'','outcome':''},headers={'X-CSRF-Token':'token'})
        data=client.get(analysis)
        self.assertEqual((data.json['labelled'],data.json['unlabelled']),(0,1))
        self.assertEqual(client.get(analysis+'&direction=internal').json['segments'],0)
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(self.case.archive.path.parent/'cdr-reasons.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM cdr_reason_audit').fetchone()[0],2)

    def test_reason_catalog_requires_full_global_authorization_and_csrf(self):
        with self.case.archive.writer() as db:db.execute("DELETE FROM report_visits WHERE queue='8002'")
        url='/api/history/cdr/classification/catalog'+self.query
        self.assertEqual(self.case.client(role='admin',menus=('reports','users')).get(url).status_code,403)
        client=self.case.client(role='admin',menus=('reports','users'),details=True)
        payload={'reason':'پشتیبانی','subreason':'نصب','active':True}
        self.assertEqual(client.post(url,json=payload).status_code,403)
        with client.session_transaction() as state:state['csrf_token']='token'
        result=client.post(url,json=payload,headers={'X-CSRF-Token':'token'})
        self.assertEqual(result.status_code,200,result.get_data(as_text=True))
        self.assertEqual(result.json['items'],[{'reason':'پشتیبانی','subreason':'نصب'}])
        payload['active']=False
        self.assertEqual(client.post(url,json=payload,headers={'X-CSRF-Token':'token'}).json['items'],[])

    def test_independent_aggregate_exports_require_permissions_and_escape_csv(self):
        with self.case.archive.writer() as db:db.execute("DELETE FROM report_visits WHERE queue='8002'")
        denied=[];client=self.case.client(role='admin',menus=('reports','users'),details=True,denied=denied)
        with client.session_transaction() as state:state['csrf_token']='token'
        hdr={'X-CSRF-Token':'token'}
        label={'reason':'=test','subreason':'','outcome':''}
        self.assertEqual(client.post('/api/history/cdr/segment/classification'+self.query,json=label,headers=hdr).status_code,200)
        for dataset in ('performance','reasons'):
            base='/api/history/cdr/aggregate/'+dataset+'/export.'
            self.assertEqual(client.post(base+'csv'+self.query).status_code,403)
            for fmt in ('csv','xlsx','pdf'):
                result=client.post(base+fmt+self.query,headers=hdr)
                self.assertEqual(result.status_code,200,result.data[:200])
                if fmt=='csv' and dataset=='reasons':self.assertIn("'=test",result.get_data(as_text=True))
                if fmt=='xlsx':
                    with ZipFile(io.BytesIO(result.data)) as workbook:self.assertIn('xl/worksheets/sheet1.xml',workbook.namelist())
                if fmt=='pdf':self.assertTrue(result.data.startswith(b'%PDF-'))
            denied.append('report_export')
            self.assertEqual(client.post(base+'csv'+self.query,headers=hdr).status_code,403)
            denied.clear()
        timeline='/api/history/cdr/aggregate/reasons-timeline/export.'
        self.assertEqual(client.post(timeline+'csv'+self.query,headers=hdr).status_code,400)
        for fmt in ('csv','xlsx','pdf'):
            result=client.post(timeline+fmt+self.query+'&bucket=weekday',headers=hdr)
            self.assertEqual(result.status_code,200,result.data[:200])
            if fmt=='csv':self.assertIn('یکشنبه',result.get_data(as_text=True))
            if fmt=='xlsx':
                with ZipFile(io.BytesIO(result.data)) as workbook:self.assertIn('xl/worksheets/sheet1.xml',workbook.namelist())
            if fmt=='pdf':self.assertTrue(result.data.startswith(b'%PDF-'))
        from sanequeue.reporting.cdr_aggregate_export import render
        def revoke(*args,**kwargs):
            result=render(*args,**kwargs);denied.append('report_export');return result
        with patch('sanequeue.api.reports.cdr_aggregate_export.render',side_effect=revoke):
            response=client.post('/api/history/cdr/aggregate/performance/export.csv'+self.query,headers=hdr)
        self.assertEqual(response.status_code,403)
        self.assertNotIn('PJSIP/100',response.get_data(as_text=True))

    def test_reason_analysis_rechecks_permissions_after_aggregation(self):
        from sanequeue.reporting.cdr_reasons import Reasons
        with self.case.archive.writer() as db:db.execute("DELETE FROM report_visits WHERE queue='8002'")
        denied=[];client=self.case.client(role='admin',menus=('reports','users'),details=True,denied=denied)
        real=Reasons.summarize
        def revoke(store,keys,**kwargs):
            value=real(store,keys,**kwargs);denied.append('caller_details');return value
        with patch('sanequeue.reporting.cdr_reasons.Reasons.summarize',new=revoke):
            result=client.get('/api/history/cdr/classification/analysis'+self.query)
        self.assertEqual(result.status_code,403)
        self.assertNotIn('rows',result.json)

    def test_trend_uses_global_access_and_filters(self):
        self.assertEqual(self.case.client(role='supervisor',menus=('reports','users')).get('/api/history/cdr/trend'+self.query).status_code,403)
        with self.case.archive.writer() as db:db.execute("DELETE FROM report_visits WHERE queue='8002'")
        client=self.case.client(role='admin',menus=('reports','users'),details=True)
        response=client.get('/api/history/cdr/trend'+self.query+'&bucket=day&direction=outbound')
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(sum(row['outbound'] for row in response.json['rows']),1)

    def test_endpoint_drilldown_requires_number_grant_and_inventory_evidence(self):
        with self.case.archive.writer() as db:db.execute("DELETE FROM report_visits WHERE queue='8002'")
        url='/api/history/cdr'+self.query+'&endpoint=PJSIP%2F100'
        self.assertEqual(self.case.client(role='admin',menus=('reports','users')).get(url).status_code,403)
        full=self.case.client(role='admin',menus=('reports','users'),details=True)
        result=full.get(url);self.assertEqual(result.status_code,200,result.get_data(as_text=True))
        self.assertEqual([row['id'] for row in result.json['rows']],['segment'])
        self.assertEqual(full.get(url.replace('PJSIP%2F100','SIP%2F200')).json['rows'],[])
        multi=url.replace('PJSIP%2F100','PJSIP%2F100%2CSIP%2F200')
        self.assertEqual([row['id'] for row in full.get(multi).json['rows']],['segment'])
        self.assertEqual(self.case.client(role='admin',menus=('reports','users')).get(multi).status_code,403)
        self.assertEqual(full.get(url.replace('PJSIP%2F100','PJSIP%2F100%27%20OR%201')).status_code,400)

    def test_cdr_api_bounded_page_limit_and_cursor(self):
        with self.case.archive.writer() as db:db.execute("DELETE FROM report_visits WHERE queue='8002'")
        case=self.case
        case.archive.append([Event('cdr','segment2',case.stamp+11,'CDR',dict(
            src='100',dst='200',duration=4,billsec=2,disposition='ANSWERED'))])
        project_batch(case.archive)
        client=case.client(role='admin',menus=('reports','users'),details=True)
        first=client.get('/api/history/cdr'+self.query+'&limit=1')
        self.assertEqual(first.status_code,200);self.assertEqual(len(first.json['rows']),1)
        cursor=first.json['next'];self.assertIsNotNone(cursor)
        second=client.get('/api/history/cdr'+self.query+'&limit=1&before_time='+str(cursor[0])+'&before_id='+cursor[1])
        self.assertEqual(second.status_code,200);self.assertEqual(len(second.json['rows']),1)
        self.assertNotEqual(first.json['rows'][0]['id'],second.json['rows'][0]['id'])
        self.assertEqual(client.get('/api/history/cdr'+self.query+'&limit=0').status_code,400)

    def test_masked_output_search_gate_and_global_aggregate_alignment(self):
        # Restrict the synthetic archive to a single authorized queue.
        with self.case.archive.writer() as db:
            db.execute("DELETE FROM report_visits WHERE queue='8002'")
        masked=self.case.client(role='admin',menus=('reports','users'))
        response=masked.get('/api/history/cdr'+self.query)
        self.assertEqual(response.status_code,200,response.json)
        row=response.json['rows'][0]
        self.assertNotEqual(row['dst'],'09123456789')
        self.assertFalse(response.json['can_search_numbers'])
        self.assertNotIn('private',response.get_data(as_text=True))
        self.assertFalse(response.json['audio_granted'])
        self.assertEqual(masked.get('/api/history/cdr'+self.query+'&party=100').status_code,403)
        self.assertEqual(masked.get('/api/history/cdr/unique-inbound'+self.query).status_code,403)
        hidden_summary=masked.get('/api/history/cdr/summary'+self.query)
        self.assertEqual(hidden_summary.status_code,200,hidden_summary.json)
        self.assertNotIn('02188888888',hidden_summary.get_data(as_text=True))
        self.assertEqual(hidden_summary.json['endpoints'],[])
        self.assertNotIn('PJSIP/100',hidden_summary.get_data(as_text=True))
        full=self.case.client(role='admin',menus=('reports','users'),details=True)
        response=full.get('/api/history/cdr'+self.query+'&origin=100')
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(len(response.json['rows']),1)
        summary=full.get('/api/history/cdr/summary'+self.query+'&origin=100')
        self.assertEqual(summary.status_code,200)
        self.assertEqual(summary.json['totals']['segments_started'],1)
        self.assertEqual(summary.json['endpoints'][0]['endpoint'],'PJSIP/100')
        self.assertEqual(sum(row['segments_started'] for row in summary.json['trunk_traffic']),1)
        self.assertEqual(summary.json['trunk_traffic'][0]['did'],'02188888888')
        self.assertEqual(full.get('/api/history/cdr'+self.query+'&queue=8001').status_code,403)
        unique=full.get('/api/history/cdr/unique-inbound'+self.query)
        self.assertEqual(unique.status_code,200,unique.json);self.assertEqual(unique.json['total_unique'],0)
        self.assertNotIn('02199999999',unique.get_data(as_text=True))

    def test_repeated_inbound_counts_require_full_number_permission_and_hide_numbers(self):
        case=self.case
        with case.archive.writer() as db:db.execute("DELETE FROM report_visits WHERE queue='8002'")
        inbound=dict(src='09120000001',dst='100',channel='PJSIP/provider-000000aa',
                     dstchannel='PJSIP/100-000000ab',duration=10,billsec=5,disposition='ANSWERED')
        case.archive.append([Event('cdr','in1',case.stamp+20,'CDR',inbound),
                             Event('cdr','in2',case.stamp+21,'CDR',inbound)])
        while project_batch(case.archive,inventory=dict(observed_at=case.stamp,endpoints=[
            dict(technology='PJSIP',endpoint='100',category='extension'),
            dict(technology='PJSIP',endpoint='provider',category='trunk')]))['processed']:
            pass
        url='/api/history/cdr/unique-inbound'+self.query
        self.assertEqual(case.client(role='admin',menus=('reports','users')).get(url).status_code,403)
        response=case.client(role='admin',menus=('reports','users'),details=True).get(url)
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual((response.json['total_unique'],response.json['repeat_numbers']),(1,1))
        self.assertEqual(response.json['repeat_number_percent'],100.0)
        self.assertNotIn('09120000001',response.get_data(as_text=True))
        export=url.replace('/unique-inbound?', '/unique-inbound/export.csv?')+'&lang=en'
        self.assertEqual(case.client(role='admin',menus=('reports','users'),details=True).post(export).status_code,403)
        def ready(**kwargs):
            client=case.client(role='admin',menus=('reports','users'),**kwargs)
            with client.session_transaction() as state:state['csrf_token']='token'
            return client
        self.assertEqual(ready().post(export,headers={'X-CSRF-Token':'token'}).status_code,403)
        self.assertEqual(ready(details=True,denied=('report_export',)).post(export,headers={'X-CSRF-Token':'token'}).status_code,403)
        exported=ready(details=True).post(export,headers={'X-CSRF-Token':'token'})
        self.assertEqual(exported.status_code,200,exported.get_data(as_text=True))
        rows=list(csv.DictReader(io.StringIO(exported.data.decode('utf-8-sig'))))
        self.assertEqual(rows[0]['period_distinct_numbers'],'1')
        self.assertEqual(rows[0]['period_multi_segment_numbers'],'1')
        self.assertEqual(rows[0]['period_multi_segment_percent'],'100.0')
        self.assertNotIn('09120000001',exported.get_data(as_text=True))
        for fmt in ('xlsx','pdf'):
            with self.subTest(format=fmt):
                document=ready(details=True).post(export.replace('export.csv','export.'+fmt),headers={'X-CSRF-Token':'token'})
                self.assertEqual(document.status_code,200,document.data[:200])
                if fmt=='pdf':self.assertTrue(document.data.startswith(b'%PDF-'))
                else:
                    with ZipFile(io.BytesIO(document.data)) as workbook:
                        self.assertIn('xl/worksheets/sheet1.xml',workbook.namelist())
                        self.assertNotIn(b'09120000001',workbook.read('xl/worksheets/sheet1.xml'))

    def test_unique_inbound_export_rechecks_export_permission(self):
        from sanequeue.reporting.cdr_queries import unique_inbound_csv
        with self.case.archive.writer() as db:db.execute("DELETE FROM report_visits WHERE queue='8002'")
        denied=[]
        client=self.case.client(role='admin',menus=('reports','users'),details=True,denied=denied)
        with client.session_transaction() as state:state['csrf_token']='token'
        def revoke(*args,**kwargs):
            result=unique_inbound_csv(*args,**kwargs)
            denied.append('report_export')
            return result
        with patch('sanequeue.api.reports.cdr_queries.unique_inbound_csv',side_effect=revoke):
            response=client.post('/api/history/cdr/unique-inbound/export.csv'+self.query+'&lang=en',headers={'X-CSRF-Token':'token'})
        self.assertEqual(response.status_code,403)
        self.assertNotIn('period_distinct_numbers',response.get_data(as_text=True))

    def test_unique_inbound_export_refuses_limited_results(self):
        with self.case.archive.writer() as db:db.execute("DELETE FROM report_visits WHERE queue='8002'")
        client=self.case.client(role='admin',menus=('reports','users'),details=True)
        with client.session_transaction() as state:state['csrf_token']='token'
        with patch('sanequeue.api.reports.cdr_queries.unique_inbound',return_value={'state':'limited'}):
            response=client.post('/api/history/cdr/unique-inbound/export.csv'+self.query,headers={'X-CSRF-Token':'token'})
        self.assertEqual(response.status_code,422)
        self.assertNotIn('text/csv',response.headers.get('Content-Type',''))

    def test_unique_inbound_rechecks_revoked_number_access_before_response(self):
        from sanequeue.reporting.cdr_queries import unique_inbound
        with self.case.archive.writer() as db:db.execute("DELETE FROM report_visits WHERE queue='8002'")
        denied=[]
        client=self.case.client(role='admin',menus=('reports','users'),details=True,denied=denied)
        def revoke(*args,**kwargs):
            result=unique_inbound(*args,**kwargs)
            denied.append('caller_details')
            return result
        with patch('sanequeue.api.reports.cdr_queries.unique_inbound',side_effect=revoke):
            response=client.get('/api/history/cdr/unique-inbound'+self.query)
        self.assertEqual(response.status_code,403)
        self.assertNotIn('repeat_numbers',response.get_data(as_text=True))


if __name__=='__main__':unittest.main()
