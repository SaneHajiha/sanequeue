import csv
import io
import unittest
from unittest.mock import patch
from tests.test_reporting_cdr import CDRTests
from tests.test_reporting_cdr_api import CDRAPITests
from sanequeue.reporting import cdr_builder
from sanequeue.reporting.store import QueryDeadline


class CDRBuilderTests(unittest.TestCase):
    def setUp(self):
        self.case=CDRTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.case.seed(self.case.event('one'),self.case.event('two',160,src='02188888888',disposition='NO ANSWER',billsec=None),
                       self.case.event('three',170,src='=cmd',disposition=None,billsec=None))
        self.spec=dict(columns=['src','dst','direction','disposition','billsec'],group_by=[])

    def test_preview_masks_numbers_and_groups_full_source_with_known_denominators(self):
        a=self.case.archive
        detail=cdr_builder.report(a,100,200,{},self.spec,numbers=False,secret=b'x'*32)
        self.assertEqual(detail['source_segments'],3);self.assertEqual(len(detail['rows']),3)
        self.assertNotIn('09123456789',str(detail));self.assertEqual(detail['unit'],'cdr_segment')
        grouped=cdr_builder.report(a,100,200,{},dict(columns=['src'],group_by=['direction']),numbers=False,secret=b'x'*32)
        self.assertEqual(len(grouped['rows']),1);row=grouped['rows'][0]
        self.assertEqual((row['segments'],row['answered'],row['unanswered'],row['unknown_disposition']),(3,1,1,1))
        self.assertEqual(row['known_billsec'],1);self.assertEqual(row['average_billsec_seconds'],30)
        self.assertNotIn('src',row)

    def test_allowlist_filter_and_limits_fail_closed(self):
        a=self.case.archive
        self.assertEqual(cdr_builder.report(a,100,200,{'disposition':'ANSWERED'},self.spec,numbers=True,secret=b'x'*32)['source_segments'],1)
        for spec in (dict(columns=['secret_sql'],group_by=[]),dict(columns=['src'],group_by=['src']),dict(columns=['src','src'],group_by=[])):
            with self.subTest(spec=spec),self.assertRaises(ValueError):cdr_builder.report(a,100,200,{},spec,numbers=True,secret=b'x'*32)
        with patch('sanequeue.reporting.cdr_builder.MAX_SEGMENTS',2):
            with self.assertRaises(QueryDeadline):cdr_builder.report(a,100,200,{},self.spec,numbers=True,secret=b'x'*32)
        with patch('sanequeue.reporting.cdr_builder.MAX_SOURCE_BYTES',1):
            with self.assertRaises(QueryDeadline):cdr_builder.report(a,100,200,{},self.spec,numbers=True,secret=b'x'*32)
        with a.writer() as db:db.execute("UPDATE report_cdr SET src=? WHERE source_key='one'",('X'*3000,))
        with self.assertRaises(ValueError):cdr_builder.report(a,100,200,{},self.spec,numbers=True,secret=b'x'*32)

    def test_csv_has_no_formula_execution_and_preserves_leading_zero(self):
        data=dict(columns=['src','trunk'],rows=[dict(src='09123456789',trunk='=HYPERLINK("x")')])
        rows=list(csv.reader(io.StringIO(cdr_builder.csv_bytes(data,'en').decode('utf-8-sig'))))
        self.assertEqual(rows[1],["'09123456789", "'=HYPERLINK(\"x\")"])
        with patch('sanequeue.reporting.cdr_builder.MAX_CSV_ROWS',0):
            with self.assertRaises(ValueError):cdr_builder.csv_bytes(data,'en')


class CDRBuilderAPITests(unittest.TestCase):
    def setUp(self):
        self.case=CDRAPITests();self.case.setUp();self.addCleanup(self.case.case.doCleanups)
        self.c=self.case.case
        with self.c.archive.writer() as db:db.execute("DELETE FROM report_visits WHERE queue='8002'")
        self.query='?from=2026-10-24&to=2026-10-25';self.body=dict(definition=dict(columns=['src','dst','billsec'],group_by=[]),language='en')

    def test_preview_and_export_require_global_role_csrf_and_export_grant(self):
        path='/api/history/cdr/builder/preview'+self.query
        client=self.c.client(role='admin',menus=('reports','users'),details=False)
        with client.session_transaction() as state:state['csrf_token']='token'
        self.assertEqual(client.post(path,json=self.body).status_code,403)
        result=client.post(path,json=self.body,headers={'X-CSRF-Token':'token'})
        self.assertEqual(result.status_code,200,result.json);self.assertNotIn('09123456789',result.text)
        self.assertEqual(result.json['number_policy'],'masked')
        self.assertEqual(self.c.client(role='supervisor',menus=('reports','users'),details=True).post(path,json=self.body,headers={'X-CSRF-Token':'token'}).status_code,403)
        export=client.post(path.replace('/preview','/export.csv'),json=self.body,headers={'X-CSRF-Token':'token'})
        self.assertEqual(export.status_code,200);self.assertNotIn(b'09123456789',export.data)
        denied=self.c.client(role='admin',menus=('reports','users'),details=True,denied=('report_export',))
        with denied.session_transaction() as state:state['csrf_token']='token'
        self.assertEqual(denied.post(path.replace('/preview','/export.csv'),json=self.body,headers={'X-CSRF-Token':'token'}).status_code,403)

    def test_preview_pagination_cap_and_authority_recheck(self):
        path='/api/history/cdr/builder/preview'+self.query;denied=[]
        client=self.c.client(role='admin',menus=('reports','users'),details=True,denied=denied)
        with client.session_transaction() as state:state['csrf_token']='token'
        real=cdr_builder.report
        def revoke(*args,**kwargs):
            result=real(*args,**kwargs);denied.append('view');return result
        with patch('sanequeue.api.reports.cdr_builder.report',side_effect=revoke):
            response=client.post(path,json=self.body,headers={'X-CSRF-Token':'token'})
        self.assertEqual(response.status_code,403);self.assertNotIn('09123456789',response.text)


if __name__=='__main__':unittest.main()
