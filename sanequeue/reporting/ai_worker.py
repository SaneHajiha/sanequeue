"""Opt-in CPU-only recording jobs, isolated from HTTP and telephony workers."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
from zoneinfo import ZoneInfo

from .ai_jobs import AIJobs
from .audio import open_recording
from .export_jobs import _worker_lock
from .recording_scope import ownership
from .store import Archive


class Deferred(RuntimeError):pass
class Cancelled(RuntimeError):pass
class ProcessingFailure(RuntimeError):pass


def resource_gate(path,disabled_file=None):
    if disabled_file and Path(disabled_file).exists():raise Deferred('module_disabled')
    if shutil.disk_usage(path).free<512*1024*1024:raise Deferred('disk_pressure')
    if hasattr(os,'getloadavg') and os.getloadavg()[0]>max(1,os.cpu_count() or 1)*.5:
        raise Deferred('system_busy')
    mem=Path('/proc/meminfo')
    if mem.exists():
        available=next((int(line.split()[1])*1024 for line in mem.read_text().splitlines() if line.startswith('MemAvailable:')),0)
        if available<1024*1024*1024:raise Deferred('system_busy')


class AIWorker:
    def __init__(self,store,archive,*,recording_root,scratch,python,ffmpeg,model,tokens,vad,
                 disabled_file=None,timeout=600,gate=resource_gate):
        self.store=store;self.archive=archive;self.recording_root=Path(recording_root)
        # Keep the lexical venv entry point: executing its resolved system
        # interpreter would lose pyvenv.cfg and the isolated ASR dependencies.
        self.scratch=Path(scratch);self.python=Path(python).absolute();self.ffmpeg=Path(ffmpeg)
        self.model=Path(model);self.tokens=Path(tokens);self.vad=Path(vad)
        self.disabled_file=disabled_file;self.timeout=float(timeout);self.gate=gate
        self._next_check=0
        if not 1<=self.timeout<=1800:raise ValueError('invalid_ai_timeout')

    def _check(self,job,worker,deadline,progress):
        now=time.monotonic()
        if now>deadline:raise ProcessingFailure('timeout')
        if now<self._next_check:return
        self.gate(self.scratch,self.disabled_file)
        if not self.store.update_progress(job['id'],worker,progress,lease=60):raise Cancelled('cancelled')
        self._next_check=now+2

    def _process(self,command,job,worker,deadline,progress,pass_fds=()):
        env=dict(os.environ,OMP_NUM_THREADS='1',OMP_THREAD_LIMIT='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
        process=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            env=env,start_new_session=True,pass_fds=pass_fds)
        try:
            while process.poll() is None:
                self._check(job,worker,deadline,progress);time.sleep(.5)
            if process.returncode:raise ProcessingFailure('processing_failed')
        finally:
            if process.poll() is None:
                try:os.killpg(process.pid,signal.SIGTERM)
                except ProcessLookupError:pass
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    process.wait(timeout=5)

    def run_once(self):
        if self.scratch.is_symlink():raise ValueError('ai_scratch_symlink')
        self.scratch.mkdir(mode=0o700,parents=True,exist_ok=True)
        if os.name!='nt' and self.scratch.stat().st_mode&0o077:raise ValueError('ai_scratch_permissions')
        with _worker_lock(str(self.store.path)+'.worker.lock') as acquired:
            if not acquired:return dict(state='busy')
            try:self.gate(self.scratch,self.disabled_file)
            except Deferred as error:return dict(state='deferred',reason=str(error))
            token=uuid.uuid4().hex;job=self.store.claim(token,lease=60)
            if job is None:return dict(state='idle')
            spec=job['spec'];deadline=time.monotonic()+self.timeout;self._next_check=0
            try:
                if not self.python.is_file() or not self.python.resolve().is_file():
                    raise ProcessingFailure('model_unavailable')
                for asset in (self.ffmpeg,self.model,self.tokens,self.vad):
                    if asset.is_symlink() or not asset.is_file():raise ProcessingFailure('model_unavailable')
                if spec['language']!='fa':raise ProcessingFailure('model_unavailable')
                if spec['pbx']!=self.archive.pbx:raise ProcessingFailure('source_unavailable')
                proof=ownership(self.archive,spec['recording_id'])
                if not proof or not set(proof).issubset(spec.get('queues',[spec['queue']])):
                    raise ProcessingFailure('source_not_ready')
                with self.archive.reader() as db:
                    row=db.execute('SELECT recording,ts FROM report_cdr WHERE pbx=? AND source_key=?',
                        (self.archive.pbx,spec['recording_id'])).fetchone()
                if row is None:raise ProcessingFailure('source_unavailable')
                try:fd,_=open_recording(self.recording_root,row['recording'])
                except FileNotFoundError:
                    if '/' in row['recording']:raise ProcessingFailure('source_unavailable') from None
                    folder=datetime.fromtimestamp(row['ts'],ZoneInfo('Asia/Tehran')).strftime('%Y/%m/%d/')
                    fd,_=open_recording(self.recording_root,folder+row['recording'])
                with tempfile.TemporaryDirectory(prefix='job-',dir=self.scratch) as directory,os.fdopen(fd,'rb') as source:
                    root=Path(directory);original=root/'source-audio';prepared=root/'speech.wav';result_path=root/'result.json'
                    first=os.fstat(source.fileno())
                    if first.st_size>128*1024*1024:raise ProcessingFailure('resource_limit')
                    digest=hashlib.sha256();copied=0
                    with original.open('xb') as target:
                        while chunk:=source.read(65536):
                            copied+=len(chunk)
                            if copied>128*1024*1024:raise ProcessingFailure('resource_limit')
                            self._check(job,token,deadline,5);target.write(chunk);digest.update(chunk)
                    original.chmod(0o600);last=os.fstat(source.fileno())
                    if (first.st_size,first.st_mtime_ns)!=(last.st_size,last.st_mtime_ns):raise ProcessingFailure('source_not_ready')
                    self._process([str(self.ffmpeg),'-nostdin','-v','error','-xerror','-max_error_rate','0','-threads','1','-i',str(original),
                        '-map_metadata','-1','-vn','-ac','1','-ar','16000','-c:a','pcm_s16le','-fs','60000000',str(prepared)],job,token,deadline,15)
                    # The engine validates the complete duration; never trim a
                    # long recording and publish it as a full transcription.
                    self._process([str(self.python),'-m','sanequeue.reporting.asr_light','--audio',str(prepared),
                        '--model',str(self.model),'--tokens',str(self.tokens),'--vad',str(self.vad),'--output',str(result_path),
                        '--maximum-seconds',str(spec['maximum_seconds']),'--language',spec['language']],job,token,deadline,35)
                    if not result_path.is_file() or result_path.is_symlink() or result_path.stat().st_size>2*1024*1024:
                        raise ProcessingFailure('result_invalid')
                    result=json.loads(result_path.read_text(encoding='utf-8'))
                    from .text_analysis import enrich
                    result=enrich(result,spec['language'])
                    result.setdefault('analysis',{}).update(source_sha256=digest.hexdigest(),source_bytes_complete=True,
                        decode_policy='fail_on_reported_decoder_error',complete_conversation=False,
                        decision_support_only=True,pre_bridge_trim='unavailable_without_recording_offset_proof')
                    self._check(job,token,deadline,95)
                    if not self.store.complete(job['id'],token,result):raise Cancelled('cancelled')
                return dict(id=job['id'],state='completed')
            except Deferred as error:
                self.store.defer(job['id'],token,str(error));return dict(id=job['id'],state='queued',reason=str(error))
            except Cancelled:return dict(id=job['id'],state='cancelled')
            except Exception as error:
                reason=str(error) if isinstance(error,ProcessingFailure) else 'processing_failed'
                self.store.fail(job['id'],token,reason)
                return dict(id=job['id'],state='failed',reason=reason)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('jobs','archive','recording-root','scratch','python','ffmpeg','model','tokens','vad'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--disabled-file');parser.add_argument('--once',action='store_true')
    args=parser.parse_args();store=AIJobs(args.jobs);store.initialize()
    def stop(*_):
        # Unwind the subprocess/temporary-file finally blocks before exit.
        # An unfinished lease is recovered on the next service start.
        raise SystemExit(0)
    signal.signal(signal.SIGTERM,stop)
    worker=AIWorker(store,Archive(args.archive),recording_root=args.recording_root,scratch=args.scratch,
        python=args.python,ffmpeg=args.ffmpeg,model=args.model,tokens=args.tokens,vad=args.vad,disabled_file=args.disabled_file)
    while True:
        result=worker.run_once()
        if args.once:print(json.dumps(result));break
        time.sleep(10)


if __name__=='__main__':main()
