"""Frozen custom scheduled definitions and current grants; no PBX connections."""
from datetime import datetime
import csv
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sanequeue.reporting.export_jobs import JobStore,ExportWorker,Limits
from sanequeue.reporting.facts import project_batch
from sanequeue.reporting.plan_worker import PlanWorker
from sanequeue.reporting.queries import Scope
from sanequeue.reporting.report_builder import definition
from sanequeue.reporting.report_plans import SavedReports
from sanequeue.reporting.store import Archive
from sanequeue.reporting.visit_snapshots import capture
from sanequeue.reporting import builder_exports


def custom(**changes):
    value=dict(dataset='queue_visits',queues=['8001'],columns=['queue','caller','talk_seconds'],
               group_by=[],filters={'outcomes':['answered'],'wait_max':5,'talk_min':1,'talk_max':15})
    value.update(changes);return value


class BuilderPlanFixtures:
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.plans=SavedReports(self.root/'plans.db');self.plans.initialize()
        self.stamp=datetime(2026,10,24,9,tzinfo=ZoneInfo('Asia/Tehran')).timestamp()
        clock=patch('sanequeue.reporting.report_plans.time.time',return_value=self.stamp)
        self.now=clock.start();self.addCleanup(clock.stop)

    def save(self,**changes):
        value=dict(owner='owner',name='Custom daily',queues=['8001'],format='csv',language='en',enabled=True,builder_definition=custom())
        value.update(changes);return self.plans.save(**value)


class BuilderPlanStoreTests(BuilderPlanFixtures,unittest.TestCase):
    def test_complete_canonical_definition_is_versioned_and_occurrence_frozen(self):
        supplied=custom();plan=self.save(builder_definition=supplied)
        frozen=definition(supplied);supplied['columns'].append('agent');supplied['filters']['talk_max']=60
        self.assertEqual(self.plans.get(plan['id'],'owner')['builder_definition'],frozen)
        occurrence=self.plans.reserve_due('attempt-old');self.plans.defer(occurrence['id'],'attempt-old')
        changed=custom(columns=['agent','outcome'],group_by=['agent'],filters={'talk_min':30})
        updated=self.save(ident=plan['id'],builder_definition=changed)
        self.assertEqual(updated['version'],2)
        self.now.return_value+=31
        retried=self.plans.reserve_due('attempt-new')
        self.assertEqual(retried['id'],occurrence['id']);self.assertEqual(retried['version'],1)
        self.assertEqual(retried['spec']['builder_definition'],frozen)
        self.assertNotEqual(updated['builder_definition'],frozen)
        with self.plans._db() as db:
            versions=[json.loads(row[0]) for row in db.execute('SELECT spec FROM report_plan_versions WHERE plan_id=? ORDER BY version',(plan['id'],))]
        self.assertEqual(versions[0]['builder_definition'],frozen)
        self.assertEqual(versions[1]['builder_definition'],definition(changed))

    def test_standard_plan_shape_preserved_and_custom_invalid_contracts_rejected(self):
        standard=self.plans.save('owner','Legacy PDF',['8001'],format='pdf')
        self.assertNotIn('builder_definition',standard)
        for changes in (dict(queues=['8002']),dict(outcome='answered'),dict(format='pdf'),
                        dict(builder_definition=custom(dataset='cdr')),dict(builder_definition=custom(columns=['secret_sql'])),
                        dict(builder_definition=custom(filters={'sql':'1=1'}))):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.save(**changes)
        self.assertEqual(len(self.plans.list('owner')),1)

    def test_disable_and_archive_cancel_pending_custom_occurrences_without_rewriting_spec(self):
        plan=self.save();occurrence=self.plans.reserve_due('attempt')
        original=occurrence['spec']['builder_definition']
        self.save(ident=plan['id'],enabled=False,builder_definition=custom(columns=['agent']))
        current=self.plans.occurrence(occurrence['id'],'owner')
        self.assertEqual(current['state'],'cancelled');self.assertEqual(current['spec']['builder_definition'],original)
        self.assertTrue(self.plans.delete(plan['id'],'owner'))
        self.assertEqual(self.plans.occurrence(occurrence['id'],'owner')['spec']['builder_definition'],original)


class BuilderPlanWorkerTests(BuilderPlanFixtures,unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.archive=Archive(self.root/'history.db',min_free_bytes=0);self.archive.initialize()
        while project_batch(self.archive,inventory={})['processed']:pass
        self.jobs=JobStore(self.root/'jobs.db',self.root/'outputs');self.jobs.initialize()
        self.disabled=self.root/'module.disabled';self.grants={'8001':'full','8002':'masked'}
        self.worker=PlanWorker(self.plans,self.jobs,self.archive,
            lambda owner,queues:{q:self.grants[q] for q in queues} if self.grants is not None and all(q in self.grants for q in queues) else None,
            disabled_file=self.disabled)

    def occurrence(self,plan):return self.plans.occurrences(plan['id'],'owner')[0]

    def test_queued_occurrence_runs_its_frozen_columns_groups_filters_after_plan_edit(self):
        original=custom(group_by=['queue','outcome']);plan=self.save(builder_definition=original)
        occurrence=self.plans.reserve_due('initial');self.plans.defer(occurrence['id'],'initial')
        self.save(ident=plan['id'],queues=['8002'],builder_definition=custom(queues=['8002'],columns=['agent'],group_by=['agent'],filters={'talk_min':45}))
        self.now.return_value+=31
        result=self.worker.run_once();self.assertEqual(result['state'],'dispatched')
        job=self.jobs.get(result['export_job_id'],'owner')
        self.assertEqual(job['spec']['builder_definition'],definition(original))
        self.assertEqual(job['spec']['scope']['queues'],['8001'])
        self.assertIsNone(job['spec']['outcome']);self.assertIn('snapshot',job['spec'])

    def test_crash_recovery_reuses_exact_definition_job_and_snapshot_after_template_edit(self):
        plan=self.save();original=definition(custom())
        with patch.object(self.plans,'finish',side_effect=SystemExit('simulated death')):
            with self.assertRaises(SystemExit):self.worker.run_once()
        prior=self.jobs.list('owner')[0]
        self.save(ident=plan['id'],builder_definition=custom(columns=['id'],filters={}))
        self.now.return_value+=61
        with patch('sanequeue.reporting.plan_worker.builder_exports.capture',side_effect=AssertionError('must reuse frozen snapshot')):
            result=self.worker.run_once()
        self.assertEqual(result['export_job_id'],prior['id']);self.assertEqual(len(self.jobs.list('owner')),1)
        self.assertEqual(self.jobs.get(prior['id'],'owner')['spec'],prior['spec'])
        self.assertEqual(prior['spec']['builder_definition'],original)

    def test_revocation_after_snapshot_prevents_custom_export_and_disabled_plan_cancels_job(self):
        plan=self.save()
        real_capture=builder_exports.capture
        def revoke(archive):self.grants={};return real_capture(archive)
        with patch('sanequeue.reporting.plan_worker.builder_exports.capture',side_effect=revoke):result=self.worker.run_once()
        self.assertEqual(result['reason'],'access_revoked');self.assertEqual(self.jobs.list('owner'),[])
        self.assertEqual(self.occurrence(plan)['state'],'failed')
        self.grants={'8001':'full'};self.assertTrue(self.plans.retry(self.occurrence(plan)['id'],'owner'))
        create=self.jobs.create
        def disable(*args,**kwargs):
            ident=create(*args,**kwargs);self.save(ident=plan['id'],enabled=False);return ident
        with patch.object(self.jobs,'create',side_effect=disable):result=self.worker.run_once()
        self.assertEqual(result['state'],'cancelled');self.assertEqual(self.jobs.list('owner')[0]['state'],'cancelled')

    def test_same_request_key_cannot_acknowledge_different_custom_definition(self):
        plan=self.save();occurrence=self.plans.reserve_due('old-attempt');spec=occurrence['spec']
        self.jobs.create('owner',Scope(('8001',)),spec['start'],spec['end'],watermark=0,
            number_modes={'8001':'full'},language='en',format='csv',snapshot=capture(self.archive),
            request_key='schedule:'+occurrence['id'],builder_definition=custom(columns=['agent']))
        self.now.return_value+=61
        result=self.worker.run_once()
        self.assertEqual(result['state'],'failed');self.assertIsNone(self.occurrence(plan)['export_job_id'])
        self.assertEqual(len(self.jobs.list('owner')),1)

    def test_module_disabled_during_custom_snapshot_is_deferred_without_export(self):
        plan=self.save()
        real_capture=builder_exports.capture
        def disable(archive):self.disabled.touch();return real_capture(archive)
        with patch('sanequeue.reporting.plan_worker.builder_exports.capture',side_effect=disable):result=self.worker.run_once()
        self.assertEqual(result['reason'],'module_disabled');self.assertEqual(self.jobs.list('owner'),[])
        self.assertEqual(self.occurrence(plan)['attempts'],0)

    def test_custom_schedule_uses_combined_capture_without_separate_metadata_reads(self):
        self.save()
        with patch('sanequeue.reporting.plan_worker.capture',side_effect=AssertionError('custom path must use combined capture')),\
             patch('sanequeue.reporting.plan_worker.projection_watermark',side_effect=AssertionError('custom path must use combined capture')):
            result=self.worker.run_once()
        self.assertEqual(result['state'],'dispatched')

    def test_scheduled_csv_artifact_uses_exact_frozen_columns_filters_and_snapshot(self):
        entered=self.stamp-86400+3600
        with self.archive.writer() as db:
            db.executemany('INSERT INTO report_visits VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',[
                ('primary','a'*64,'first','8001',entered,entered+1,entered+4,'00000000000','100','answered',1,3,'caller','observed'),
                ('primary','b'*64,'second','8001',entered+10,entered+11,entered+31,'00000000001','100','answered',1,20,'agent','observed')])
        original=custom(filters={'outcomes':['answered'],'wait_max':5,'talk_max':8})
        plan=self.save(builder_definition=original)
        dispatched=self.worker.run_once();self.assertEqual(dispatched['state'],'dispatched')
        ident=dispatched['export_job_id']
        # Later plan edits and archive versions must not affect this export.
        self.save(ident=plan['id'],builder_definition=custom(columns=['agent'],group_by=['agent'],filters={}))
        with self.archive.writer() as db:db.execute('UPDATE report_visits SET talk_seconds=999 WHERE id=?',('a'*64,))
        worker=ExportWorker(self.jobs,self.archive,authorize=lambda spec:True,
            limits=Limits(min_free_bytes=0,max_load_per_cpu=0),disabled_file=self.disabled)
        self.assertEqual(worker.run_once()['state'],'completed')
        fd,size=self.jobs.open_output(ident,'owner')
        with os.fdopen(fd,'rb') as stream:body=stream.read()
        self.assertEqual(len(body),size)
        rows=list(csv.reader(io.StringIO(body.decode('utf-8-sig'))))
        self.assertEqual(rows[0],['queue','caller','talk_seconds'])
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[1], ["'8001","'00000000000",'3.0'])
        self.assertEqual(self.jobs.get(ident,'owner')['spec']['builder_definition'],definition(original))
