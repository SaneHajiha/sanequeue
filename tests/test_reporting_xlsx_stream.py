"""Workbook validity, inline text safety and bounded worker pages."""
import hashlib
import io
import os
import unittest
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from sanequeue.reporting.xlsx_stream import Workbook, SizeLimit
from sanequeue.reporting.visit_snapshots import capture
from tests import test_reporting_export_jobs as fixtures


class StreamingXlsxTests(unittest.TestCase):
    def test_xml_valid_text_is_never_formula_and_limits_enforced(self):
        output=io.BytesIO();book=Workbook(output,'fa',period='test')
        book.append([['09123456789','=HYPERLINK("x")','<danger>&\x00',None,12.5]])
        book.close()
        with ZipFile(io.BytesIO(output.getvalue())) as archive:
            sheet=ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
            ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            self.assertEqual(sheet.find('s:sheetViews/s:sheetView',ns).attrib['rightToLeft'],'1')
            self.assertEqual(len(sheet.findall('s:sheetData/s:row',ns)),5)
            self.assertEqual(sheet.find('s:autoFilter',ns).attrib['ref'],'A4:L5')
            self.assertEqual(sheet.findall('.//s:f',ns),[])
            text=[node.text for node in sheet.findall('.//s:t',ns)]
            self.assertIn('09123456789',text);self.assertIn('=HYPERLINK("x")',text)
            self.assertIn('<danger>&',text)
        with self.assertRaises(SizeLimit):Workbook(io.BytesIO(),'en',max_bytes=100)
        with self.assertRaises(SizeLimit):Workbook(io.BytesIO(),'en',max_xml_bytes=10)
        book=Workbook(io.BytesIO(),'en',max_xml_bytes=3000)
        try:
            with self.assertRaises(SizeLimit):book.append([['x'*32767]])
        finally:book.abort()

    def test_worker_snapshot_xlsx_has_all_rows_and_hash_after_zip_finalization(self):
        case=fixtures.ExportJobTests();case.setUp();self.addCleanup(case.doCleanups)
        case.seed(405)
        ident=case.create(format='xlsx',language='fa',snapshot=capture(case.archive))
        worker=case.worker();sizes=[];original=worker._page
        def page(*args):
            rows=original(*args);sizes.append(len(rows));return rows
        worker._page=page
        result=worker.run_once()
        self.assertEqual(result['state'],'completed',result)
        self.assertEqual(sizes,[200,200,5,0])
        fd,_=case.store.open_output(ident,'alice')
        with os.fdopen(fd,'rb') as stream:content=stream.read()
        self.assertEqual(hashlib.sha256(content).hexdigest(),case.store.get(ident,'alice')['checksum'])
        with ZipFile(io.BytesIO(content)) as archive:
            self.assertIsNone(archive.testzip())
            sheet=ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
            self.assertEqual(len(sheet.findall('{*}sheetData/{*}row')),409)
        self.assertFalse(list(case.store.output_dir.glob('*.part')))

    def test_worker_does_not_publish_partial_xlsx_at_row_limit(self):
        from sanequeue.reporting.export_jobs import Limits
        case=fixtures.ExportJobTests();case.setUp();self.addCleanup(case.doCleanups);case.seed(3)
        ident=case.create(format='xlsx')
        result=case.worker(limits=Limits(max_rows=2,min_free_bytes=0,max_load_per_cpu=0)).run_once()
        self.assertEqual(result['error'],'export_row_limit')
        self.assertFalse((case.store.output_dir/(ident+'.xlsx')).exists())
        self.assertFalse(list(case.store.output_dir.glob('*.part')))


if __name__=='__main__':unittest.main()
