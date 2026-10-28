"""Private artifact recovery, including actual process death rather than finally."""
import json
import errno
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from tests import test_reporting_export_jobs as fixtures
from sanequeue.reporting.export_maintenance import ArtifactReconciler,owner_artifacts


class ArtifactRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.ExportJobTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.store=self.case.store
        self.reconciler=ArtifactReconciler(self.store,grace_seconds=0)
        self.addCleanup(self.reconciler.close)

    def artifact(self,*,state='cancelled',format='csv',part=False,owner='alice',token='a'*32):
        ident=self.case.create(owner=owner,format=format)
        with self.store._db(write=True) as db:
            db.execute('UPDATE export_jobs SET state=?,updated=0,worker=?,bytes=7 WHERE id=?',(state,'b'*32,ident))
        path=self.store.output_dir/(ident+'.'+token+'.part' if part else ident+'.'+format)
        path.write_bytes(b'private');path.chmod(0o600);os.utime(path,(0,0))
        return ident,path

    def drain(self,**kwargs):
        outputs=[];kwargs.setdefault('now',1000)
        for _ in range(100):
            result=self.reconciler.run_once(max_seconds=1,**kwargs);outputs.append(result)
            if result['scan_complete']:break
        else:self.fail('bounded directory traversal did not finish')
        return outputs

    def test_terminal_formats_are_preserved_in_private_non_downloadable_quarantine(self):
        jobs=[]
        for format in ('csv','xlsx','pdf'):
            ident,path=self.artifact(format=format);jobs.append(ident)
        results=self.drain()
        self.assertEqual(sum(r['quarantined'] for r in results),3)
        rows=owner_artifacts(self.store,'alice');self.assertEqual(len(rows),3)
        self.assertTrue(all(row['state']=='quarantined' for row in rows))
        self.assertTrue(all('source' not in row and 'target' not in row and 'owner' not in row for row in rows))
        self.assertEqual(owner_artifacts(self.store,'bob'),[])
        self.assertEqual([p.read_bytes() for p in self.reconciler.directory.iterdir()],[b'private']*3)
        if os.name!='nt':self.assertEqual(self.reconciler.directory.stat().st_mode&0o077,0)
        for ident in jobs:
            with self.assertRaises(FileNotFoundError):self.store.open_output(ident,'alice')

    def test_completed_pending_and_unknown_files_are_not_retired(self):
        paths=[]
        for state in ('completed','queued','running'):
            _,path=self.artifact(state=state);paths.append(path)
        unknown=self.store.output_dir/('c'*32+'.csv');unknown.write_bytes(b'not-owned-by-a-job');paths.append(unknown)
        self.drain();self.assertTrue(all(p.is_file() for p in paths))
        self.assertEqual(owner_artifacts(self.store,'alice'),[])
        self.assertFalse(self.reconciler.directory.exists())

    def test_live_attempt_part_is_protected_but_superseded_part_can_be_retired(self):
        ident,current=self.artifact(state='running',part=True,token='b'*32)
        previous=self.store.output_dir/(ident+'.'+'a'*32+'.part');previous.write_bytes(b'older');os.utime(previous,(0,0))
        self.drain(active=(ident,'b'*32))
        self.assertTrue(current.is_file());self.assertFalse(previous.exists())
        self.assertEqual(owner_artifacts(self.store,'alice')[0]['reason'],'superseded_attempt')

    def test_completed_redundant_hardlink_keeps_download_unchanged(self):
        ident,final=self.artifact(state='completed')
        part=self.store.output_dir/(ident+'.'+'a'*32+'.part');os.link(final,part)
        self.drain();self.assertFalse(part.exists());self.assertEqual(final.read_bytes(),b'private')
        fd,size=self.store.open_output(ident,'alice')
        with os.fdopen(fd,'rb') as stream:self.assertEqual(stream.read(),b'private')
        self.assertEqual(size,7)

    def test_completed_partial_attempt_is_preserved_without_moving_final(self):
        ident,final=self.artifact(state='completed')
        part=self.store.output_dir/(ident+'.'+'a'*32+'.part');part.write_bytes(b'partial');os.utime(part,(0,0))
        self.drain();self.assertFalse(part.exists());self.assertEqual(final.read_bytes(),b'private')
        self.assertEqual(owner_artifacts(self.store,'alice')[0]['reason'],'completed_attempt_staging')

    def test_directory_iterator_makes_progress_past_preserved_files(self):
        retained=[]
        for _ in range(25):retained.append(self.artifact(state='completed')[1])
        _,target=self.artifact()
        results=self.drain(max_entries=3)
        self.assertTrue(all(result['examined']<=3 for result in results))
        self.assertGreater(len(results),8);self.assertFalse(target.exists())
        self.assertTrue(all(path.is_file() for path in retained))

    def test_grace_period_protects_fresh_terminal_file_and_job(self):
        _,path=self.artifact();self.reconciler.grace=300
        os.utime(path,(950,950));self.drain();self.assertTrue(path.is_file())
        os.utime(path,(0,0));self.drain();self.assertFalse(path.exists())

    def intent(self):
        ident,path=self.artifact();meta=path.stat();job=self.reconciler._job(ident)
        return path,self.reconciler._intent(path.name,meta,job,'terminal_unpublished',1000)

    def test_durable_intent_recovers_death_before_link(self):
        source,row=self.intent();self.drain();self.assertFalse(source.exists())
        self.assertEqual((self.reconciler.directory/row['target']).read_bytes(),b'private')
        self.drain();self.assertEqual(len(list(self.reconciler.directory.iterdir())),1)

    def test_link_filesystem_failures_preserve_source_and_retry_durable_intent(self):
        # A mounted quarantine or full filesystem must never trigger copy/delete.
        for failure in (errno.EXDEV,errno.ENOSPC):
            with self.subTest(errno=failure):
                source,row=self.intent()
                with patch('sanequeue.reporting.export_maintenance.os.link',side_effect=OSError(failure,'injected link failure')):
                    result=self.reconciler.run_once(now=1000,max_seconds=1)
                self.assertEqual(result['state'],'unavailable')
                self.assertEqual(source.read_bytes(),b'private')
                self.assertFalse((self.reconciler.directory/row['target']).exists())
                entry=next(item for item in owner_artifacts(self.store,'alice') if item['id']==row['id'])
                self.assertEqual(entry['state'],'pending')
                self.drain()
                self.assertFalse(source.exists())
                self.assertEqual((self.reconciler.directory/row['target']).read_bytes(),b'private')
                entry=next(item for item in owner_artifacts(self.store,'alice') if item['id']==row['id'])
                self.assertEqual(entry['state'],'quarantined')

    def test_target_collision_never_overwrites_or_removes_source(self):
        source,row=self.intent();self.reconciler._directories(create=True)
        target=self.reconciler.directory/row['target'];target.write_bytes(b'foreign')
        self.drain();self.assertEqual(target.read_bytes(),b'foreign');self.assertTrue(source.exists())
        self.assertEqual(owner_artifacts(self.store,'alice')[0]['state'],'conflict')

    def test_source_replacement_before_unlink_is_preserved(self):
        source,row=self.intent();original=self.reconciler._allowed_now;calls=[]
        def changed(*args):
            calls.append(1)
            if len(calls)==2:
                source.unlink();source.write_bytes(b'replacement')
            return original(*args)
        with patch.object(self.reconciler,'_allowed_now',side_effect=changed):self.drain()
        self.assertEqual(source.read_bytes(),b'replacement')
        self.assertEqual((self.reconciler.directory/row['target']).read_bytes(),b'private')
        self.assertEqual(owner_artifacts(self.store,'alice')[0]['state'],'source_changed')

    @unittest.skipIf(os.name=='nt','Unix special-file and symlink coverage runs in Linux CI')
    def test_symlink_fifo_directory_and_quarantine_symlink_are_not_followed(self):
        ident,path=self.artifact();path.unlink();outside=self.case.root/'outside';outside.write_bytes(b'outside')
        path.symlink_to(outside);self.drain();self.assertEqual(outside.read_bytes(),b'outside');self.assertTrue(path.is_symlink())
        path.unlink();os.mkfifo(path);self.drain();self.assertTrue(path.exists())
        path.unlink();path.mkdir();self.drain();self.assertTrue(path.is_dir())
        self.reconciler.directory.symlink_to(self.case.root,target_is_directory=True)
        self.assertEqual(self.reconciler.run_once()['state'],'unavailable')

    def test_process_death_after_link_and_after_unlink_is_recoverable(self):
        # os._exit bypasses finally/atexit. These are genuine durable windows.
        for after_unlink in (False,True):
            with self.subTest(after_unlink=after_unlink):
                source,row=self.intent();self.reconciler._directories(create=True)
                target=self.reconciler.directory/row['target']
                code='import os,sys;os.link(sys.argv[1],sys.argv[2]);'+('os.unlink(sys.argv[1]);' if after_unlink else '')+'os._exit(23)'
                process=subprocess.run([sys.executable,'-c',code,str(source),str(target)],timeout=15,capture_output=True)
                self.assertEqual(process.returncode,23)
                self.assertTrue(target.exists());self.assertEqual(source.exists(),not after_unlink)
                self.drain();self.assertFalse(source.exists());self.assertEqual(target.read_bytes(),b'private')
                self.assertEqual(next(item for item in owner_artifacts(self.store,'alice') if item['id']==row['id'])['state'],'quarantined')

    def test_worker_os_exit_publication_then_cancel_or_retry_exhaustion(self):
        self.case.seed()
        code="""import os,sys
from sanequeue.reporting.export_jobs import JobStore,ExportWorker,Limits
from sanequeue.reporting.store import Archive
store=JobStore(sys.argv[1],sys.argv[2]);worker=ExportWorker(store,Archive(sys.argv[3]),limits=Limits(min_free_bytes=0,max_load_per_cpu=0),authorize=lambda spec:True)
link=os.link
def publish_then_die(source,target,*args,**kwargs):
 link(source,target,*args,**kwargs)
 if str(target).endswith('.csv'):os._exit(24)
os.link=publish_then_die
worker.run_once()
"""
        for exhaust in (False,True):
            with self.subTest(exhaust=exhaust):
                ident=self.case.create()
                process=subprocess.run([sys.executable,'-c',code,str(self.store.path),str(self.store.output_dir),str(self.case.archive.path)],capture_output=True,timeout=30)
                self.assertEqual(process.returncode,24,process.stderr.decode(errors='replace')[-500:])
                final=self.store.output_dir/(ident+'.csv');parts=list(self.store.output_dir.glob(ident+'.*.part'))
                self.assertTrue(final.is_file());self.assertEqual(len(parts),1)
                original=final.read_bytes()
                if exhaust:
                    with self.store._db(write=True) as db:db.execute('UPDATE export_jobs SET attempts=3,lease_until=0 WHERE id=?',(ident,))
                    self.assertIsNone(self.store.claim('next-worker'))
                    self.assertEqual(self.store.get(ident,'alice')['state'],'failed')
                else:self.assertTrue(self.store.cancel(ident,'alice'))
                self.drain(now=time.time()+1)
                self.assertFalse(final.exists());self.assertFalse(parts[0].exists())
                artifacts=[item for item in owner_artifacts(self.store,'alice') if item['job_id']==ident]
                self.assertEqual(len(artifacts),2)
                with self.store._db() as db:
                    targets=[row[0] for row in db.execute('SELECT target FROM export_artifacts WHERE job_id=?',(ident,))]
                self.assertTrue(all((self.reconciler.directory/target).read_bytes()==original for target in targets))

    def test_database_contention_obeys_short_busy_budget_and_keeps_source(self):
        import sqlite3
        _,source=self.artifact()
        blocker=sqlite3.connect(self.store.path,timeout=.1)
        try:
            blocker.execute('BEGIN IMMEDIATE')
            start=time.monotonic();result=self.reconciler.run_once(now=1000,max_seconds=.1)
            self.assertLess(time.monotonic()-start,1.0)
            self.assertTrue(result['state']=='unavailable' or result.get('budget_exhausted'));self.assertTrue(source.is_file())
        finally:blocker.rollback();blocker.close()
        for _ in range(3):
            self.drain()
            if not source.exists():break
        self.assertFalse(source.exists())

    def test_move_budget_expiry_keeps_durable_intent_for_next_cycle(self):
        from sanequeue.reporting.export_maintenance import _BudgetExpired
        source,row=self.intent();link=os.link
        def interrupted(*args,**kwargs):
            link(*args,**kwargs);raise _BudgetExpired('test')
        with patch('sanequeue.reporting.export_maintenance.os.link',side_effect=interrupted):
            result=self.reconciler.run_once(now=1000,max_seconds=1)
        self.assertTrue(result['budget_exhausted']);self.assertTrue(source.exists())
        self.drain();self.assertFalse(source.exists())
        self.assertEqual((self.reconciler.directory/row['target']).read_bytes(),b'private')

    def test_maintenance_health_logs_only_state_changes_without_private_paths(self):
        worker=self.case.worker();worker.reconciler=self.reconciler
        with patch.object(self.reconciler,'run_once',side_effect=[{'state':'unavailable'},{'state':'unavailable'},{'state':'ready'}]):
            with self.assertLogs('sanequeue.reporting.export_jobs',level='INFO') as logs:
                for _ in range(3):self.assertEqual(worker.run_once()['state'],'idle')
        self.assertEqual(len(logs.output),2)
        self.assertTrue(logs.output[0].endswith('export_artifact_recovery_unavailable'))
        self.assertTrue(logs.output[1].endswith('export_artifact_recovery_resumed'))
        self.assertNotIn(str(self.store.output_dir),' '.join(logs.output))

    def test_completed_history_does_not_exhaust_pending_intent_quota(self):
        for _ in range(101):
            source,row=self.intent();self.reconciler._finish(row,'protected',1000)
        source,row=self.intent();self.assertIsNotNone(row)
        self.reconciler._directories(create=True);self.reconciler._move(row,None,1000)
        self.assertFalse(source.exists())


if __name__=='__main__':unittest.main()


class ArtifactRecoveryAPITests(unittest.TestCase):
    def setUp(self):
        from tests import test_reporting_queries as report_fixtures
        from sanequeue.reporting.export_jobs import JobStore,projection_watermark
        from sanequeue.reporting.queries import Scope
        self.case=report_fixtures.ReportTests();self.case.setUp();self.addCleanup(self.case.doCleanups);self.case.seed()
        self.client=self.case.client(menus=('reports',),details=True)
        self.store=JobStore(self.case.archive.path.parent/'export-jobs.sqlite3',self.case.archive.path.parent/'private-exports');self.store.initialize()
        reconciler=ArtifactReconciler(self.store,grace_seconds=0);self.addCleanup(reconciler.close)
        self.ids=[]
        for owner in ('test','other'):
            ident=self.store.create(owner,Scope(('8001',)),self.case.stamp,self.case.stamp+100,
                watermark=projection_watermark(self.case.archive),number_modes={'8001':'full'})
            self.ids.append(ident);self.store.cancel(ident,owner)
            path=self.store.output_dir/(ident+'.csv');path.write_bytes(b'PRIVATE CUSTOMER DATA')
        for _ in range(10):
            if reconciler.run_once(now=time.time()+1,max_seconds=1)['scan_complete']:break
    def test_recovery_metadata_is_owner_scoped_currently_authorized_and_path_free(self):
        response=self.client.get('/api/history/export-jobs')
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual([row['job_id'] for row in response.json['recovery']],[self.ids[0]])
        self.assertNotIn('PRIVATE CUSTOMER DATA',response.text)
        self.assertNotIn('source',response.json['recovery'][0]);self.assertNotIn('target',response.json['recovery'][0])
        self.assertEqual(response.headers['Cache-Control'],'private, no-store')
        revoked=self.case.client(menus=('reports',),details=True,denied=('report_export',))
        self.assertEqual(revoked.get('/api/history/export-jobs').json['recovery'],[])
        masked=self.case.client(menus=('reports',),details=False)
        self.assertEqual(masked.get('/api/history/export-jobs').json['recovery'],[])
        self.assertEqual(self.case.client(role='agent').get('/api/history/export-jobs').status_code,403)
        self.assertEqual(self.client.get('/api/history/export-jobs/'+self.ids[0]+'/download').status_code,404)
