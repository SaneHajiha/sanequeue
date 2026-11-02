import unittest
from tests import test_reporting_queries as fixtures
from sanequeue.reporting.facts import project_batch
from sanequeue.reporting.queries import Scope,visits,detail


class QueuePositionTests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.ReportTests();self.case.setUp();self.addCleanup(self.case.doCleanups)

    def test_explicit_positions_conflicts_unknown_and_queue_isolation(self):
        c=self.case
        c.archive.append([c.event('a','8001','ENTERQUEUE',0,['','100','5']),
          c.event('a','8001','EXITWITHKEY',25,['9','2','5','25']),
          c.event('b','8001','ENTERQUEUE',30,['','200','4']),
          c.event('b','8001','ABANDON',40,['1','3','10']),
          c.event('c','8001','ENTERQUEUE',50,['','300','0']),
          c.event('c','8001','CONNECT',60,['10','peer','1']),
          c.event('c','8001','COMPLETEAGENT',70,['10','10','bad']),
          c.event('d','8002','ENTERQUEUE',80,['','400','9']),
          c.event('d','8002','EXITWITHTIMEOUT',90,['2','9','10'])])
        while project_batch(c.archive,limit=3)['processed']:pass
        rows=visits(c.archive,Scope(('8001',)),c.stamp,c.stamp+100)['rows'];by_caller={row['caller']:row for row in rows}
        self.assertEqual((by_caller['100']['entry_position'],by_caller['100']['exit_position']),(5,2))
        self.assertEqual(by_caller['100']['exit_position_evidence'],'exitwithkey')
        self.assertIsNone(by_caller['200']['entry_position']);self.assertEqual(by_caller['200']['entry_position_evidence'],'conflicting')
        self.assertIsNone(by_caller['300']['entry_position']);self.assertIsNone(by_caller['300']['exit_position'])
        self.assertEqual(by_caller['300']['exit_position_evidence'],'unavailable')
        self.assertIsNone(detail(c.archive,Scope(('8001',)),c.stamp,c.stamp+100,
                                 visits(c.archive,Scope(('8002',)),c.stamp,c.stamp+100)['rows'][0]['id']))
        self.assertEqual(detail(c.archive,Scope(('8001',)),c.stamp,c.stamp+100,by_caller['100']['id'])['visit']['entry_position'],5)

    def test_incremental_repair_rebuilds_existing_positions_in_bounded_steps(self):
        from sanequeue.reporting.repair_queue_positions import step,CHECKPOINT
        c=self.case
        c.archive.append([c.event('a','8001','ENTERQUEUE',0,['','100','5']),
                          c.event('a','8001','ABANDON',10,['2','5','10']),
                          c.event('b','8001','ENTERQUEUE',20,['','200','7']),
                          c.event('b','8001','EXITWITHKEY',30,['9','3','7','10'])])
        while project_batch(c.archive,limit=2)['processed']:pass
        with c.archive.writer() as db:db.execute('DELETE FROM report_visit_positions')
        self.assertTrue(all(r['entry_position'] is None for r in visits(c.archive,Scope(('8001',)),c.stamp,c.stamp+100)['rows']))
        for _ in range(10):
            result=step(c.archive,scan_limit=2,max_calls=1)
            self.assertLessEqual(result['rebuilt_calls'],1)
            if result['completed']:break
        self.assertTrue(result['completed']);self.assertTrue(c.archive.checkpoint(CHECKPOINT)['completed'])
        rows=visits(c.archive,Scope(('8001',)),c.stamp,c.stamp+100)['rows']
        self.assertEqual({(r['entry_position'],r['exit_position']) for r in rows},{(5,2),(7,3)})
        self.assertEqual(step(c.archive)['rebuilt_calls'],0)

    def test_snapshot_csv_and_xlsx_preserve_positions_as_of_request(self):
        import csv,io,os
        from zipfile import ZipFile
        from xml.etree import ElementTree as ET
        from sanequeue.reporting import visit_snapshots
        from sanequeue.reporting.export_jobs import JobStore,ExportWorker,Limits,projection_watermark
        c=self.case;c.archive.append([c.event('a','8001','ENTERQUEUE',0,['','100','5']),
            c.event('a','8001','EXITWITHKEY',25,['9','2','5','25'])])
        while project_batch(c.archive,limit=2)['processed']:pass
        old=visit_snapshots.capture(c.archive)
        store=JobStore(c.root/'jobs.db',c.root/'private');store.initialize()
        ident=store.create('test',Scope(('8001',)),c.stamp,c.stamp+100,watermark=projection_watermark(c.archive),
                           number_modes={'8001':'masked'},snapshot=old,format='csv',language='en',outcome_class='unanswered')
        xlsx_id=store.create('test',Scope(('8001',)),c.stamp,c.stamp+100,watermark=projection_watermark(c.archive),
                            number_modes={'8001':'masked'},snapshot=old,format='xlsx',language='en',outcome_class='unanswered')
        with c.archive.writer() as db:db.execute('UPDATE report_visit_positions SET entry_position=9,exit_position=1')
        new=visit_snapshots.capture(c.archive)
        self.assertGreater(new['sequence'],old['sequence'])
        with c.archive.reader() as db:
            old_rows=visit_snapshots.page(db,c.archive.pbx,old,Scope(('8001',)),c.stamp,c.stamp+100)
            new_rows=visit_snapshots.page(db,c.archive.pbx,new,Scope(('8001',)),c.stamp,c.stamp+100)
        self.assertEqual((old_rows[0]['entry_position'],old_rows[0]['exit_position']),(5,2))
        self.assertEqual((new_rows[0]['entry_position'],new_rows[0]['exit_position']),(9,1))
        worker=ExportWorker(store,c.archive,limits=Limits(min_free_bytes=0,max_load_per_cpu=0),authorize=lambda spec:True,disabled_file=c.root/'disabled')
        result=worker.run_once();self.assertEqual(result['state'],'completed',result)
        fd,_=store.open_output(ident,'test')
        with os.fdopen(fd,'rb') as stream:rows=list(csv.DictReader(io.StringIO(stream.read().decode('utf-8-sig'))))
        self.assertEqual((rows[0]['Entry position'],rows[0]['Exit position']),('5','2'))
        result=worker.run_once();self.assertEqual(result['state'],'completed',result)
        fd,_=store.open_output(xlsx_id,'test')
        with os.fdopen(fd,'rb') as stream, ZipFile(io.BytesIO(stream.read())) as book:
            sheet=ET.fromstring(book.read('xl/worksheets/sheet1.xml'))
        ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        cells={cell.get('r'):cell for cell in sheet.findall('.//s:c',ns)}
        self.assertEqual(cells['M4'].find('.//s:t',ns).text,'Entry position')
        self.assertEqual(cells['N4'].find('.//s:t',ns).text,'Exit position')
        self.assertEqual(cells['M5'].find('s:v',ns).text,'5')
        self.assertEqual(cells['N5'].find('s:v',ns).text,'2')
        self.assertEqual(sheet.find('s:autoFilter',ns).get('ref'),'A4:N5')

    def test_snapshot_reader_handles_archive_before_position_version_migration(self):
        from sanequeue.reporting import visit_snapshots
        c=self.case;c.archive.append([c.event('a','8001','ENTERQUEUE',0,['','100','5'])])
        while project_batch(c.archive,limit=2)['processed']:pass
        token=visit_snapshots.capture(c.archive)
        with c.archive.writer() as db:db.execute('DROP TABLE report_position_versions')
        with c.archive.reader() as db:rows=visit_snapshots.page(db,c.archive.pbx,token,Scope(('8001',)),c.stamp,c.stamp+100)
        self.assertIsNone(rows[0]['entry_position']);self.assertIsNone(rows[0]['exit_position'])

    def test_bootstrap_versions_existing_positions_without_overwriting_snapshot(self):
        from sanequeue.reporting import visit_snapshots
        from sanequeue.reporting.snapshot_schema import bootstrap_positions
        c=self.case;c.archive.append([c.event('a','8001','ENTERQUEUE',0,['','100','5'])])
        while project_batch(c.archive,limit=2)['processed']:pass
        with c.archive.writer() as db:
            db.execute('DELETE FROM report_position_versions')
            db.execute('DELETE FROM report_position_snapshot_meta')
        old=visit_snapshots.capture(c.archive)
        with c.archive.writer() as db:bootstrap_positions(db,c.archive.pbx,limit=1)
        new=visit_snapshots.capture(c.archive)
        with c.archive.reader() as db:
            before=visit_snapshots.page(db,c.archive.pbx,old,Scope(('8001',)),c.stamp,c.stamp+100)
            after=visit_snapshots.page(db,c.archive.pbx,new,Scope(('8001',)),c.stamp,c.stamp+100)
        self.assertIsNone(before[0]['entry_position']);self.assertEqual(after[0]['entry_position'],5)

    def test_reentry_does_not_mix_positions_and_rebuild_removes_old(self):
        c=self.case
        c.archive.append([c.event('a','8001','ENTERQUEUE',0,['','100','5']),
          c.event('a','8001','ABANDON',10,['2','5','10']),
          c.event('a','8001','ENTERQUEUE',20,['','100','7']),
          c.event('a','8001','ABANDON',30,['3','7','10'])])
        while project_batch(c.archive,limit=2)['processed']:pass
        rows=visits(c.archive,Scope(('8001',)),c.stamp,c.stamp+100)['rows']
        self.assertEqual({(r['entry_position'],r['exit_position']) for r in rows},{(5,2),(7,3)})
        self.assertEqual(project_batch(c.archive)['processed'],0)

if __name__=='__main__':unittest.main()
