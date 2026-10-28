from contextlib import closing
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from sanequeue.reporting.ai_jobs import AIJobs
from sanequeue.reporting.transcript_search import expression,normalize

class TranscriptSearchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=AIJobs(Path(self.temp.name)/'ai.db');self.store.initialize()
    def complete(self,key='one',owner='owner',text='مشتري گفت شماره ۰۹۱۲ و پیگیری',queue='8001'):
        job=self.store.create(owner,'visit','recording',queue,'fa',key)
        self.store.claim('worker')
        self.assertTrue(self.store.complete(job['id'],'worker',dict(text=text,normalized_text=text,segments=[])))
        return job
    def test_literal_tokens_normalization_and_no_operator_injection(self):
        self.assertEqual(normalize('ي ك ۰۹١٢'),'ی ک 0912')
        self.assertEqual(expression('hello OR world*'),'"hello" AND "or" AND "world"')
        self.complete()
        self.assertEqual(len(self.store.search_text('owner','مشتری 0912')),1)
        self.assertEqual(self.store.search_text('owner','مشت'),[])
        self.assertEqual(self.store.search_text('owner','شماره OR absent'),[])
        for value in ('', '***', 'a '*13,'x'*257,None):
            with self.subTest(value=value),self.assertRaises(ValueError):self.store.search_text('owner',value)
    def test_owner_pbx_and_uncompleted_results_are_private(self):
        job=self.complete();self.complete('two','another')
        self.assertEqual([r['job']['id'] for r in self.store.search_text('owner','شماره')],[job['id']])
        self.assertEqual(AIJobs(self.store.path,pbx='other').search_text('owner','شماره'),[])
        queued=self.store.create('owner','visit','recording','8001','fa','queued')
        self.assertNotIn(queued['id'],[r['job']['id'] for r in self.store.search_text('owner','شماره')])
        self.assertIsNone(self.store.search_text('owner','شماره')[0]['job']['result'])
    def test_bounded_recoverable_legacy_migration_does_not_duplicate(self):
        job=self.complete()
        with closing(sqlite3.connect(self.store.path)) as db:
            db.execute('DELETE FROM ai_text_search');db.execute('DELETE FROM ai_text_indexed');db.commit()
        self.assertEqual(self.store.search_text('owner','شماره'),[])
        self.assertEqual(self.store.index_legacy_texts(limit=1),1)
        self.assertEqual(self.store.index_legacy_texts(limit=1),0)
        self.assertEqual(self.store.search_text('owner','شماره')[0]['job']['id'],job['id'])
        self.complete('new');self.store.index_legacy_texts(limit=1)
        self.assertEqual(len(self.store.search_text('owner','شماره')),2)
        with self.assertRaises(ValueError):self.store.index_legacy_texts(limit=100)
    def test_missing_optional_fts_does_not_break_speech_jobs(self):
        from sanequeue.reporting.ai_jobs import AIUnavailable
        with closing(sqlite3.connect(self.store.path)) as db:
            db.execute('DROP TABLE ai_text_search');db.commit()
        job=self.complete();self.assertEqual(self.store.get(job['id'],'owner')['state'],'completed')
        self.assertEqual(self.store.index_legacy_texts(limit=1),0)
        with self.assertRaises(AIUnavailable):self.store.search_text('owner','شماره')

    def test_search_readers_share_deadline_and_interrupt_heavy_queries(self):
        import time
        from sanequeue.reporting.store import Archive,QueryDeadline
        from sanequeue.reporting.transcript_search import DeadlineArchive
        archive=Archive(Path(self.temp.name)/'archive.db',min_free_bytes=0);archive.initialize()
        expired=DeadlineArchive(archive,time.monotonic()-1)
        with self.assertRaises(QueryDeadline):expired.reader()
        bounded=DeadlineArchive(archive,time.monotonic()+.01)
        with self.assertRaises(QueryDeadline):
            with bounded.reader() as db:
                db.execute('WITH RECURSIVE n(v) AS (VALUES(0) UNION ALL SELECT v+1 FROM n WHERE v<100000000) SELECT SUM(v) FROM n').fetchone()

    def test_index_and_completion_are_atomic(self):
        from unittest.mock import patch
        job=self.store.create('owner','visit','recording','8001','fa','one');self.store.claim('worker')
        with patch.object(self.store,'_index_text',side_effect=RuntimeError('failed')):
            with self.assertRaises(RuntimeError):self.store.complete(job['id'],'worker',dict(text='hello',segments=[]))
        self.assertEqual(self.store.get(job['id'],'owner')['state'],'running')
        self.assertEqual(self.store.search_text('owner','hello'),[])

if __name__=='__main__':unittest.main()


class TranscriptSearchAPITests(unittest.TestCase):
    def setUp(self):
        from tests.test_reporting_queries import ReportTests
        from sanequeue.reporting.store import Event
        from sanequeue.reporting.facts import project_batch
        self.case=ReportTests();self.case.setUp();self.addCleanup(self.case.doCleanups);self.case.seed()
        self.client=self.case.client(menus=('reports','audit'),details=True)
        ident=self.client.get('/api/history/visits'+self.case.dates).json['rows'][0]['id']
        self.case.archive.append([Event('cdr','audio',self.case.stamp,'CDR',dict(uniqueid='a',linkedid='a',recordingfile='private.wav',duration=40,billsec=30,disposition='ANSWERED'))])
        project_batch(self.case.archive)
        store=AIJobs(self.case.archive.path.parent/'ai-jobs.sqlite3')
        self.job=store.create('test',ident,'audio','8001','fa','one');store.claim('worker')
        store.complete(self.job['id'],'worker',dict(text='مشتری پیگیری ویژه',segments=[]))
        self.path='/api/history/transcripts/search?q='+__import__('urllib.parse',fromlist=['quote']).quote('پیگیری')
    def test_each_result_rechecks_current_audio_number_menu_and_queue_permissions(self):
        from unittest.mock import patch
        with patch('sanequeue.api.reports.recording_ownership',return_value=('8001',)):
            response=self.client.get(self.path)
            self.assertEqual(response.status_code,200,response.json)
            self.assertEqual([row['id'] for row in response.json['rows']],[self.job['id']])
            self.assertNotIn('total',response.json)
            self.assertEqual(response.headers['Cache-Control'],'private, no-store')
            for capability in ('recording_play','caller_details','view'):
                client=self.case.client(menus=('reports','audit'),details=True,denied=(capability,))
                self.assertEqual(client.get(self.path).json['rows'],[])
            for client in (self.case.client(menus=('reports',),details=True),self.case.client(role='agent',menus=('reports','audit'),details=True)):
                self.assertEqual(client.get(self.path).status_code,403)
        with patch('sanequeue.api.reports.recording_ownership',return_value=('8001','8002')):
            self.assertEqual(self.client.get(self.path).json['rows'],[])
        self.assertEqual(self.client.get('/api/history/transcripts/search?q=***').status_code,400)
