"""Synthetic transcripts only: private leases, strict citations and local transport."""
from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

from sanequeue.reporting.ai_jobs import AIJobs,AIConflict,AIUnavailable
from sanequeue.reporting.generative_jobs import GenerativeJobs
from sanequeue.reporting.generative_worker import GenerativeWorker,local_authorizer
from sanequeue.reporting.store import Archive
from sanequeue.reporting.text_generation import (configuration,transcript,assemble,validate_result,generate,canonical,GenerationFailure)


TEXT='Synthetic customer asks about an invoice. Agent offers a review.'
ANSWER=dict(summary=[dict(text='An invoice review was discussed.',evidence=['s1'])],themes=[dict(text='Invoice query',evidence=['s1'])],suggestions=[dict(text='A human may verify the invoice.',evidence=['s1'])])
def config(port=19411):return dict(enabled=True,allow_local_transcript_processing=True,endpoint='http://127.0.0.1:'+str(port)+'/v1/chat/completions',model='synthetic-test',timeout_seconds=5,max_tokens=512)
def write(path,value):path.write_text(canonical(value),encoding='utf-8');path.chmod(0o600)


@contextmanager
def provider(mode='good'):
    requests=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])));requests.append((self.path,payload))
            answer=copy.deepcopy(ANSWER)
            if mode=='bad_reference':answer['summary'][0]['evidence']=['s999']
            content=json.dumps(dict(choices=[dict(finish_reason='length' if mode=='truncated' else 'stop',message={'content':canonical(answer)})])).encode()
            self.send_response(302 if mode=='redirect' else 200)
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(65537 if mode=='oversize' else len(content)))
            if mode=='redirect':self.send_header('Location','http://example.invalid/private')
            self.end_headers()
            try:self.wfile.write(content)
            except (BrokenPipeError,ConnectionResetError):pass
    try:server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    except PermissionError as error:raise unittest.SkipTest('Loopback bind unavailable in this runtime') from error
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield server.server_port,requests
    finally:server.shutdown();server.server_close();thread.join(timeout=2)


class GenerativeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.sources=AIJobs(self.root/'asr.sqlite3');self.sources.initialize();self.jobs=GenerativeJobs(self.root/'generative.sqlite3');self.jobs.initialize()
        source=self.sources.create('alice','a'*64,'recording-test','8001','en','source')
        self.sources.claim('asr-worker')
        self.sources.complete(source['id'],'asr-worker',dict(text=TEXT,segments=[dict(start=1,end=9,text=TEXT)]))
        self.source=self.sources.get(source['id'],'alice');self.archive=Archive(self.root/'archive.db',min_free_bytes=0);self.archive.initialize()
        self.settings=self.root/'generative.json';write(self.settings,config())
    def create(self,**extra):return self.jobs.create('alice',self.source,extra.get('queues',['8001']),extra.get('language','en'),extra.get('key','one'))
    def worker(self,**options):
        return GenerativeWorker(self.jobs,self.sources,self.archive,config=self.settings,scratch=self.root/'scratch',gate=lambda *args:None,
            authorize=options.pop('authorize',lambda spec:True),proof=options.pop('proof',lambda *args:['8001']),**options)
    def final(self,job):return assemble(copy.deepcopy(ANSWER),transcript(self.source),job['spec'],configuration(config()))
    def test_opt_in_and_strict_loopback_no_ssrf_or_header_injection(self):
        for endpoint in ('http://example.com:8080/v1/chat/completions','http://127.0.0.1:80/v1/chat/completions','http://127.0.0.1.evil:8080/v1/chat/completions','http://user@127.0.0.1:8080/v1/chat/completions','http://127.0.0.1:8080/v1/chat/completions?url=private','http://127.0.0.1:8080/other','https://127.0.0.1:8080/v1/chat/completions'):
            with self.subTest(endpoint=endpoint),self.assertRaises(GenerationFailure):configuration({**config(),'endpoint':endpoint})
        for change in ({'enabled':False},{'allow_local_transcript_processing':False},{'api_key':'bad\r\nvalue'},{'timeout_seconds':31},{'max_tokens':True}):
            with self.assertRaises(GenerationFailure):configuration({**config(),**change})
        self.assertEqual(configuration(config())['host'],'127.0.0.1')
    def test_pinned_source_and_private_idempotency_owner_versions(self):
        made=self.create();again=self.create();self.assertEqual(made['id'],again['id'])
        self.assertIsNone(self.jobs.get(made['id'],'bob'));self.assertEqual(self.jobs.list('bob'),[])
        with self.assertRaises(AIConflict):self.create(language='fa')
        original=copy.deepcopy(self.source);original['result']['text']='Changed transcript'
        with self.assertRaises(GenerationFailure):transcript(original)
        self.assertNotIn(TEXT,canonical(made['spec']))
        with self.assertRaises(AIUnavailable):GenerativeJobs(self.sources.path).initialize()
        with self.assertRaises(ValueError):GenerativeWorker(self.sources,self.sources,self.archive,config=self.settings,scratch=self.root/'bad')
    def test_result_refs_and_flags_are_validated_and_list_does_not_read_result(self):
        job=self.create();self.jobs.claim('worker');value=self.final(job)
        self.assertEqual(value['evidence']['s1']['text'],TEXT);self.assertTrue(value['machine_generated']);self.assertFalse(value['automated_decision'])
        bad=copy.deepcopy(value);bad['analysis']['summary'][0]['evidence']=['s2']
        with self.assertRaises(GenerationFailure):self.jobs.complete(job['id'],'worker',bad)
        self.assertTrue(self.jobs.complete(job['id'],'worker',value));self.assertFalse(self.jobs.cancel(job['id'],'alice'))
        self.assertIsNone(self.jobs.list('alice')[0]['result']);self.assertEqual(self.jobs.get(job['id'],'alice')['result'],value)
        forged=copy.deepcopy(value);forged['evidence']['s1']['text']='Invented quotation'
        with self.assertRaises(GenerationFailure):validate_result(forged,job['spec'],transcript(self.source))
    def test_limits_and_missing_evidence_are_not_silently_truncated(self):
        bad=copy.deepcopy(self.source);bad['result']['text']='x'*16001
        with self.assertRaises(GenerationFailure):transcript(bad)
        bad=copy.deepcopy(ANSWER);bad['summary'][0]['evidence']=[]
        with self.assertRaises(GenerationFailure):assemble(bad,transcript(self.source),self.create()['spec'],configuration(config()))
        bad=copy.deepcopy(ANSWER);bad['decisions']=['fire someone']
        with self.assertRaises(GenerationFailure):assemble(bad,transcript(self.source),self.create()['spec'],configuration(config()))
    def test_http_protocol_runs_only_synthetic_loopback_and_rejects_redirect_truncation(self):
        job=self.create();prepared=transcript(self.source)
        with provider() as (port,requests):
            value=generate(prepared,job['spec'],configuration(config(port)))
            self.assertEqual(value['analysis']['summary'][0]['evidence'],['s1']);self.assertEqual(len(requests),1)
            self.assertEqual(requests[0][0],'/v1/chat/completions');self.assertFalse(requests[0][1]['stream'])
            self.assertNotIn('alice',canonical(requests[0][1]));self.assertNotIn('recording-test',canonical(requests[0][1]))
        for mode in ('redirect','oversize','truncated','bad_reference'):
            with provider(mode) as (port,requests),self.assertRaises(GenerationFailure):generate(prepared,job['spec'],configuration(config(port)))
    def test_real_worker_child_roundtrip_against_synthetic_provider(self):
        job=self.create()
        with provider() as (port,requests):
            write(self.settings,config(port));result=self.worker().run_once()
        self.assertEqual(result['state'],'completed',result);stored=self.jobs.get(job['id'],'alice')
        self.assertEqual(stored['result']['source']['job_id'],self.source['id']);self.assertEqual(len(requests),1)
        self.assertEqual(list((self.root/'scratch').iterdir()),[])
    def test_revocation_cancel_and_source_change_after_generation_do_not_publish(self):
        for case in ('revoke','cancel','change'):
            with self.subTest(case=case):
                granted=[True];job=self.create(key=case);worker=self.worker(authorize=lambda spec:granted[0])
                def finish(command,current,token,deadline):
                    write(Path(command[command.index('--output')+1]),self.final(job))
                    if case=='revoke':granted[0]=False
                    elif case=='cancel':self.jobs.cancel(job['id'],'alice')
                    else:
                        changed=copy.deepcopy(self.source['result']);changed['text']='Other';changed['segments']=[dict(start=1,end=9,text='Other')]
                        with self.sources._db(write=True) as db:db.execute('UPDATE ai_jobs SET result=? WHERE id=?',(canonical(changed),self.source['id']))
                worker._process=finish;result=worker.run_once();stored=self.jobs.get(job['id'],'alice')
                self.assertIn(result['state'],('failed','cancelled'));self.assertIsNone(stored['result'])
    def test_default_authorization_and_unknown_scope_prevent_request(self):
        job=self.create();worker=self.worker(authorize=lambda spec:False)
        with patch.object(worker,'_process') as send:self.assertEqual(worker.run_once()['reason'],'access_revoked');send.assert_not_called()
        job=self.create(key='unproven');worker=self.worker(proof=lambda *args:False)
        with patch.object(worker,'_process') as send:self.assertEqual(worker.run_once()['state'],'queued');send.assert_not_called()
        self.assertEqual(self.jobs.get(job['id'],'alice')['attempts'],0)
    def test_lease_recovery_and_cancelled_result_cannot_commit(self):
        job=self.create();self.jobs.claim('old')
        with self.jobs._db(write=True) as db:db.execute('UPDATE ai_jobs SET lease_until=0 WHERE id=?',(job['id'],))
        recovered=self.jobs.claim('new');self.assertEqual(recovered['id'],job['id']);self.assertEqual(recovered['attempts'],2)
        self.assertFalse(self.jobs.complete(job['id'],'old',self.final(job)))
        self.assertTrue(self.jobs.cancel(job['id'],'alice'));self.assertFalse(self.jobs.complete(job['id'],'new',self.final(job)))
    def test_current_local_role_menus_and_all_queue_grants_are_reloaded(self):
        users=self.root/'accounts.json';policies=self.root/'policies.json'
        account=dict(role='supervisor',phone='PJSIP/100',menus=['reports','audit'],password_hash='pbkdf2:sha256:test')
        policy=dict(version=1,queues={'8001':{}},supervisors={'alice':dict(queues=['8001'],actions=['view','recording_play','caller_details'])})
        write(users,{'alice':account});write(policies,policy);authorize=local_authorizer(users,policies);spec=self.create()['spec']
        self.assertTrue(authorize(spec));self.assertFalse(authorize({**spec,'queues':['8001','8002']}))
        write(users,{'alice':{**account,'menus':['reports']}});self.assertFalse(authorize(spec))
        write(users,{'alice':account});policy['supervisors']['alice']['actions'].remove('recording_play');write(policies,policy)
        self.assertFalse(authorize(spec));users.unlink();self.assertFalse(authorize(spec))
    def test_process_timeout_terminates_real_child_instead_of_publishing(self):
        from sanequeue.reporting.ai_worker import ProcessingFailure
        job=self.create();claimed=self.jobs.claim('worker');worker=self.worker();processes=[];start=time.monotonic();original=subprocess.Popen
        def spawn(*args,**kwargs):
            child=original(*args,**kwargs);processes.append(child);return child
        with patch('sanequeue.reporting.generative_worker.subprocess.Popen',side_effect=spawn),self.assertRaises(ProcessingFailure):
            worker._process([sys.executable,'-c','import time;time.sleep(10)'],claimed,'worker',time.monotonic()+.2)
        self.assertLess(time.monotonic()-start,8);self.assertIsNotNone(processes[0].poll())
    def test_config_opt_out_and_owner_quota(self):
        job=self.create();worker=self.worker()
        def finish(command,current,token,deadline):
            write(Path(command[command.index('--output')+1]),self.final(job));write(self.settings,{**config(),'enabled':False})
        worker._process=finish;self.assertEqual(worker.run_once()['state'],'failed');self.assertIsNone(self.jobs.get(job['id'],'alice')['result'])
        for key in ('pending1','pending2','pending3'):self.create(key=key)
        with self.assertRaises(AIConflict):self.create(key='over-quota')


if __name__=='__main__':unittest.main()
