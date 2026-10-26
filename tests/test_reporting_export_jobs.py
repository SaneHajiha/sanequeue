import csv
import io
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from sanequeue.reporting.export_jobs import (JobStore,ExportWorker,ExportFailure,Limits,
    projection_watermark,_worker_lock,_number_key)
from sanequeue.reporting.facts import project_batch
from sanequeue.reporting.queries import Scope
from sanequeue.reporting.store import Archive


class ExportJobTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.archive=Archive(self.root/'archive.db',min_free_bytes=0);self.archive.initialize()
        project_batch(self.archive,inventory={})
        self.store=JobStore(self.root/'jobs'/'jobs.db',self.root/'private-output');self.store.initialize()
        self.limits=Limits(min_free_bytes=0,max_load_per_cpu=0)

    def seed(self,count=1,queue='8001',agent='100',caller='09123456789'):
        with self.archive.writer() as db:
            db.executemany('INSERT INTO report_visits VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                [('primary',format(i+1,'064x'),'private-call-'+str(i),queue,100+i/1000,101,120,
                  caller,agent,'answered',1,19,'caller','observed') for i in range(count)])

    def create(self,owner='alice',scope=None,modes=None,**extra):
        return self.store.create(owner,scope or Scope(('8001',)),90,300,
            watermark=projection_watermark(self.archive),number_modes=modes or {'8001':'masked'},**extra)

    def worker(self,**extra):
        return ExportWorker(self.store,self.archive,limits=extra.pop('limits',self.limits),**extra)

    def read(self,ident,owner='alice'):
        fd,size=self.store.open_output(ident,owner)
        with os.fdopen(fd,'rb') as stream:body=stream.read()
        self.assertEqual(len(body),size)
        return list(csv.reader(io.StringIO(body.decode('utf-8-sig'))))

    def test_large_csv_uses_bounded_pages_and_closes_archive_readers(self):
        self.seed(405);ident=self.create()
        worker=self.worker();sizes=[];original=worker._page
        def page(*args):
            rows=original(*args);sizes.append(len(rows))
            # A writer can proceed after each page: no long read transaction
            # or archive writes from the export worker are required.
            with self.archive.writer() as db:db.execute('SELECT 1')
            return rows
        worker._page=page
        result=worker.run_once()
        self.assertEqual(result['state'],'completed')
        self.assertEqual(sizes,[200,200,5,0])
        content=self.read(ident)
        self.assertEqual(len(content),406)
        self.assertEqual(content[1][1],'0912***6789')
        job=self.store.get(ident,'alice')
        self.assertEqual((job['rows'],job['state']),(405,'completed'))
        self.assertEqual(len(job['checksum']),64)
        self.assertFalse(self.store.cancel(ident,'alice'))
        self.assertFalse(list(self.store.output_dir.glob('*.part')))

    def test_immutable_scope_masking_snapshot_owner_and_revocation(self):
        self.seed(1)
        with self.archive.writer() as db:
            db.execute('INSERT INTO report_visits SELECT pbx,?,callid,?,entered,answered,ended,caller,agent,outcome,wait_seconds,talk_seconds,segment_ended_by,coverage FROM report_visits LIMIT 1',('f'*64,'8002'))
        queues=['8001'];modes={'8001':'masked'}
        ident=self.create(scope=Scope(queues),modes=modes)
        queues.append('8002');modes['8001']='full';modes['8002']='full'
        job=self.store.get(ident,'alice')
        self.assertEqual(job['spec']['scope']['queues'],['8001'])
        self.assertEqual(job['spec']['number_modes'],{'8001':'masked'})
        self.assertIsNone(self.store.get(ident,'bob'))
        self.assertEqual(self.store.list('bob'),[])
        self.assertFalse(self.store.cancel(ident,'bob'))
        self.assertEqual(self.worker().run_once()['state'],'completed')
        self.assertEqual(len(self.read(ident)),2)
        with self.assertRaises(FileNotFoundError):self.store.open_output(ident,'bob')
        revoked=self.create()
        result=self.worker(authorize=lambda spec:False).run_once()
        self.assertEqual(result['error'],'export_access_revoked')
        with self.assertRaises(FileNotFoundError):self.store.open_output(revoked,'alice')

    def test_formula_neutralization_and_number_policy_are_independent(self):
        self.seed(agent='  =HYPERLINK("bad")',caller='+989123456789')
        ident=self.create(modes={'8001':'full'})
        self.worker().run_once();row=self.read(ident)[1]
        self.assertTrue(row[1].startswith("'+"));self.assertTrue(row[2].startswith("'  ="))
        hidden=self.create(modes={'8001':'hidden'});self.worker().run_once()
        self.assertEqual(self.read(hidden)[1][1],'')
        pseudo=self.create(modes={'8001':'pseudonymous'})
        self.assertEqual(self.worker(number_key=b'k'*32).run_once()['state'],'completed')
        self.assertTrue(self.read(pseudo)[1][1].startswith('Caller #'))

    def test_cancel_running_cleans_partial_and_never_publishes(self):
        self.seed(3);ident=self.create()
        worker=self.worker(limits=Limits(page_size=1,min_free_bytes=0,max_load_per_cpu=0))
        original=worker._page
        def cancel_after_read(*args):
            rows=original(*args);self.store.cancel(ident,'alice');return rows
        worker._page=cancel_after_read
        self.assertEqual(worker.run_once()['state'],'cancelled')
        self.assertEqual(self.store.get(ident,'alice')['state'],'cancelled')
        with self.assertRaises(FileNotFoundError):self.store.open_output(ident,'alice')
        self.assertEqual(list(self.store.output_dir.iterdir()),[])

    def test_cancel_queued_and_progress_listing_are_owner_scoped(self):
        ident=self.create();self.assertTrue(self.store.cancel(ident,'alice'))
        self.assertFalse(self.store.cancel(ident,'alice'))
        self.assertEqual(self.worker().run_once()['state'],'idle')
        self.assertEqual([job['id'] for job in self.store.list('alice')],[ident])
        self.assertEqual(self.store.list('alice')[0]['state'],'cancelled')
        with self.assertRaises(ValueError):self.store.get('../jobs.db','alice')

    def test_expired_lease_recovers_from_zero_without_reusing_partial(self):
        self.seed();ident=self.create()
        claimed=self.store.claim('crashed',now=self.store.get(ident,'alice')['available_at']+1)
        self.assertEqual(claimed['id'],ident)
        with self.store._db(write=True) as db:
            db.execute('UPDATE export_jobs SET lease_until=? WHERE id=?',(time.time()-1,ident))
        partial=self.store.output_dir/(ident+'.crashed.part');partial.write_bytes(b'private incomplete')
        self.assertEqual(self.worker().run_once()['state'],'completed')
        self.assertFalse(partial.exists())
        self.assertEqual(self.store.get(ident,'alice')['attempts'],2)
        self.assertEqual(len(self.read(ident)),2)

    def test_watermark_change_after_page_fails_instead_of_mixing_snapshots(self):
        self.seed(3);ident=self.create()
        worker=self.worker(limits=Limits(page_size=1,min_free_bytes=0,max_load_per_cpu=0))
        original=worker._page
        def advance(*args):
            rows=original(*args)
            with self.archive.writer() as db:db.execute('UPDATE report_projection SET after_id=after_id+1')
            return rows
        worker._page=advance
        result=worker.run_once()
        self.assertEqual(result['error'],'export_projection_changed')
        self.assertEqual(self.store.get(ident,'alice')['state'],'failed')
        self.assertEqual(list(self.store.output_dir.iterdir()),[])

    def test_row_and_byte_limits_fail_without_downloadable_truncation(self):
        self.seed(3)
        for limits,reason in ((Limits(max_rows=2,min_free_bytes=0,max_load_per_cpu=0),'export_row_limit'),
                              (Limits(max_bytes=20,min_free_bytes=0,max_load_per_cpu=0),'export_byte_limit')):
            ident=self.create();result=self.worker(limits=limits).run_once()
            self.assertEqual(result['error'],reason)
            with self.assertRaises(FileNotFoundError):self.store.open_output(ident,'alice')
        self.assertEqual(list(self.store.output_dir.iterdir()),[])

    def test_existing_output_is_not_overwritten_and_failed_job_is_not_downloadable(self):
        self.seed();ident=self.create();final=self.store.output_dir/(ident+'.csv')
        final.write_bytes(b'original')
        self.assertEqual(self.worker().run_once()['error'],'export_output_exists')
        self.assertEqual(final.read_bytes(),b'original')
        with self.assertRaises(FileNotFoundError):self.store.open_output(ident,'alice')

    def test_only_one_worker_and_disk_load_disable_gates(self):
        ident=self.create()
        with _worker_lock(str(self.store.path)+'.worker.lock') as acquired:
            self.assertTrue(acquired);self.assertEqual(self.worker().run_once()['state'],'busy')
        disabled=self.root/'disabled';disabled.touch()
        self.assertEqual(self.worker(disabled_file=disabled).run_once()['error'],'module_disabled')
        with patch('sanequeue.reporting.export_jobs.shutil.disk_usage',return_value=type('Usage',(),{'free':0})()):
            result=self.worker(limits=Limits(min_free_bytes=1,max_load_per_cpu=0)).run_once()
            self.assertEqual(result['error'],'export_disk_pressure')
        with patch('sanequeue.reporting.export_jobs.os.getloadavg',return_value=(10,0,0),create=True),patch('sanequeue.reporting.export_jobs.os.cpu_count',return_value=1):
            self.assertEqual(self.worker(limits=Limits(min_free_bytes=0)).run_once()['error'],'export_system_busy')
        self.assertEqual(self.store.get(ident,'alice')['state'],'queued')

    def test_quotas_unsupported_formats_storage_separation_and_private_key(self):
        for _ in range(3):self.create()
        with self.assertRaisesRegex(ExportFailure,'quota'):self.create()
        for i in range(7):self.create(owner='owner-'+str(i))
        with self.assertRaisesRegex(ExportFailure,'quota'):self.create(owner='global')
        with self.assertRaises(ValueError):self.create(format='pdf')
        with self.assertRaisesRegex(ValueError,'database_is_archive'):
            JobStore(self.archive.path,self.root/'another-output').initialize()
        key=self.root/'key';key.write_bytes(b'x'*32);os.chmod(key,0o600)
        self.assertEqual(_number_key(key),b'x'*32)
        key.write_bytes((b'x'*32).hex().encode()+b'\n');self.assertEqual(_number_key(key),b'x'*32)

    def test_self_assignment_cutoff_and_empty_scope_cannot_expand(self):
        self.seed(3)
        ident=self.create(scope=Scope(('8001',),('100',),True,100.001))
        self.worker().run_once();self.assertEqual(len(self.read(ident)),3)
        with self.assertRaises(ValueError):self.store.create('alice',Scope(()),90,300,watermark=0,number_modes={})
        with self.assertRaises(ValueError):self.create(modes={'8002':'full'})

    def test_mid_export_revocation_and_time_limit_remove_partial_output(self):
        self.seed(3);ident=self.create();granted=[True]
        worker=self.worker(authorize=lambda spec:granted[0]);original=worker._page
        def revoke_after_page(*args):
            rows=original(*args);granted[0]=False;return rows
        worker._page=revoke_after_page
        self.assertEqual(worker.run_once()['error'],'export_access_revoked')
        self.assertEqual(self.store.get(ident,'alice')['state'],'failed')
        timed=self.create();worker=self.worker();original=worker._page
        def over_deadline(*args):
            rows=original(*args);worker._gate(deadline=0);return rows
        worker._page=over_deadline
        self.assertEqual(worker.run_once()['error'],'export_time_limit')
        self.assertEqual(self.store.get(timed,'alice')['state'],'failed')
        self.assertEqual(list(self.store.output_dir.iterdir()),[])

    def test_disable_environment_matches_the_organization_switch(self):
        disabled=self.root/'organization-disabled';disabled.touch();ident=self.create()
        with patch.dict(os.environ,{'SANEQUEUE_DISABLE_FILE':str(disabled)}):
            self.assertEqual(self.worker().run_once()['error'],'module_disabled')
        self.assertEqual(self.store.get(ident,'alice')['state'],'queued')

    def test_crash_after_link_recovers_only_the_authenticated_complete_artifact(self):
        self.seed();ident=self.create();link=os.link
        def crash_after_link(source,destination):
            link(source,destination)
            raise SystemExit('simulated process death')
        with patch('sanequeue.reporting.export_jobs.os.link',side_effect=crash_after_link):
            with self.assertRaises(SystemExit):self.worker().run_once()
        final=self.store.output_dir/(ident+'.csv')
        self.assertTrue(final.is_file())
        self.assertEqual(self.store.get(ident,'alice')['state'],'running')
        with self.assertRaises(FileNotFoundError):self.store.open_output(ident,'alice')
        before=final.read_bytes()
        with self.store._db(write=True) as db:db.execute('UPDATE export_jobs SET lease_until=0 WHERE id=?',(ident,))
        result=self.worker().run_once()
        self.assertTrue(result['recovered'])
        self.assertEqual(final.read_bytes(),before)
        self.assertEqual(len(self.read(ident)),2)

    def test_deferred_recovery_preserves_manifest_and_can_finish_later(self):
        from sanequeue.reporting.export_jobs import _Deferred
        self.seed();ident=self.create();link=os.link
        def crash(source,destination):
            link(source,destination);raise SystemExit('simulated process death')
        with patch('sanequeue.reporting.export_jobs.os.link',side_effect=crash):
            with self.assertRaises(SystemExit):self.worker().run_once()
        with self.store._db(write=True) as db:db.execute('UPDATE export_jobs SET lease_until=0 WHERE id=?',(ident,))
        worker=self.worker();gate=worker._gate;calls=[]
        def pause(deadline=None):
            calls.append(1)
            if len(calls)==2:raise _Deferred('export_system_busy')
            return gate(deadline)
        worker._gate=pause
        self.assertEqual(worker.run_once()['state'],'queued')
        self.assertIsNotNone(self.store.get(ident,'alice')['checksum'])
        with self.store._db(write=True) as db:db.execute('UPDATE export_jobs SET available_at=0 WHERE id=?',(ident,))
        self.assertTrue(self.worker().run_once()['recovered'])

    def test_authenticated_crash_artifact_is_removed_when_recovery_is_stale(self):
        self.seed();ident=self.create();link=os.link
        def crash_after_link(source,destination):
            link(source,destination);raise SystemExit('simulated process death')
        with patch('sanequeue.reporting.export_jobs.os.link',side_effect=crash_after_link):
            with self.assertRaises(SystemExit):self.worker().run_once()
        with self.store._db(write=True) as db:db.execute('UPDATE export_jobs SET lease_until=0 WHERE id=?',(ident,))
        with self.archive.writer() as db:db.execute('UPDATE report_projection SET after_id=after_id+1')
        self.assertEqual(self.worker().run_once()['error'],'export_projection_changed')
        self.assertFalse((self.store.output_dir/(ident+'.csv')).exists())
        self.assertEqual(self.store.get(ident,'alice')['state'],'failed')
