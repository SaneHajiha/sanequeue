"""Single opt-in text-analysis worker; inference lives in an operator-run service.

Only the killable child contacts an explicitly approved loopback endpoint.
CPU/memory limits here do not limit the separate model service: operators must
isolate and resource-limit it independently before enabling processing.
"""
import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import uuid

from .ai_jobs import AIJobs
from .generative_jobs import GenerativeJobs
from .ai_worker import resource_gate,Deferred,Cancelled,ProcessingFailure
from .export_jobs import _worker_lock,_local_json
from .recording_scope import ownership
from .store import Archive
from .text_generation import (private_json,configuration,canonical,transcript,validate_result,GenerationFailure,MAX_INPUT,MAX_RESULT)


def local_authorizer(accounts,policies):
    """Fresh account, role, menus and all frozen queue grants; no grant cache."""
    from qpanel.local_accounts import validate_identity
    from qpanel.queue_policies import validate_config
    from sanequeue.security.permissions import sections_for,validate_sections,ROLE_ACTIONS
    def check(spec):
        try:
            users=_local_json(accounts)
            if not isinstance(users,dict) or len(users)>100:return False
            for name,user in users.items():
                if not isinstance(user,dict):return False
                validate_identity(name,user.get('role'),user.get('phone',''));validate_sections(user['role'],user.get('menus'))
                if not str(user.get('password_hash','')).startswith('pbkdf2:sha256:'):return False
            user=users.get(spec['owner']);role=(user or {}).get('role')
            if role not in ('admin','supervisor') or not {'reports','audit'}.issubset(sections_for(role,user)):return False
            raw=_local_json(policies)
            if not isinstance(raw,dict) or type(raw.get('version')) is not int or raw['version']!=1 or not {'queues','supervisors'}.issubset(raw):return False
            policy=validate_config(raw);grant=policy['supervisors'].get(spec['owner'],{})
            return bool(spec['queues']) and all(cap in ROLE_ACTIONS[role] and (role=='admin' or queue in grant.get('queues',[]) and cap in grant.get('actions',[]))
                for queue in spec['queues'] for cap in ('view','recording_play','caller_details'))
        except Exception:return False
    return check


class GenerativeWorker:
    def __init__(self,store,sources,archive,*,config,scratch,authorize=None,disabled_file=None,gate=resource_gate,python=None,timeout=45,proof=None):
        self.store=store;self.sources=sources;self.archive=archive;self.config=Path(config);self.scratch=Path(scratch)
        self.authorize=authorize or (lambda spec:False);self.disabled_file=disabled_file;self.gate=gate
        self.python=Path(python or sys.executable).absolute();self.timeout=float(timeout);self.proof=proof or ownership
        if store.path.resolve() in (sources.path.resolve(),archive.path.resolve()):raise ValueError('analysis_stores_must_be_separate')
        if not 1<=self.timeout<=60:raise ValueError('invalid_analysis_timeout')
        self._next=0
    def _source(self,spec):
        source=self.sources.get(spec['source_job_id'],spec['owner'])
        prepared=transcript(source)
        if prepared['sha256']!=spec['transcript_sha256'] or prepared['spec_sha256']!=spec['source_spec_sha256']:raise ProcessingFailure('source_unavailable')
        return prepared
    def _check(self,job,token,deadline,progress,force=False):
        now=time.monotonic()
        if now>=deadline:raise ProcessingFailure('timeout')
        if not force and now<self._next:return
        self.gate(self.scratch,self.disabled_file)
        configuration(private_json(self.config,16384))
        spec=job['spec']
        if spec['pbx']!=self.archive.pbx or not self.authorize(spec):raise ProcessingFailure('access_revoked')
        bounded=Archive(self.archive.path,pbx=self.archive.pbx,read_seconds=min(1,max(.001,deadline-now)))
        proof=self.proof(bounded,spec['recording_id'])
        if not proof:raise Deferred('source_not_ready')
        if not set(proof).issubset(spec['queues']):raise ProcessingFailure('access_revoked')
        if not self.store.update_progress(job['id'],token,progress,lease=90):raise Cancelled('cancelled')
        self._next=time.monotonic()+1
    def _process(self,command,job,token,deadline):
        process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,
            env=dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1'))
        try:
            while process.poll() is None:self._check(job,token,deadline,50);time.sleep(.25)
            if process.returncode:raise ProcessingFailure('processing_failed')
        finally:
            if process.poll() is None:
                if os.name=='nt':process.terminate()
                else:
                    try:os.killpg(process.pid,signal.SIGTERM)
                    except ProcessLookupError:pass
                try:process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    if os.name=='nt':process.kill()
                    else:
                        try:os.killpg(process.pid,signal.SIGKILL)
                        except ProcessLookupError:pass
                    process.wait(timeout=2)
    def run_once(self):
        if self.scratch.is_symlink():raise ValueError('analysis_scratch_symlink')
        self.scratch.mkdir(mode=0o700,parents=True,exist_ok=True)
        if os.name!='nt' and self.scratch.stat().st_mode&0o077:raise ValueError('analysis_scratch_permissions')
        with _worker_lock(str(self.store.path)+'.worker.lock') as acquired:
            if not acquired:return dict(state='busy')
            try:self.gate(self.scratch,self.disabled_file)
            except Deferred as error:return dict(state='deferred',reason=str(error))
            token=uuid.uuid4().hex;job=self.store.claim(token,lease=90)
            if job is None:return dict(state='idle')
            deadline=time.monotonic()+self.timeout;self._next=0
            try:
                configuration(private_json(self.config,16384))
                if not self.python.is_file() or not self.python.resolve().is_file():raise ProcessingFailure('model_unavailable')
                self._check(job,token,deadline,5,True);prepared=self._source(job['spec'])
                payload=canonical(dict(spec=job['spec'],prepared={k:v for k,v in prepared.items() if k!='text'}))
                if len(payload.encode())>MAX_INPUT:raise ProcessingFailure('resource_limit')
                with tempfile.TemporaryDirectory(prefix='text-',dir=self.scratch) as folder:
                    folder=Path(folder);source=folder/'input.json';output=folder/'output.json'
                    fd=os.open(source,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                    with os.fdopen(fd,'w',encoding='utf-8') as stream:stream.write(payload)
                    self._check(job,token,deadline,10,True)
                    self._process([str(self.python),'-m','sanequeue.reporting.text_generation','--input',str(source),'--output',str(output),'--config',str(self.config)],job,token,deadline)
                    value=private_json(output,MAX_RESULT);current=self._source(job['spec']);validate_result(value,job['spec'],current)
                    self._check(job,token,deadline,95,True)
                    if not self.store.complete(job['id'],token,value):raise Cancelled('cancelled')
                return dict(id=job['id'],state='completed')
            except Deferred as error:
                self.store.defer(job['id'],token,str(error));return dict(id=job['id'],state='queued',reason=str(error))
            except Cancelled:return dict(id=job['id'],state='cancelled')
            except Exception as error:
                reason=str(error) if isinstance(error,(ProcessingFailure,GenerationFailure)) else 'processing_failed'
                if reason not in ('model_unavailable','source_unavailable','resource_limit','access_revoked','timeout','result_invalid'):reason='processing_failed'
                self.store.fail(job['id'],token,reason);return dict(id=job['id'],state='failed',reason=reason)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('jobs','sources','archive','config','scratch','accounts','policies'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--pbx',default='primary');parser.add_argument('--once',action='store_true');parser.add_argument('--disabled-file',default=os.getenv('SANEQUEUE_DISABLE_FILE','/var/lib/sanequeue/module.disabled'));args=parser.parse_args()
    if Path(args.jobs).resolve() in (Path(args.sources).resolve(),Path(args.archive).resolve()):parser.error('jobs must use a separate private database')
    store=GenerativeJobs(args.jobs,pbx=args.pbx);store.initialize()
    worker=GenerativeWorker(store,AIJobs(args.sources,pbx=args.pbx),Archive(args.archive,pbx=args.pbx),config=args.config,scratch=args.scratch,
        authorize=local_authorizer(args.accounts,args.policies),disabled_file=args.disabled_file)
    while True:
        outcome=worker.run_once()
        if args.once:break
        if outcome['state'] in ('idle','busy','deferred','queued'):time.sleep(5)


if __name__=='__main__':main()
