import math
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from sanequeue.reporting.ai_jobs import AIJobs,AIConflict,AIUnavailable
from sanequeue.reporting.store import QueryDeadline


class AIJobTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'ai.db';self.store=AIJobs(self.path);self.store.initialize()
        self.clock=patch('sanequeue.reporting.ai_jobs.time.time',return_value=100)
        self.now=self.clock.start();self.addCleanup(self.clock.stop)

    def job(self,key='one',owner='owner',**changes):
        spec=dict(owner=owner,visit_id='visit-id',recording_id='generation:recording-id',queue='8001',
                  language='fa',request_key=key)
        spec.update(changes);return self.store.create(**spec)

    def result(self,**changes):
        result=dict(text='<b>متن فارسی</b>',normalized_text='متن فارسی',
                    segments=[dict(start=0,end=10,text='متن فارسی')],analysis=dict(summary='Plain text',sentiment=.5))
        result.update(changes);return result

    def test_idempotency_owner_isolation_and_immutable_source(self):
        first=self.job();self.assertEqual(first['id'],self.job()['id'])
        with self.assertRaises(AIConflict):self.job(queue='8002')
        other=self.job(owner='other');self.assertNotEqual(first['id'],other['id'])
        self.assertIsNone(self.store.get(first['id'],'other'))
        self.assertEqual([j['id'] for j in self.store.list('owner')],[first['id']])
        db=sqlite3.connect(self.path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):db.execute("UPDATE ai_jobs SET spec='{}'")
        finally:db.close()

    def test_claim_progress_complete_durable_plain_text_and_no_worker_public(self):
        job=self.job();claimed=self.store.claim('attempt-a')
        self.assertEqual(claimed['id'],job['id']);self.assertEqual(claimed['attempts'],1)
        self.assertTrue(self.store.update_progress(job['id'],'attempt-a',40))
        self.assertFalse(self.store.update_progress(job['id'],'attempt-a',30))
        self.assertFalse(self.store.complete(job['id'],'wrong',self.result()))
        self.assertTrue(self.store.complete(job['id'],'attempt-a',self.result()))
        fresh=AIJobs(self.path).get(job['id'],'owner')
        self.assertEqual(fresh['state'],'completed');self.assertEqual(fresh['progress'],100)
        self.assertEqual(fresh['result']['text'],'<b>متن فارسی</b>')
        self.assertIsNone(self.store.list('owner')[0]['result'])
        self.assertNotIn('worker',fresh);self.assertNotIn('lease_until',fresh)
        self.assertFalse(self.store.cancel(job['id'],'owner'))
        self.assertFalse(self.store.fail(job['id'],'attempt-a','processing_failed'))

    def test_cancel_queued_and_running_prevents_result_publication(self):
        queued=self.job();self.assertFalse(self.store.cancel(queued['id'],'other'))
        self.assertTrue(self.store.cancel(queued['id'],'owner'));self.assertIsNone(self.store.claim('worker'))
        running=self.job('two');self.store.claim('attempt-b')
        self.assertTrue(self.store.cancel(running['id'],'owner'))
        self.assertFalse(self.store.complete(running['id'],'attempt-b',self.result()))
        self.assertFalse(self.store.update_progress(running['id'],'attempt-b',90))
        stored=self.store.get(running['id'],'owner');self.assertEqual(stored['state'],'cancelled');self.assertIsNone(stored['result'])

    def test_expired_leases_retry_three_times_and_fence_old_attempts(self):
        job=self.job();self.store.claim('attempt-a',lease=5)
        self.now.return_value=106
        self.assertFalse(self.store.complete(job['id'],'attempt-a',self.result()))
        two=self.store.claim('attempt-b',lease=5);self.assertEqual(two['attempts'],2)
        self.assertFalse(self.store.update_progress(job['id'],'attempt-a',50))
        self.now.return_value=112
        three=self.store.claim('attempt-c',lease=5);self.assertEqual(three['attempts'],3)
        self.now.return_value=118;self.assertIsNone(self.store.claim('attempt-d'))
        final=self.store.get(job['id'],'owner');self.assertEqual(final['state'],'failed');self.assertEqual(final['error'],'lease_expired')
        self.assertIsNone(final['result'])

    def test_defer_does_not_consume_attempt_and_obeys_available_time(self):
        job=self.job();self.store.claim('attempt-a')
        self.assertTrue(self.store.defer(job['id'],'attempt-a','system_busy',delay=30))
        deferred=self.store.get(job['id'],'owner');self.assertEqual(deferred['attempts'],0);self.assertEqual(deferred['state'],'queued')
        self.assertIsNone(self.store.claim('attempt-b'))
        self.now.return_value=130
        self.assertEqual(self.store.claim('attempt-c')['attempts'],1)

    def test_quotas_are_global_and_owner_pending_only(self):
        jobs=[self.job(str(index)) for index in range(3)]
        with self.assertRaises(AIConflict):self.job('four')
        self.assertEqual(self.job('0')['id'],jobs[0]['id'])
        self.store.cancel(jobs[0]['id'],'owner');self.job('replacement')
        for index in range(7):self.job('other'+str(index),owner='other'+str(index))
        with self.assertRaises(AIConflict):self.job('eleven',owner='new')
        other=AIJobs(self.path,pbx='secondary')
        with self.assertRaises(AIConflict):other.create('new','visit','recording','8001','en','key')

    def test_result_limits_offsets_nonfinite_and_booleans(self):
        job=self.job(maximum_seconds=20);self.store.claim('attempt-a')
        invalid=[self.result(segments=[dict(start=False,end=1,text='bad')]),
                 self.result(segments=[dict(start=2,end=1,text='bad')]),
                 self.result(segments=[dict(start=0,end=21,text='bad')]),
                 self.result(segments=[dict(start=0,end=math.inf,text='bad')]),
                 self.result(text='x'*(1024*1024+1)),self.result(segments=[dict(start=0,end=1,text='x')]*10001),
                 self.result(analysis={'x':math.nan}),self.result(analysis={'x':object()}),
                 self.result(segments=[dict(start=1,end=2,text='a'),dict(start=0,end=1,text='b')]),
                 self.result(text='x'*800000,normalized_text='x'*800000,analysis={'x':'x'*800000})]
        for value in invalid:
            with self.subTest(kind=list(value)),self.assertRaises(ValueError):self.store.complete(job['id'],'attempt-a',value)
            self.assertIsNone(self.store.get(job['id'],'owner')['result'])
        self.assertTrue(self.store.complete(job['id'],'attempt-a',self.result()))

    def test_invalid_sources_languages_reason_codes_and_numeric_types(self):
        for changes in (dict(recording_id='/private/audio.wav'),dict(visit_id='https://example.test'),
                        dict(language='xx'),dict(maximum_seconds=True),dict(maximum_seconds=1801)):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.job(**changes)
        job=self.job();self.store.claim('attempt-a')
        with self.assertRaises(ValueError):self.store.fail(job['id'],'attempt-a','secret=/private/path')
        self.assertTrue(self.store.fail(job['id'],'attempt-a','model_unavailable'))
        self.assertEqual(self.store.get(job['id'],'owner')['error'],'model_unavailable')

    def test_storage_permissions_busy_and_missing_do_not_leak_errors(self):
        missing=AIJobs(Path(self.temp.name)/'missing.db')
        with self.assertRaises(AIUnavailable):missing.list('owner')
        self.assertFalse(missing.path.exists())
        if os.name!='nt':self.assertEqual(self.path.stat().st_mode&0o777,0o600)
        db=sqlite3.connect(self.path);db.execute('BEGIN IMMEDIATE')
        try:
            with self.assertRaisesRegex(AIUnavailable,'^ai_job_store_unavailable$'):self.job()
        finally:db.rollback();db.close()

    def test_reader_deadline_and_owner_list_cap(self):
        # Completed/cancelled jobs do not consume the pending quota.
        for index in range(105):
            job=self.job(str(index));self.store.cancel(job['id'],'owner')
        self.assertEqual(len(self.store.list('owner',999)),100)
        with patch('sanequeue.reporting.ai_jobs.time.monotonic',side_effect=[0,1]),self.assertRaises(QueryDeadline):
            self.store.list('owner')


if __name__=='__main__':unittest.main()
