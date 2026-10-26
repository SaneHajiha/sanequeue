"""Immutable exports while callers, late evidence and ingestion keep changing."""
import csv
import io
import os
from pathlib import Path
import tempfile
import unittest

from tests import test_reporting_queries as fixtures
from sanequeue.reporting.store import Archive
from sanequeue.reporting.facts import project_batch, SCHEMA
from sanequeue.reporting.queries import Scope
from sanequeue.reporting import visit_snapshots
from sanequeue.reporting.export_jobs import JobStore, ExportWorker, Limits, projection_watermark


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ReportTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.archive=self.fixture.archive

    def page(self,token,**extra):
        with self.archive.reader() as db:
            return visit_snapshots.page(db,self.archive.pbx,token,Scope(('8001',)),0,1000,**extra)

    def seed(self,count=1):
        project_batch(self.archive)
        with self.archive.writer() as db:
            db.executemany('INSERT INTO report_visits VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                [('primary',format(i+1,'064x'),'call-'+str(i),'8001',100+i/1000,101,120,
                  '09123456789','PJSIP/100','answered',1,19,'caller','observed') for i in range(count)])

    def test_pinned_versions_survive_updates_deletes_and_new_arrivals(self):
        self.seed(3);token=visit_snapshots.capture(self.archive)
        with self.archive.writer() as db:
            db.execute("UPDATE report_visits SET caller='09999999999',talk_seconds=99 WHERE id=?",(format(1,'064x'),))
            db.execute('DELETE FROM report_visits WHERE id=?',(format(2,'064x'),))
            db.execute("UPDATE report_visits SET queue='8002',entered=200 WHERE id=?",(format(3,'064x'),))
        rows=self.page(token)
        self.assertEqual(len(rows),3)
        self.assertEqual({row['caller'] for row in rows},{'09123456789'})
        self.assertEqual({row['talk_seconds'] for row in rows},{19})
        current=self.page(visit_snapshots.capture(self.archive))
        self.assertEqual(len(current),1)
        self.assertEqual(current[0]['caller'],'09999999999')

    def test_export_finishes_during_live_ingestion_and_retains_original_values(self):
        self.seed(405);token=visit_snapshots.capture(self.archive)
        store=JobStore(self.fixture.root/'jobs.db',self.fixture.root/'exports');store.initialize()
        ident=store.create('alice',Scope(('8001',)),90,300,watermark=projection_watermark(self.archive),
                           snapshot=token,number_modes={'8001':'full'})
        worker=ExportWorker(store,self.archive,limits=Limits(min_free_bytes=0,max_load_per_cpu=0))
        original=worker._page;pages=[]
        def changing_page(*args):
            rows=original(*args);pages.append(len(rows))
            with self.archive.writer() as db:
                # Change already-read and not-yet-read rows; advance projection.
                db.execute("UPDATE report_visits SET caller='09999999999',talk_seconds=88")
                db.execute('UPDATE report_projection SET after_id=after_id+1')
            return rows
        worker._page=changing_page
        result=worker.run_once()
        self.assertEqual(result['state'],'completed')
        self.assertEqual(pages,[200,200,5,0])
        fd,_=store.open_output(ident,'alice')
        with os.fdopen(fd,'rb') as stream:
            rows=list(csv.reader(io.StringIO(stream.read().decode('utf-8-sig'))))
        self.assertEqual(len(rows),406)
        self.assertEqual({row[1] for row in rows[1:]},{'09123456789'})
        self.assertEqual({row[8] for row in rows[1:]},{'19.0'})

    def test_bounded_migration_and_new_writes_during_bootstrap(self):
        # Simulate an existing deployment with derived facts but no history.
        with self.archive.writer() as db:
            db.executescript(SCHEMA)
            db.executemany('INSERT INTO report_visits VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                [('primary',format(i,'064x'),'old-'+str(i),'8001',100,None,None,'200','','waiting',
                  None,None,None,'missing_end') for i in range(1,6)])
        project_batch(self.archive,limit=2)
        with self.assertRaises(visit_snapshots.SnapshotUnavailable):visit_snapshots.capture(self.archive)
        with self.archive.writer() as db:
            db.execute("UPDATE report_visits SET outcome='abandoned',ended=130,wait_seconds=30 WHERE id=?",(format(1,'064x'),))
        project_batch(self.archive,limit=2);project_batch(self.archive,limit=2)
        token=visit_snapshots.capture(self.archive)
        rows=self.page(token)
        self.assertEqual(len(rows),5)
        self.assertEqual(next(row for row in rows if row['id']==format(1,'064x'))['outcome'],'abandoned')

    def test_late_entry_replaces_orphan_without_changing_an_old_snapshot(self):
        case=self.fixture
        case.archive.append([case.event('late','8001','COMPLETEAGENT',40,['10','30'])])
        project_batch(case.archive);token=visit_snapshots.capture(case.archive)
        with case.archive.reader() as db:
            before=visit_snapshots.page(db,'primary',token,Scope(('8001',)),case.stamp,case.stamp+100)
        case.archive.append([case.event('late','8001','ENTERQUEUE',0,['','200']),
                             case.event('late','8001','CONNECT',10,['10'])])
        project_batch(case.archive)
        with case.archive.reader() as db:
            old=visit_snapshots.page(db,'primary',token,Scope(('8001',)),case.stamp,case.stamp+100)
            new=visit_snapshots.page(db,'primary',visit_snapshots.capture(case.archive),Scope(('8001',)),case.stamp,case.stamp+100)
        self.assertEqual(old,before)
        self.assertEqual(new[0]['coverage'],'observed')
        self.assertNotEqual(new[0]['id'],old[0]['id'])

    def test_generation_scope_and_unchanged_projection(self):
        self.seed();token=visit_snapshots.capture(self.archive)
        project_batch(self.archive)
        self.assertEqual(token,visit_snapshots.capture(self.archive))
        with self.archive.reader() as db:
            self.assertEqual(visit_snapshots.page(db,'primary',token,Scope(()),0,1000),[])
            self.assertEqual(visit_snapshots.page(db,'primary',token,Scope(('8001',),(),True),0,1000),[])
        with self.archive.writer() as db:
            db.execute("UPDATE report_snapshot_meta SET generation=lower(hex(randomblob(16)))")
        with self.assertRaises(visit_snapshots.SnapshotUnavailable):self.page(token)


if __name__=='__main__':unittest.main()
