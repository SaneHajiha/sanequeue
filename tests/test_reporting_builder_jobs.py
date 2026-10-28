"""Custom CSV/XLSX use immutable queue-visit snapshots and the durable worker."""
import csv
from contextlib import contextmanager
import io
import os
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from tests import test_reporting_export_jobs as fixtures
from sanequeue.reporting.export_jobs import ExportFailure,Limits,projection_watermark
from sanequeue.reporting.report_builder import DEFAULT,preview
from sanequeue.reporting import visit_snapshots
from sanequeue.reporting import builder_exports
from sanequeue.reporting.store import Archive


class BuilderJobTests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.ExportJobTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.spec={**DEFAULT,'queues':['8001'],'columns':['agent','caller','talk_seconds','id']}

    def create(self,spec=None,**kwargs):
        kwargs.setdefault('snapshot',visit_snapshots.capture(self.case.archive))
        return self.case.create(builder_definition=spec or self.spec,**kwargs)

    def read_bytes(self,ident):
        fd,size=self.case.store.open_output(ident,'alice')
        with os.fdopen(fd,'rb') as stream:data=stream.read()
        self.assertEqual(len(data),size);return data

    def run_job(self,**kwargs):
        worker=self.case.worker(**kwargs);result=worker.run_once()
        if hasattr(worker,'reconciler'):worker.reconciler.close()
        return result

    def xlsx_rows(self,ident):
        with ZipFile(io.BytesIO(self.read_bytes(ident))) as file:
            sheet=ET.fromstring(file.read('xl/worksheets/sheet1.xml'))
        ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        rows=[]
        for row in sheet.findall('s:sheetData/s:row',ns):
            rows.append([(cell.findtext('s:is/s:t',namespaces=ns) if cell.get('t')=='inlineStr' else cell.findtext('s:v',namespaces=ns)) for cell in row])
        return sheet,rows,ns

    def test_exact_columns_full_csv_pages_filters_and_frozen_source(self):
        self.case.seed(605)
        with self.case.archive.writer() as db:
            db.execute("UPDATE report_visits SET talk_seconds=1 WHERE CAST(substr(id,60) AS INTEGER)%2=0")
        selected={**self.spec,'filters':{'talk_min':10,'talk_max':30,'outcomes':['answered']}}
        expected=preview(self.case.archive,fixtures.Scope(('8001',)),90,300,selected,number_modes={'8001':'masked'},limit=100)
        ident=self.create(selected);pinned=self.case.store.get(ident,'alice')['spec']['snapshot']
        with self.case.archive.writer() as db:
            db.execute("UPDATE report_visits SET caller='09999999999',talk_seconds=999")
            db.execute('UPDATE report_projection SET after_id=after_id+1')
        self.assertEqual(self.run_job()['state'],'completed')
        rows=self.case.read(ident)
        self.assertEqual(rows[0],selected['columns']);self.assertGreater(len(rows),101)
        self.assertEqual(rows[1][0],"'100");self.assertEqual(rows[1][1],"'0912***6789")
        self.assertEqual(rows[1][3],"'"+expected['rows'][0]['id'])
        self.assertEqual({float(row[2]) for row in rows[1:]},{19})
        self.assertEqual(self.case.store.get(ident,'alice')['spec']['snapshot'],pinned)

    def test_snapshot_filter_uses_latest_pinned_version_not_old_matching_version(self):
        self.case.seed(3)
        with self.case.archive.writer() as db:
            db.execute('UPDATE report_visits SET talk_seconds=99 WHERE id=?',(format(2,'064x'),))
            db.execute('DELETE FROM report_visits WHERE id=?',(format(3,'064x'),))
        ident=self.create({**self.spec,'filters':{'talk_max':30}})
        self.assertEqual(self.run_job()['state'],'completed')
        self.assertEqual(len(self.case.read(ident)),2)

    def test_global_groups_match_preview_known_denominators_across_pages(self):
        self.case.seed(405)
        with self.case.archive.writer() as db:
            db.execute('UPDATE report_visits SET wait_seconds=NULL,talk_seconds=NULL,answered=NULL,outcome=? WHERE id=?',('abandoned',format(1,'064x')))
            db.execute('UPDATE report_visits SET talk_seconds=100,wait_seconds=50 WHERE id=?',(format(405,'064x'),))
        selected={**self.spec,'group_by':['queue','agent']}
        expected=preview(self.case.archive,fixtures.Scope(('8001',)),90,300,selected,number_modes={'8001':'masked'})
        ident=self.create(selected)
        self.assertEqual(self.run_job(limits=Limits(page_size=2,min_free_bytes=0,max_load_per_cpu=0))['state'],'completed')
        rows=self.case.read(ident);self.assertEqual(rows[0],expected['columns']);self.assertEqual(len(rows),2)
        data=dict(zip(rows[0],rows[1]));self.assertEqual(data['visits'],'405');self.assertEqual(data['wait_known'],'404')
        self.assertAlmostEqual(float(data['average_queue_talk_seconds']),expected['rows'][0]['average_queue_talk_seconds'])
        self.assertEqual(float(data['queue_talk_seconds']),expected['rows'][0]['queue_talk_seconds'])
        self.assertEqual(self.case.store.get(ident,'alice')['rows'],1)

    def test_xlsx_exact_headers_inline_identity_dates_and_dynamic_filter(self):
        self.case.seed(2,agent='=HYPERLINK("private")')
        selected={**self.spec,'columns':['caller','agent','entered']}
        ident=self.create(selected,format='xlsx')
        self.assertEqual(self.run_job()['state'],'completed')
        sheet,rows,ns=self.xlsx_rows(ident)
        self.assertEqual(rows[3],selected['columns']);self.assertEqual(len(rows),6)
        self.assertEqual(rows[4][0],'0912***6789');self.assertEqual(rows[4][1],'=HYPERLINK("private")')
        self.assertIn('1970-01-01',rows[4][2]);self.assertEqual(sheet.find('s:autoFilter',ns).get('ref'),'A4:C6')
        self.assertEqual(len(sheet.findall('s:cols/s:col',ns)),3)
        self.assertEqual(sheet.findall('.//s:f',ns),[])

    def test_grouped_xlsx_has_one_full_result_not_multiple_page_averages(self):
        self.case.seed(203)
        ident=self.create({**self.spec,'group_by':['queue']},format='xlsx',language='fa')
        self.assertEqual(self.run_job()['state'],'completed')
        sheet,rows,ns=self.xlsx_rows(ident)
        self.assertEqual(len(rows),5);self.assertEqual(rows[4][1],'203');self.assertEqual(rows[3][0],'صف')
        self.assertEqual(sheet.find('s:sheetViews/s:sheetView',ns).get('rightToLeft'),'1')

    def test_requires_snapshot_matching_queues_supported_format_and_request_identity(self):
        self.case.seed()
        for kwargs in ({'snapshot':None},{'format':'pdf'},{'outcome':'answered'},{'scope':fixtures.Scope(('8001','8002')),'modes':{'8001':'masked','8002':'masked'}}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):self.create(**kwargs)
        ident=self.create(request_key='custom-one')
        self.assertEqual(self.create(request_key='custom-one'),ident)
        with self.assertRaises(ExportFailure):self.create({**self.spec,'columns':['queue']},request_key='custom-one')
        self.assertEqual(self.case.store.get(ident,'alice')['spec']['builder_definition'],self.spec)

    def test_row_and_group_limits_reject_without_publishing_partial(self):
        self.case.seed(5)
        ident=self.create({**self.spec,'group_by':['queue']})
        result=self.run_job(limits=Limits(max_rows=2,min_free_bytes=0,max_load_per_cpu=0))
        self.assertEqual(result['error'],'export_row_limit')
        with self.assertRaises(FileNotFoundError):self.read_bytes(ident)
        with self.case.archive.writer() as db:
            for n in range(1,6):db.execute('UPDATE report_visits SET agent=? WHERE id=?',(str(n),format(n,'064x')))
        ident=self.create({**self.spec,'group_by':['agent']})
        with patch('sanequeue.reporting.builder_exports.MAX_GROUPS',2):result=self.run_job()
        self.assertEqual(result['error'],'builder_group_limit')
        with self.assertRaises(FileNotFoundError):self.read_bytes(ident)

    def test_custom_cancel_and_number_revocation_between_pages_never_publish(self):
        self.case.seed(3)
        ident=self.create(modes={'8001':'full'});worker=self.case.worker(limits=Limits(page_size=1,min_free_bytes=0,max_load_per_cpu=0))
        page=worker._page
        def cancel(*args):
            rows=page(*args);self.case.store.cancel(ident,'alice');return rows
        worker._page=cancel
        self.assertEqual(worker.run_once()['state'],'cancelled');worker.reconciler.close()
        with self.assertRaises(FileNotFoundError):self.read_bytes(ident)
        ident=self.create({**self.spec,'group_by':['queue']});worker=self.case.worker(limits=Limits(page_size=1,min_free_bytes=0,max_load_per_cpu=0))
        page=worker._page;allowed=[True]
        def revoke(*args):
            rows=page(*args);allowed[0]=False;return rows
        worker._page=revoke;worker.authorize=lambda spec:allowed[0]
        self.assertEqual(worker.run_once()['error'],'export_access_revoked');worker.reconciler.close()
        with self.assertRaises(FileNotFoundError):self.read_bytes(ident)

    def test_request_capture_has_one_watermark_and_version_snapshot(self):
        self.case.seed()
        original=Archive.reader;archive=self.case.archive;changed=[]
        @contextmanager
        def reader(instance):
            with original(instance) as db:
                class Connection:
                    def execute(self,sql,args=()):
                        cursor=db.execute(sql,args)
                        if 'SELECT generation,ready FROM report_snapshot_meta' in sql and not changed:
                            changed.append(True)
                            with archive.writer() as write:
                                write.execute('UPDATE report_projection SET after_id=after_id+1')
                                write.execute('UPDATE report_visits SET talk_seconds=99')
                        return cursor
                yield Connection()
        with patch.object(Archive,'reader',reader):pinned=builder_exports.capture(archive)
        self.assertEqual(pinned['watermark'],0)
        ident=self.case.store.create('alice',fixtures.Scope(('8001',)),90,300,number_modes={'8001':'masked'},builder_definition=self.spec,**pinned)
        self.assertEqual(self.run_job()['state'],'completed')
        self.assertEqual(float(self.case.read(ident)[1][2]),19)

    def test_custom_byte_caps_and_unknown_aggregate_never_fabricate_zero(self):
        self.case.seed()
        with self.case.archive.writer() as db:db.execute('UPDATE report_visits SET talk_seconds=NULL,wait_seconds=NULL,answered=NULL')
        ident=self.create({**self.spec,'group_by':['queue']})
        self.assertEqual(self.run_job()['state'],'completed')
        rows=self.case.read(ident);values=dict(zip(rows[0],rows[1]))
        self.assertEqual(values['talk_known'],'0');self.assertEqual(values['queue_talk_seconds'],'');self.assertEqual(values['average_wait_seconds'],'')
        for format in ('csv','xlsx'):
            ident=self.create(format=format)
            result=self.run_job(limits=Limits(max_bytes=20,min_free_bytes=0,max_load_per_cpu=0))
            self.assertEqual(result['error'],'export_byte_limit')
            with self.assertRaises(FileNotFoundError):self.read_bytes(ident)


if __name__=='__main__':unittest.main()
