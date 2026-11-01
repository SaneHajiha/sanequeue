import unittest
import csv
import io
from zipfile import ZipFile
from unittest.mock import patch
from tests.test_reporting_cdr_api import CDRAPITests
from sanequeue.reporting.outbound_dashboard import report
from sanequeue.reporting.store import QueryDeadline


class OutboundDashboardTests(unittest.TestCase):
    def setUp(self):
        fixture=CDRAPITests();fixture.setUp();self.addCleanup(fixture.case.doCleanups);self.c=fixture.case
        with self.c.archive.writer() as db:
            db.execute("DELETE FROM report_visits WHERE queue='8002'")
            base=self.c.stamp
            for i,(disp,duration,bill,dest) in enumerate([('ANSWERED',30,5,'09123456789'),('BUSY',7,0,'09123456789'),('ANSWERED',8,None,'09111111111'),('UNKNOWN',4,None,'')]):
                key='synthetic'+str(i)
                db.execute('INSERT INTO report_cdr VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    ('primary',key,100+i,base+20+i,'','','100',dest,'','',duration,bill,disp,''))
                db.execute('INSERT INTO report_cdr_parties VALUES(?,?,?,?,?)',('primary',key,'100','outbound',base+20+i))
        self.start=self.c.stamp;self.end=self.start+100;self.query='?from=2026-10-24&to=2026-10-25'

    def test_segments_denominators_and_uncertain_human_answer(self):
        result=report(self.c.archive,self.start,self.end,numbers=True);total=result['totals']
        self.assertEqual((total['segments'],total['answered'],total['unanswered'],total['unknown']),(5,3,1,1))
        self.assertEqual(total['known_dispositions'],4);self.assertEqual(total['technical_answer_rate'],75)
        self.assertEqual((result['dispositions']['ANSWERED'],result['dispositions']['BUSY'],result['dispositions']['OTHER']),(3,1,1))
        self.assertEqual((total['answered_known_billsec'],total['short_answered']),(2,1))
        self.assertEqual(total['short_answered_rate'],50);self.assertEqual(total['average_answered_billsec'],12.5)
        self.assertEqual(total['average_pre_answer'],17.5);self.assertEqual(total['known_setup'],2)
        self.assertEqual(result['unique_destinations'],2);self.assertEqual(result['unknown_destination'],1)
        self.assertIn('not_proof_of_human',result['definitions']['technical_answer'])
        self.assertEqual(sum(x['segments'] for x in result['origins']),total['segments'])
        self.assertNotIn('09123456789',str(result))

    def test_bounded_scope_and_role_number_policy(self):
        with patch('sanequeue.reporting.outbound_dashboard.MAX_SEGMENTS',1):
            with self.assertRaises(QueryDeadline):report(self.c.archive,self.start,self.end)
        masked=self.c.client(role='admin',menus=('reports','users'),details=False)
        response=masked.get('/api/history/cdr/outbound-dashboard'+self.query)
        self.assertEqual(response.status_code,200,response.json);self.assertIsNone(response.json['unique_destinations'])
        self.assertNotIn('09123456789',response.text);self.assertNotIn('02199999999',response.text)
        self.assertEqual(masked.get('/api/history/cdr/outbound-dashboard'+self.query+'&party=100').status_code,403)
        self.assertEqual(self.c.client(role='supervisor',menus=('reports','users'),details=True).get('/api/history/cdr/outbound-dashboard'+self.query).status_code,403)
        full=self.c.client(role='admin',menus=('reports','users'),details=True)
        self.assertEqual(full.get('/api/history/cdr/outbound-dashboard'+self.query+'&direction=inbound').status_code,400)

    def test_permission_is_rechecked_after_archive_read(self):
        denied=[];client=self.c.client(role='admin',menus=('reports','users'),details=True,denied=denied)
        original=report
        def revoke(*args,**kwargs):
            result=original(*args,**kwargs);denied.append('caller_details');return result
        with patch('sanequeue.api.reports.outbound_dashboard.report',side_effect=revoke):
            response=client.get('/api/history/cdr/outbound-dashboard'+self.query)
        self.assertEqual(response.status_code,403);self.assertNotIn('09123456789',response.text)

    def test_export_tables_match_aggregate_and_enforce_csrf_permissions(self):
        client=self.c.client(role='admin',menus=('reports','users'),details=True)
        with client.session_transaction() as state:state['csrf_token']='token'
        url='/api/history/cdr/outbound-dashboard/export.csv'+self.query
        self.assertEqual(client.post(url+'&table=origins&lang=en').status_code,403)
        headers={'X-CSRF-Token':'token'}
        baseline=client.get('/api/history/cdr/outbound-dashboard'+self.query).json
        for table in ('origins','days','dispositions'):
            response=client.post(url+'&table='+table+'&lang=en',headers=headers)
            self.assertEqual(response.status_code,200,response.json)
            self.assertEqual(response.headers['X-SaneQueue-Unit'],'outbound_cdr_segment')
            rows=list(csv.DictReader(io.StringIO(response.data.decode('utf-8-sig'))))
            self.assertEqual(sum(int(row['segments']) for row in rows),baseline['totals']['segments'])
            self.assertNotIn('09123456789',response.get_data(as_text=True))
            if table=='origins':self.assertTrue(all(not row['origin'] or row['origin'].startswith("'") for row in rows))
        self.assertEqual(client.post(url+'&table=bogus',headers=headers).status_code,400)
        masked=self.c.client(role='admin',menus=('reports','users'),details=False)
        with masked.session_transaction() as state:state['csrf_token']='token'
        masked_file=masked.post(url+'&table=origins&lang=fa',headers=headers)
        self.assertEqual(masked_file.status_code,200);self.assertNotIn("'100",masked_file.get_data(as_text=True))
        self.assertIn('شروع تهران',masked_file.get_data(as_text=True))
        denied=self.c.client(role='admin',menus=('reports','users'),details=True,denied=['report_export'])
        with denied.session_transaction() as state:state['csrf_token']='token'
        self.assertEqual(denied.post(url+'&table=origins',headers=headers).status_code,403)

    def test_export_rechecks_access_after_generation(self):
        denied=[];client=self.c.client(role='admin',menus=('reports','users'),details=True,denied=denied)
        with client.session_transaction() as state:state['csrf_token']='token'
        from sanequeue.reporting.outbound_dashboard import csv_bytes
        def revoke(*args,**kwargs):
            result=csv_bytes(*args,**kwargs);denied.append('report_export');return result
        with patch('sanequeue.api.reports.outbound_dashboard.csv_bytes',side_effect=revoke):
            response=client.post('/api/history/cdr/outbound-dashboard/export.csv'+self.query+'&table=origins',headers={'X-CSRF-Token':'token'})
        self.assertEqual(response.status_code,403);self.assertNotIn('09123456789',response.text)

    def test_excel_and_pdf_export_all_tables_and_obey_row_limit(self):
        client=self.c.client(role='admin',menus=('reports','users'),details=True)
        with client.session_transaction() as state:state['csrf_token']='token'
        headers={'X-CSRF-Token':'token'}
        for table in ('origins','days','dispositions'):
            xlsx=client.post('/api/history/cdr/outbound-dashboard/export'+self.query+'&format=xlsx&table='+table+'&lang=en',headers=headers)
            self.assertEqual(xlsx.status_code,200,xlsx.json)
            with ZipFile(io.BytesIO(xlsx.data)) as archive:
                xml=archive.read('xl/worksheets/sheet1.xml')
                self.assertIn(b'period_start_tehran',xml);self.assertNotIn(b'<f>',xml)
                if table=='origins':self.assertIn(b'>100<',xml)
            pdf=client.post('/api/history/cdr/outbound-dashboard/export'+self.query+'&format=pdf&table='+table+'&lang=fa',headers=headers)
            self.assertEqual(pdf.status_code,200,pdf.json);self.assertTrue(pdf.data.startswith(b'%PDF-'))
        data=report(self.c.archive,self.start,self.end,numbers=True)
        data['origins']=[dict(data['origins'][0]) for _ in range(101)]
        with patch('sanequeue.api.reports.outbound_dashboard.report',return_value=data):
            limited=client.post('/api/history/cdr/outbound-dashboard/export.pdf'+self.query+'&table=origins',headers=headers)
        self.assertEqual(limited.status_code,422);self.assertFalse(limited.data.startswith(b'%PDF-'))

    def test_pdf_export_rechecks_number_permission_before_download(self):
        denied=[];client=self.c.client(role='admin',menus=('reports','users'),details=True,denied=denied)
        with client.session_transaction() as state:state['csrf_token']='token'
        from sanequeue.reporting.outbound_dashboard import document_bytes
        def revoke(*args,**kwargs):
            value=document_bytes(*args,**kwargs);denied.append('caller_details');return value
        with patch('sanequeue.api.reports.outbound_dashboard.document_bytes',side_effect=revoke):
            response=client.post('/api/history/cdr/outbound-dashboard/export.pdf'+self.query+'&table=origins',headers={'X-CSRF-Token':'token'})
        self.assertEqual(response.status_code,403);self.assertFalse(response.data.startswith(b'%PDF-'))


if __name__=='__main__':unittest.main()
