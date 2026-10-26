"""Private PDF: actual font/shaping, bounded pages and worker fences."""
import io
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from sanequeue.reporting import pdf_stream
from sanequeue.reporting.exports import table
from sanequeue.reporting.export_jobs import Limits
from sanequeue.reporting.visit_snapshots import capture
from tests import test_reporting_export_jobs as export_fixtures


def rows(count=1):
    return [dict(id=format(i+1,'064x'),queue='8001',caller='0912***6789',agent='کارشناس پشتیبانی',
        outcome='answered',entered=1792886400+i,answered=1792886410+i,ended=1792886430+i,
        wait_seconds=10,talk_seconds=20,segment_ended_by='caller',coverage='observed') for i in range(count)]


class PdfDocumentTests(unittest.TestCase):
    def document(self,language='en',**options):
        self.output=io.BytesIO()
        return pdf_stream.Document(self.output,language,start=1792886400,end=1792972800,queues=['8001'],**options)

    def test_actual_fa_en_document_embeds_font_and_preserves_shaped_rtl_and_latin(self):
        for language in ('fa','en'):
            with self.subTest(language=language):
                document=self.document(language)
                visual=document.visual('سلام دنیا')
                self.assertNotEqual(visual,'سلام دنیا')
                self.assertTrue(any('\ufe70'<=ch<='\ufeff' for ch in visual))
                self.assertEqual(document.visual('PJSIP/100'),'PJSIP/100')
                document.append(table(rows(),language)[1])
                commands=document.pdf.getCurrentPageContent()
                self.assertIn('0912***6789',commands);self.assertNotIn('09123456789',commands)
                document.close();data=self.output.getvalue()
                self.assertTrue(data.startswith(b'%PDF-'));self.assertTrue(data.rstrip().endswith(b'%%EOF'))
                self.assertIn(b'/FontFile2',data);self.assertIn(b'/ToUnicode',data)
                self.assertEqual(document.rows,1)

    def test_pagination_repeats_header_without_truncating_rows(self):
        document=self.document();headers=[];original=document._new_page
        def page():
            original();headers.append(document.pdf.getCurrentPageContent())
        document._new_page=page
        document.append(table(rows(42),'en')[1]);document.close()
        self.assertEqual(document.rows,42);self.assertGreater(document.pages,1)
        self.assertEqual(len(headers),document.pages-1)
        self.assertTrue(all('Queue visit report' in page for page in headers))
        self.assertEqual(len(re.findall(rb'/Type\s*/Page\b',self.output.getvalue())),document.pages)

    def test_empty_report_is_valid_and_unknown_timestamps_stay_blank(self):
        document=self.document();document.close()
        self.assertEqual(document.pages,1);self.assertEqual(document.rows,0)
        self.assertTrue(self.output.getvalue().startswith(b'%PDF-'))
        unknown=rows()[0];unknown.update(answered=None,ended=None,talk_seconds=None)
        document=self.document();document.append(table([unknown],'en')[1])
        self.assertIn('Answered:  | Segment ended:  | Visit ID:',document.pdf.getCurrentPageContent())
        document.close()

    def test_rows_pages_bytes_and_long_fields_fail_instead_of_silent_truncation(self):
        document=self.document(max_rows=1)
        with self.assertRaisesRegex(pdf_stream.PdfFailure,'^pdf_row_limit$'):document.append(table(rows(2),'en')[1])
        document.abort()
        document=self.document(max_pages=1)
        with self.assertRaisesRegex(pdf_stream.PdfFailure,'^pdf_page_limit$'):document.append(table(rows(42),'en')[1])
        document.abort()
        document=self.document(max_bytes=100)
        with self.assertRaisesRegex(pdf_stream.PdfFailure,'^pdf_byte_limit$'):document.close()
        document.abort()
        document=self.document();body=table(rows(),'en')[1];body[0][2]='X'*512
        with self.assertRaisesRegex(pdf_stream.PdfFailure,'^pdf_field_limit$'):document.append(body)
        document.abort()

    def test_callback_fences_pages_and_serialization_and_no_html_actions(self):
        calls=[];document=self.document(check=lambda:calls.append(1))
        values=rows(21);values[0]['agent']='https://example.invalid/<script>'
        document.append(table(values,'en')[1]);document.close()
        self.assertGreaterEqual(len(calls),document.pages+2)
        data=self.output.getvalue()
        for action in (b'/URI',b'/JavaScript',b'/OpenAction'):self.assertNotIn(action,data)
        with patch('sanequeue.reporting.pdf_stream._dependencies',side_effect=pdf_stream.PdfFailure('pdf_dependency_unavailable')):
            with self.assertRaisesRegex(pdf_stream.PdfFailure,'^pdf_dependency_unavailable$'):self.document()


class PdfWorkerTests(unittest.TestCase):
    setUp=export_fixtures.ExportJobTests.setUp
    seed=export_fixtures.ExportJobTests.seed
    create=export_fixtures.ExportJobTests.create
    worker=export_fixtures.ExportJobTests.worker

    def test_private_pdf_snapshot_masking_checksum_and_completed_cancel(self):
        self.seed();token=capture(self.archive)
        ident=self.create(format='pdf',snapshot=token)
        with self.archive.writer() as db:db.execute("UPDATE report_visits SET caller='09999999999'")
        seen=[];original=pdf_stream.Document.close
        def close(document):
            seen.append(document.pdf.getCurrentPageContent());return original(document)
        with patch.object(pdf_stream.Document,'close',close):result=self.worker().run_once()
        self.assertEqual(result['state'],'completed',result)
        self.assertIn('0912***6789',''.join(seen));self.assertNotIn('0999***9999',''.join(seen))
        job=self.store.get(ident,'alice');self.assertEqual(job['rows'],1);self.assertEqual(len(job['checksum']),64)
        self.assertFalse(self.store.cancel(ident,'alice'))
        with (self.store.output_dir/(ident+'.pdf')).open('rb') as stream:self.assertEqual(stream.read(5),b'%PDF-')
        with self.assertRaises(FileNotFoundError):self.store.open_output(ident,'bob')

    def test_pdf_cancel_during_source_batch_is_fenced_on_new_pdf_page(self):
        self.seed(35);ident=self.create(format='pdf');original=pdf_stream.Document._new_page
        def cancel(document):
            if document.pages:self.store.cancel(ident,'alice')
            return original(document)
        with patch.object(pdf_stream.Document,'_new_page',cancel):result=self.worker().run_once()
        self.assertEqual(result['state'],'cancelled',result)
        self.assertFalse((self.store.output_dir/(ident+'.pdf')).exists())
        self.assertFalse(list(self.store.output_dir.glob('*.part')))

    def test_pdf_permission_revoked_on_page_boundary_prevents_publication(self):
        self.seed(35);ident=self.create(format='pdf');granted=[True];original=pdf_stream.Document._new_page
        def revoke(document):
            if document.pages:granted[0]=False
            return original(document)
        with patch.object(pdf_stream.Document,'_new_page',revoke):result=self.worker(authorize=lambda spec:granted[0]).run_once()
        self.assertEqual(result['error'],'export_access_revoked',result)
        self.assertFalse((self.store.output_dir/(ident+'.pdf')).exists())

    def test_pdf_limits_and_dependency_failure_leave_no_downloadable_partial(self):
        self.seed(3);ident=self.create(format='pdf')
        with patch('sanequeue.reporting.pdf_stream.MAX_ROWS',2):result=self.worker().run_once()
        self.assertEqual(result['error'],'pdf_row_limit',result)
        self.assertFalse((self.store.output_dir/(ident+'.pdf')).exists())
        ident=self.create(format='pdf')
        with patch('sanequeue.reporting.pdf_stream._dependencies',side_effect=pdf_stream.PdfFailure('pdf_dependency_unavailable')):
            result=self.worker().run_once()
        self.assertEqual(result['error'],'pdf_dependency_unavailable',result)
        self.assertFalse(list(self.store.output_dir.glob('*.part')))

    def test_pdf_authenticated_publish_crash_recovers_same_complete_file(self):
        self.seed();ident=self.create(format='pdf');link=os.link
        def crash(source,destination):
            link(source,destination);raise SystemExit('simulated process death')
        with patch('sanequeue.reporting.export_jobs.os.link',side_effect=crash):
            with self.assertRaises(SystemExit):self.worker().run_once()
        final=self.store.output_dir/(ident+'.pdf');before=final.read_bytes()
        with self.assertRaises(FileNotFoundError):self.store.open_output(ident,'alice')
        with self.store._db(write=True) as db:db.execute('UPDATE export_jobs SET lease_until=0 WHERE id=?',(ident,))
        result=self.worker().run_once()
        self.assertTrue(result['recovered']);self.assertEqual(result['state'],'completed')
        self.assertEqual(final.read_bytes(),before)


class PdfAPITests(unittest.TestCase):
    def test_create_background_pdf_download_mime_and_current_permission(self):
        from tests import test_reporting_queries as fixtures
        from sanequeue.reporting.export_jobs import JobStore,ExportWorker
        case=fixtures.ReportTests();case.setUp();self.addCleanup(case.doCleanups);case.seed()
        store=JobStore(case.root/'export-jobs.sqlite3',case.root/'private-exports');store.initialize()
        client=case.client(role='admin',menus=('reports',),details=True)
        with client.session_transaction() as session:session['csrf_token']='test'
        response=client.post('/api/history/export-jobs'+case.dates+'&format=pdf&lang=fa',headers={'X-CSRF-Token':'test'})
        self.assertEqual(response.status_code,202,response.json);ident=response.json['id']
        self.assertEqual(client.get('/api/history/export-jobs/'+ident+'/download').status_code,404)
        worker=ExportWorker(store,case.archive,limits=Limits(min_free_bytes=0,max_load_per_cpu=0),authorize=lambda spec:True)
        self.assertEqual(worker.run_once()['state'],'completed')
        result=client.get('/api/history/export-jobs/'+ident+'/download')
        self.assertEqual(result.status_code,200);self.assertEqual(result.mimetype,'application/pdf')
        self.assertTrue(result.data.startswith(b'%PDF-'));self.assertIn('.pdf',result.headers['Content-Disposition'])
        plan=client.post('/api/history/plans'+case.dates,headers={'X-CSRF-Token':'test'},json=dict(
            name='Persian PDF schedule',queues=['8001'],format='pdf',language='fa',period='yesterday',enabled=False))
        self.assertEqual(plan.status_code,201,plan.json);self.assertEqual(plan.json['plan']['format'],'pdf')
        restricted=case.client(role='admin',menus=('reports',),details=True,denied=('report_export',))
        self.assertEqual(restricted.get('/api/history/export-jobs/'+ident+'/download').status_code,403)


if __name__=='__main__':unittest.main()
