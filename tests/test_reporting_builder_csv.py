"""Exact bounded custom CSV, real SQLite snapshots and fresh publication grants."""
from contextlib import contextmanager
import csv
import io
import unittest
from unittest.mock import patch

from tests import test_reporting_builder as fixtures
from tests import test_reporting_builder_api as api_fixtures
from sanequeue.reporting.report_builder import export_csv
from sanequeue.reporting.store import Archive
from sanequeue.reporting.queries import Scope


def decode(data):return list(csv.reader(io.StringIO(data.decode('utf-8-sig'))))


class BuilderCSVTests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.BuilderTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.spec={**self.case.spec,'columns':['agent','caller','wait_seconds','id']}

    def export(self,spec=None,**kwargs):
        return export_csv(self.case.archive,Scope(('8001',)),90,300,spec or self.spec,number_modes={'8001':'masked'},**kwargs)

    def many(self,count):
        with self.case.archive.writer() as db:
            db.executemany('INSERT INTO report_visits VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',[
                ('primary',format(n,'064x'),'private-call','8001',100,110,130,'09123456789','100','answered',10,20,'caller','observed') for n in range(count)])

    def test_exports_full_definition_beyond_preview_page_with_order_and_text_ids(self):
        self.many(151)
        content,meta=self.export();rows=decode(content)
        self.assertTrue(content.startswith(b'\xef\xbb\xbf'))
        self.assertEqual(rows[0],self.spec['columns']);self.assertEqual(len(rows),152)
        self.assertEqual(rows[1][:3],["'100","'0912***6789",'10'])
        self.assertEqual(rows[1][3],"'"+format(150,'064x'))
        self.assertEqual(meta['rows'],151);self.assertEqual(len(meta['definition_sha256']),64)
        self.assertNotIn(b'private-call',content);self.assertNotIn(b'09123456789',content)

    def test_filters_and_grouped_unknown_denominators_match_preview(self):
        self.case.add(1,wait=10,talk=20);self.case.add(2,wait=None,talk=None,outcome='abandoned',answered=None)
        filtered={**self.spec,'filters':{'wait_min':5,'wait_max':12,'outcomes':['answered']}}
        self.assertEqual(self.export(filtered)[1]['rows'],1)
        grouped={**self.spec,'group_by':['queue']}
        rows=decode(self.export(grouped)[0]);values=dict(zip(rows[0],rows[1]))
        self.assertEqual(values['visits'],'2');self.assertEqual(values['wait_known'],'1')
        self.assertEqual(values['talk_known'],'1');self.assertEqual(values['average_queue_talk_seconds'],'20')

    def test_rejects_over_cap_and_byte_limit_without_partial_result(self):
        self.many(501)
        with self.assertRaisesRegex(ValueError,'builder_export_row_limit'):self.export()
        with self.case.archive.writer() as db:db.execute('DELETE FROM report_visits WHERE id=?',(format(500,'064x'),))
        self.assertEqual(self.export()[1]['rows'],500)
        with patch('sanequeue.reporting.report_builder.EXPORT_MAX_BYTES',16):
            with self.assertRaisesRegex(ValueError,'builder_export_byte_limit'):self.export()

    def test_source_formulas_and_unicode_are_safe_and_persian_dates_are_readable(self):
        self.case.add(1,agent='=SUM(1,2)')
        content,_=self.export({**self.spec,'columns':['agent','entered','outcome']},language='fa')
        rows=decode(content);self.assertEqual(rows[1][0],"'=SUM(1,2)")
        self.assertIn('/',rows[1][1]);self.assertEqual(rows[1][2],'پاسخ‌داده')
        with self.assertRaisesRegex(ValueError,'invalid_builder_language'):self.export(language='xx')

    def test_projection_and_rows_share_one_snapshot_despite_concurrent_writer(self):
        self.case.add(1)
        original=Archive.reader;archive=self.case.archive;changed=[]
        @contextmanager
        def reader(instance):
            with original(instance) as db:
                class Connection:
                    def execute(self,sql,args=()):
                        cursor=db.execute(sql,args)
                        if 'SELECT after_id,updated FROM report_projection' in sql and not changed:
                            changed.append(True)
                            with archive.writer() as write:
                                write.execute("UPDATE report_visits SET caller='09999999999'")
                                write.execute('UPDATE report_projection SET after_id=99')
                        return cursor
                yield Connection()
        with patch.object(Archive,'reader',reader):content,meta=self.export()
        self.assertEqual(meta['projection']['after_id'],0)
        self.assertEqual(decode(content)[1][1],"'0912***6789")
        with archive.reader() as db:self.assertEqual(db.execute('SELECT after_id FROM report_projection').fetchone()[0],99)


class BuilderCSVAPITests(unittest.TestCase):
    def setUp(self):
        self.case=api_fixtures.BuilderAPITests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.client=self.case.client;self.path='/api/history/builder/export.csv';self.body={'definition':self.case.spec,'language':'en'}
    def post(self,body=None,headers=True):return self.client.post(self.path,json=body or self.body,headers=self.case.headers if headers else {})
    def test_csrf_current_scope_role_and_private_download_headers(self):
        self.assertEqual(self.post(headers=False).status_code,403)
        response=self.post();self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.mimetype,'text/csv');self.assertEqual(response.headers['Cache-Control'],'private, no-store')
        self.assertEqual(response.headers['X-SaneQueue-Export-Rows'],'1');self.assertIn('attachment;',response.headers['Content-Disposition'])
        self.assertNotIn('09123456789',response.text)
        self.case.role='agent';self.assertEqual(self.post().status_code,403)
        self.case.role='supervisor';self.case.scope=Scope(('8002',));self.assertEqual(self.post().status_code,403)
    def test_rechecks_all_queues_number_grants_and_cutoff_after_generation(self):
        from sanequeue.api import report_builder as adapter
        actual=adapter.export_csv
        for revoke in ('scope','details','cutoff'):
            self.case.scope=Scope(('8001',));self.case.full=True
            def generate(*args,**kwargs):
                result=actual(*args,**kwargs)
                if revoke=='scope':self.case.scope=Scope(('8002',))
                elif revoke=='details':self.case.full=False
                else:self.case.scope=Scope(('8001',),not_before=self.case.case.stamp+20)
                return result
            with self.subTest(revoke=revoke),patch.object(adapter,'export_csv',generate):
                response=self.post();self.assertEqual(response.status_code,403);self.assertNotIn(b'09123456789',response.data)
    def test_saved_definition_and_multi_queue_partial_authorization_are_private(self):
        created=self.client.post('/api/history/builder/templates',json={'name':'Private','definition':self.case.spec},headers=self.case.headers)
        ident=created.json['template']['id']
        response=self.post({'template_id':ident,'language':'en'});self.assertEqual(response.status_code,200)
        self.assertEqual(decode(response.data)[0],self.case.spec['columns'])
        invalid={**self.case.spec,'queues':['8001','8002']}
        self.assertEqual(self.post({'definition':invalid}).status_code,403)
    def test_every_selected_queue_requires_export_permission_before_and_after_read(self):
        from sanequeue.api import report_builder as adapter
        with patch.object(adapter,'install'):
            client=self.case.case.client(role='admin',menus=('reports',),details=True)
        allowed={'8001','8002'}
        adapter.install(client.application,self.case.case.archive,
            context=lambda **kw:(Scope(('8001','8002')),self.case.case.stamp,self.case.case.stamp+100),
            role=lambda:'supervisor',sections=lambda:['reports'],
            can_queue=lambda queue,action:action!='report_export' or queue in allowed)
        with client.session_transaction() as state:state['csrf_token']='token'
        body={'definition':{**self.case.spec,'queues':['8001','8002']}}
        allowed.remove('8002')
        response=client.post(self.path,json=body,headers=self.case.headers);self.assertEqual(response.status_code,403)
        allowed.add('8002');actual=adapter.export_csv
        def generate(*args,**kwargs):
            result=actual(*args,**kwargs);allowed.remove('8002');return result
        with patch.object(adapter,'export_csv',generate):
            response=client.post(self.path,json=body,headers=self.case.headers)
        self.assertEqual(response.status_code,403);self.assertNotIn(b'09123456789',response.data)
    def test_parallel_exports_are_bounded_and_slot_is_released_after_failure(self):
        from sanequeue.api import report_builder as adapter
        actual=adapter.export_csv;parallel=[]
        def generate(*args,**kwargs):
            parallel.append(self.post())
            return actual(*args,**kwargs)
        with patch.object(adapter,'export_csv',generate):response=self.post()
        self.assertEqual(response.status_code,200)
        self.assertEqual(parallel[0].status_code,429)
        self.assertEqual(parallel[0].json,{'error':'builder_export_busy'})
        with patch.object(adapter,'export_csv',side_effect=ValueError('builder_export_row_limit')):
            self.assertEqual(self.post().status_code,400)
        self.assertEqual(self.post().status_code,200)


if __name__=='__main__':unittest.main()
