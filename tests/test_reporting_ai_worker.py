"""Worker publication/cancellation/resource boundaries with a fake local engine."""
import json
import os
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from sanequeue.reporting.ai_jobs import AIJobs
from sanequeue.reporting.ai_worker import AIWorker,Deferred
from sanequeue.reporting.store import Archive,Event
from sanequeue.reporting.facts import project_batch


class AIWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.archive=Archive(self.root/'history.db',min_free_bytes=0);self.archive.initialize()
        self.archive.append([Event('cdr','audio',100,'CDR',dict(recordingfile='source.wav',uniqueid='call',src='100',dst='200'))])
        project_batch(self.archive)
        self.store=AIJobs(self.root/'ai.db');self.store.initialize()
        for name in ('source.wav','python','ffmpeg','model','tokens','vad'):(self.root/name).write_bytes(b'private synthetic content')
        self.worker=AIWorker(self.store,self.archive,recording_root=self.root,scratch=self.root/'scratch',
            python=self.root/'python',ffmpeg=self.root/'ffmpeg',model=self.root/'model',tokens=self.root/'tokens',
            vad=self.root/'vad',gate=lambda *args:None)

    def create(self,**kwargs):
        return self.store.create('owner','visit','audio','8001','fa','key',**kwargs)

    def fake_engine(self,command,*args,**kwargs):
        if '--output' in command:
            path=Path(command[command.index('--output')+1])
            path.write_text(json.dumps(dict(text='پیگیری فاکتور پونصد تومان',segments=[dict(start=0,end=1,text='پیگیری')],analysis={})),encoding='utf-8')
        else:
            self.assertIn('-xerror',command)
            self.assertEqual(command[command.index('-max_error_rate')+1],'0')
            Path(command[-1]).write_bytes(b'converted')

    def test_completed_result_is_private_enriched_and_multi_queue_scope_is_preserved(self):
        job=self.create(queues=['8001','8002'])
        self.worker._process=self.fake_engine
        with patch('sanequeue.reporting.ai_worker.ownership',return_value=('8001','8002')):
            result=self.worker.run_once()
        self.assertEqual(result['state'],'completed',result)
        stored=self.store.get(job['id'],'owner')
        self.assertEqual(stored['result']['normalized_text'],'پیگیری فاکتور 500 تومان')
        self.assertFalse(stored['result']['analysis']['automated_decision'])
        self.assertEqual(list((self.root/'scratch').iterdir()),[])
        self.assertIsNone(self.store.get(job['id'],'other'))

    def test_unowned_queue_and_cancelled_work_never_publish_text(self):
        job=self.create();self.worker._process=self.fake_engine
        with patch('sanequeue.reporting.ai_worker.ownership',return_value=('8002',)):
            self.assertEqual(self.worker.run_once()['reason'],'source_not_ready')
        self.assertIsNone(self.store.get(job['id'],'owner')['result'])
        second=self.store.create('owner','visit','audio','8001','fa','key2')
        def cancel(command,*args,**kwargs):
            self.fake_engine(command,*args,**kwargs);self.store.cancel(second['id'],'owner')
        self.worker._process=cancel
        with patch('sanequeue.reporting.ai_worker.ownership',return_value=('8001',)):
            self.assertEqual(self.worker.run_once()['state'],'cancelled')
        self.assertIsNone(self.store.get(second['id'],'owner')['result'])
        self.assertEqual(list((self.root/'scratch').iterdir()),[])

    def test_busy_server_does_not_consume_a_job_attempt(self):
        job=self.create()
        def busy(*args):raise Deferred('system_busy')
        self.worker.gate=busy
        self.assertEqual(self.worker.run_once()['state'],'deferred')
        stored=self.store.get(job['id'],'owner')
        self.assertEqual((stored['state'],stored['attempts']),('queued',0))

    @unittest.skipIf(os.name=='nt','Unix venv symlink semantics')
    def test_virtual_environment_entrypoint_is_not_replaced_by_system_interpreter(self):
        entry=self.root/'venv-python';entry.symlink_to(self.root/'python')
        worker=AIWorker(self.store,self.archive,recording_root=self.root,scratch=self.root/'scratch',
            python=entry,ffmpeg=self.root/'ffmpeg',model=self.root/'model',tokens=self.root/'tokens',
            vad=self.root/'vad',gate=lambda *args:None)
        self.assertEqual(worker.python,entry)
        self.assertNotEqual(worker.python,entry.resolve())


if __name__=='__main__':unittest.main()
