from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sanequeue.reporting.export_jobs import JobStore,ExportFailure,projection_watermark,_worker_lock
from sanequeue.reporting.facts import project_batch
from sanequeue.reporting.plan_worker import PlanWorker,current_modes
from sanequeue.reporting.queries import Scope
from sanequeue.reporting.report_plans import SavedReports
from sanequeue.reporting.store import Archive
from sanequeue.reporting.visit_snapshots import capture,SnapshotUnavailable


class PlanWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.stamp=datetime(2026,10,24,9,tzinfo=ZoneInfo('Asia/Tehran')).timestamp()
        self.clock=patch('sanequeue.reporting.plan_worker.time.time',return_value=self.stamp)
        self.now=self.clock.start();self.addCleanup(self.clock.stop)
        self.archive=Archive(self.root/'history.db',min_free_bytes=0);self.archive.initialize()
        while project_batch(self.archive,inventory={})['processed']:pass
        self.plans=SavedReports(self.root/'plans.db');self.plans.initialize()
        self.jobs=JobStore(self.root/'jobs.db',self.root/'private-output');self.jobs.initialize()
        self.plan=self.plans.save('owner','Daily',['8001'],enabled=True)
        self.modes={'8001':'full'}
        self.disabled=self.root/'module.disabled'
        self.worker=PlanWorker(self.plans,self.jobs,self.archive,
            lambda owner,queues:None if self.modes is None else dict(self.modes),disabled_file=self.disabled)

    def create(self,key='manual',**changes):
        bounds=capture(self.archive)
        spec=dict(owner='owner',scope=Scope(('8001',)),start=self.stamp-86400,end=self.stamp,
                  watermark=projection_watermark(self.archive),number_modes={'8001':'full'},snapshot=bounds,request_key=key)
        spec.update(changes);return self.jobs.create(**spec)

    def occurrence(self):return self.plans.occurrences(self.plan['id'],'owner')[0]

    def crash_after_create(self):
        with patch.object(self.plans,'finish',side_effect=SystemExit('simulated process death')):
            with self.assertRaises(SystemExit):self.worker.run_once()
        self.assertEqual(len(self.jobs.list('owner')),1)
        return self.jobs.list('owner')[0]

    def test_dispatch_is_unique_and_cross_database_crash_reuses_original_snapshot(self):
        original=self.crash_after_create();self.now.return_value=self.stamp+61
        with patch('sanequeue.reporting.plan_worker.capture',side_effect=AssertionError('must reuse original snapshot')),\
             patch('sanequeue.reporting.plan_worker.projection_watermark',side_effect=AssertionError('no archive read')):
            result=self.worker.run_once()
        self.assertEqual(result['state'],'dispatched');self.assertEqual(result['export_job_id'],original['id'])
        self.assertEqual(self.jobs.get(original['id'],'owner')['spec'],original['spec'])
        self.assertEqual(len(self.jobs.list('owner')),1)
        self.assertEqual(self.occurrence()['export_job_id'],original['id'])
        self.assertEqual(self.worker.run_once()['state'],'idle')

    def test_disabled_plan_during_snapshot_never_creates_an_export(self):
        def disable(archive):
            self.plans.save('owner','Daily',['8001'],enabled=False,ident=self.plan['id'])
            return capture(archive)
        with patch('sanequeue.reporting.plan_worker.capture',side_effect=disable):result=self.worker.run_once()
        self.assertEqual(result['state'],'cancelled');self.assertEqual(self.jobs.list('owner'),[])
        self.assertEqual(self.occurrence()['state'],'cancelled')

    def test_disabling_after_create_or_at_finish_cancels_the_queued_export(self):
        def disable_at_finish(*args):
            self.plans.save('owner','Daily',['8001'],enabled=False,ident=self.plan['id'])
            return False
        with patch.object(self.plans,'finish',side_effect=disable_at_finish):result=self.worker.run_once()
        self.assertEqual(result['state'],'cancelled')
        self.assertEqual(self.jobs.list('owner')[0]['state'],'cancelled')
        self.assertEqual(self.occurrence()['state'],'cancelled')

    def test_lease_loss_alone_keeps_original_export_for_the_recovering_worker(self):
        create=self.jobs.create
        def expire_after_create(*args,**kwargs):
            ident=create(*args,**kwargs);self.now.return_value=self.stamp+61;return ident
        with patch.object(self.jobs,'create',side_effect=expire_after_create):result=self.worker.run_once()
        self.assertEqual(result['state'],'lease_lost')
        original=self.jobs.list('owner')[0];self.assertEqual(original['state'],'queued')
        recovered=self.worker.run_once()
        self.assertEqual(recovered['export_job_id'],original['id']);self.assertEqual(len(self.jobs.list('owner')),1)

    def test_current_permission_revocation_after_snapshot_stops_dispatch(self):
        def revoke(archive):self.modes=None;return capture(archive)
        with patch('sanequeue.reporting.plan_worker.capture',side_effect=revoke):result=self.worker.run_once()
        self.assertEqual(result['reason'],'access_revoked');self.assertEqual(self.jobs.list('owner'),[])
        self.assertEqual(self.occurrence()['error'],'access_revoked')

    def test_number_policy_downgrade_before_create_masks_and_after_create_cancels(self):
        def downgrade(archive):self.modes={'8001':'masked'};return capture(archive)
        with patch('sanequeue.reporting.plan_worker.capture',side_effect=downgrade):result=self.worker.run_once()
        self.assertEqual(self.jobs.get(result['export_job_id'],'owner')['spec']['number_modes'],{'8001':'masked'})
        # A separate day's newly full export loses the full-number grant after
        # its creation; the immutable full artifact may not be dispatched.
        self.now.return_value=self.stamp+86400;self.modes={'8001':'full'};create=self.jobs.create
        def revoke_after_create(*args,**kwargs):
            ident=create(*args,**kwargs);self.modes={'8001':'masked'};return ident
        with patch.object(self.jobs,'create',side_effect=revoke_after_create):result=self.worker.run_once()
        self.assertEqual(result['reason'],'access_revoked')
        latest=self.jobs.list('owner')[0];self.assertEqual(latest['state'],'cancelled')
        self.assertEqual(latest['spec']['number_modes'],{'8001':'full'})

    def test_recovery_never_resurrects_cancelled_export_and_reports_actual_state(self):
        original=self.crash_after_create();self.jobs.cancel(original['id'],'owner');self.now.return_value=self.stamp+61
        result=self.worker.run_once()
        self.assertEqual(result['export_job_id'],original['id']);self.assertEqual(result['export_state'],'cancelled')
        self.assertEqual(self.jobs.get(original['id'],'owner')['state'],'cancelled')
        self.assertEqual(len(self.jobs.list('owner')),1)

    def test_prior_full_numbers_cannot_be_reused_after_permission_downgrade(self):
        original=self.crash_after_create();self.now.return_value=self.stamp+61;self.modes={'8001':'masked'}
        result=self.worker.run_once()
        self.assertEqual(result['reason'],'access_revoked')
        self.assertEqual(self.jobs.get(original['id'],'owner')['state'],'cancelled')
        self.assertEqual(self.occurrence()['state'],'failed')

    def test_request_core_conflict_is_not_acknowledged_as_the_scheduled_export(self):
        occurrence=self.plans.reserve_due('old-attempt')
        self.create(key='schedule:'+occurrence['id'],format='csv')
        self.now.return_value=self.stamp+61
        result=self.worker.run_once()
        self.assertEqual(result['state'],'failed');self.assertEqual(self.occurrence()['error'],'export_failed')
        self.assertIsNone(self.occurrence()['export_job_id']);self.assertEqual(len(self.jobs.list('owner')),1)

    def test_quota_snapshot_and_module_defer_do_not_spend_attempts(self):
        self.disabled.touch();self.assertEqual(self.worker.run_once()['state'],'paused')
        self.assertEqual(self.plans.occurrences(self.plan['id'],'owner'),[]);self.disabled.unlink()
        with patch('sanequeue.reporting.plan_worker.capture',side_effect=SnapshotUnavailable('initializing')):
            self.assertEqual(self.worker.run_once()['reason'],'export_unavailable')
        self.assertEqual(self.occurrence()['attempts'],0)
        self.now.return_value=self.stamp+31
        for index in range(3):self.create(str(index))
        self.assertEqual(self.worker.run_once()['reason'],'system_busy');self.assertEqual(self.occurrence()['attempts'],0)

    def test_worker_lock_and_malformed_authorization_fail_closed(self):
        with _worker_lock(str(self.plans.path)+'.worker.lock') as acquired:
            self.assertTrue(acquired);self.assertEqual(self.worker.run_once()['state'],'busy')
        self.modes={'8002':'full'}
        self.assertEqual(self.worker.run_once()['reason'],'access_revoked');self.assertEqual(self.jobs.list('owner'),[])

    def test_job_request_idempotency_is_atomic_and_ignores_only_snapshot_watermark(self):
        original=self.create('stable')
        self.assertEqual(self.create('stable',watermark=999),original)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(lambda _:self.create('concurrent'),range(2)))
        self.assertEqual(results[0],results[1]);self.assertEqual(len(self.jobs.list('owner')),2)
        for changes in (dict(start=self.stamp-100),dict(number_modes={'8001':'masked'}),dict(language='fa'),dict(format='xlsx')):
            with self.subTest(changes=changes),self.assertRaisesRegex(ExportFailure,'export_request_conflict'):
                self.create('stable',**changes)
        other=self.create('stable',owner='other');self.assertNotEqual(other,original)
        self.assertEqual(self.jobs.by_request('owner','stable')['id'],original)
        self.assertIsNone(self.jobs.by_request('unknown','stable'))

    def test_idempotency_detects_corrupted_original_spec_and_request_hash(self):
        ident=self.create('stable')
        with self.jobs._db(write=True) as db:db.execute("UPDATE export_jobs SET request_hash='bad' WHERE id=?",(ident,))
        with self.assertRaisesRegex(ExportFailure,'export_request_integrity'):self.jobs.by_request('owner','stable')
        with self.assertRaisesRegex(ExportFailure,'export_request_integrity'):self.create('stable')

    def test_current_modes_reloads_account_and_queue_permissions(self):
        accounts=self.root/'accounts.json';policies=self.root/'policies.json'
        account=dict(role='supervisor',phone='PJSIP/100',password_hash='pbkdf2:sha256:placeholder',menus=['reports'])
        accounts.write_text(json.dumps(dict(owner=account)),encoding='utf-8')
        policy=dict(version=1,queues={'8001':{}},supervisors={'owner':dict(queues=['8001'],actions=['view','report_export','caller_details'])})
        policies.write_text(json.dumps(policy),encoding='utf-8')
        self.assertEqual(current_modes('owner',['8001'],accounts,policies),{'8001':'full'})
        policy['supervisors']['owner']['actions'].remove('caller_details');policies.write_text(json.dumps(policy),encoding='utf-8')
        self.assertEqual(current_modes('owner',['8001'],accounts,policies),{'8001':'masked'})
        account['menus']=[];accounts.write_text(json.dumps(dict(owner=account)),encoding='utf-8')
        self.assertIsNone(current_modes('owner',['8001'],accounts,policies))


if __name__=='__main__':unittest.main()
