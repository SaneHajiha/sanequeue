import csv
import io
import json
import os
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from tests.test_reporting_cdr import CDRTests
from sanequeue.reporting import cdr_builder
from sanequeue.reporting.export_jobs import JobStore,ExportWorker,Limits,projection_watermark,local_authorizer
from sanequeue.reporting.queries import Scope


class CDRBuilderJobTests(unittest.TestCase):
    def setUp(self):
        self.case=CDRTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.case.seed(self.case.event('one'),self.case.event('two',160,src='02188888888',disposition='NO ANSWER',billsec=None))
        self.archive=self.case.archive
        with self.archive.writer() as db:
            db.execute('INSERT INTO report_visits VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                ('primary','a'*64,'q1','8001',110,111,130,'09123456789','100','answered',1,19,'caller','observed'))
        self.store=JobStore(self.archive.path.parent/'jobs.db',self.archive.path.parent/'outputs');self.store.initialize()
        self.scope=Scope(('8001',));self.spec=dict(columns=['src','dst','disposition','billsec'],group_by=[])
        self.worker=ExportWorker(self.store,self.archive,limits=Limits(page_size=2,min_free_bytes=0,max_load_per_cpu=0),authorize=lambda spec:True,disabled_file=self.archive.path.parent/'disabled')
        self.addCleanup(lambda:getattr(self.worker,'reconciler',None) and self.worker.reconciler.close())

    def create(self,**kwargs):
        filters=kwargs.pop('cdr_filters',{})
        return self.store.create('alice',self.scope,100,200,watermark=projection_watermark(self.archive),
            number_modes={'8001':'masked'},cdr_definition=self.spec,cdr_filters=filters,**kwargs)

    def read(self,ident):
        fd,size=self.store.open_output(ident,'alice')
        with os.fdopen(fd,'rb') as stream:data=stream.read()
        self.assertEqual(len(data),size);return data

    def test_cdr_csv_xlsx_and_pdf_are_private_and_use_worker_snapshot(self):
        for fmt in ('csv','xlsx','pdf'):
            with self.subTest(fmt=fmt):
                ident=self.create(format=fmt,cdr_filters={'direction':'outbound'});job=self.store.get(ident,'alice')
                self.assertEqual(job['spec']['consistency'],'worker_start_snapshot');self.assertNotIn('snapshot',job['spec'])
                result=self.worker.run_once();self.assertEqual(result['state'],'completed',result);self.assertEqual(result['rows'],2)
                data=self.read(ident);self.assertNotIn(b'09123456789',data)
                if fmt=='csv':
                    rows=list(csv.reader(io.StringIO(data.decode('utf-8-sig'))));self.assertEqual(len(rows),3);self.assertEqual(rows[0],self.spec['columns'])
                elif fmt=='xlsx':
                    with ZipFile(io.BytesIO(data)) as book:
                        sheet=book.read('xl/worksheets/sheet1.xml');self.assertIn(b'Custom PBX CDR report',sheet);self.assertIn(b'direction',sheet);self.assertIn(b'outbound',sheet);self.assertNotIn(b'09123456789',sheet)
                else:self.assertTrue(data.startswith(b'%PDF-'))

    def test_cdr_grouped_export_is_not_queue_visit_and_obeys_scope_changes(self):
        self.spec=dict(columns=['src'],group_by=['direction']);ident=self.create(format='xlsx')
        result=self.worker.run_once();self.assertEqual(result['state'],'completed',result);self.assertEqual(result['rows'],1)
        with ZipFile(io.BytesIO(self.read(ident))) as book:self.assertIn(b'outbound',book.read('xl/worksheets/sheet1.xml'))
        ident=self.create(format='csv')
        with self.archive.writer() as db:
            db.execute('INSERT INTO report_visits VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                ('primary','b'*64,'q2','8002',110,111,130,'09123456789','100','answered',1,19,'caller','observed'))
        self.assertEqual(self.worker.run_once()['error'],'export_access_revoked')
        with self.assertRaises(FileNotFoundError):self.read(ident)

    def test_cdr_snapshot_is_execution_time_and_stable_after_read(self):
        ident=self.create(format='csv');real=cdr_builder.report
        def change_after_read(*args,**kwargs):
            data=real(*args,**kwargs)
            with self.archive.writer() as db:db.execute("UPDATE report_cdr SET billsec=999 WHERE source_key='one'")
            return data
        with patch('sanequeue.reporting.cdr_builder.report',side_effect=change_after_read):
            self.assertEqual(self.worker.run_once()['state'],'completed')
        rows=list(csv.reader(io.StringIO(self.read(ident).decode('utf-8-sig'))))
        self.assertIn('30.0',[row[3] for row in rows[1:]]);self.assertNotIn('999.0',[row[3] for row in rows[1:]])

    def test_cdr_limits_and_invalid_number_filters_fail_closed(self):
        with self.assertRaises(ValueError):self.create(format='csv',cdr_filters={'src':'100'})
        with self.assertRaises(ValueError):self.create(format='csv',cdr_filters={'endpoint':'PJSIP/100'})
        ident=self.create(format='pdf')
        with patch('sanequeue.reporting.pdf_stream.MAX_ROWS',1):
            result=self.worker.run_once()
        self.assertEqual(result['state'],'failed');self.assertEqual(result['error'],'pdf_row_limit')
        with self.assertRaises(FileNotFoundError):self.read(ident)

    def test_cdr_worker_local_authorization_requires_current_admin_and_users_menu(self):
        ident=self.create(format='xlsx');spec=self.store.get(ident,'alice')['spec'];root=self.archive.path.parent
        accounts=root/'accounts.json';policies=root/'policies.json'
        values={'alice':dict(role='admin',phone='PJSIP/100',menus=['reports','users'],password_hash='pbkdf2:sha256:test')}
        accounts.write_text(json.dumps(values),encoding='utf8')
        policies.write_text(json.dumps(dict(version=1,queues={'8001':{}},supervisors={})),encoding='utf8')
        check=local_authorizer(accounts,policies);self.assertTrue(check(spec))
        values['alice']['menus']=['reports'];accounts.write_text(json.dumps(values),encoding='utf8');self.assertFalse(check(spec))
        values['alice'].update(role='supervisor',menus=['reports','users']);accounts.write_text(json.dumps(values),encoding='utf8');self.assertFalse(check(spec))

    def test_cdr_revocation_after_snapshot_never_publishes(self):
        ident=self.create(format='xlsx');real=cdr_builder.report;allowed=[True];self.worker.authorize=lambda spec:allowed[0]
        def revoke(*args,**kwargs):
            result=real(*args,**kwargs);allowed[0]=False;return result
        with patch('sanequeue.reporting.cdr_builder.report',side_effect=revoke):result=self.worker.run_once()
        self.assertEqual(result['error'],'export_access_revoked')
        with self.assertRaises(FileNotFoundError):self.read(ident)
        self.assertFalse(list(self.store.output_dir.glob('*.part')))


if __name__=='__main__':unittest.main()
