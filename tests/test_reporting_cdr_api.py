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

    def test_trend_uses_global_access_and_filters(self):
        self.assertEqual(self.case.client(role='supervisor',menus=('reports','users')).get('/api/history/cdr/trend'+self.query).status_code,403)
        with self.case.archive.writer() as db:db.execute("DELETE FROM report_visits WHERE queue='8002'")
        client=self.case.client(role='admin',menus=('reports','users'),details=True)
        response=client.get('/api/history/cdr/trend'+self.query+'&bucket=day&direction=outbound')
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(sum(row['outbound'] for row in response.json['rows']),1)

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
