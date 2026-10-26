"""Durable private CSV exports in a separate, resource-limited worker.

HTTP callers authorize creation and every later access themselves. A stored
scope never expands with new grants. The CLI reloads local grants before work,
between pages and before publication; download must independently reauthorize.
Pages use immutable fact versions pinned at request time, with short read
transactions. New ingestion never changes that snapshot. Legacy jobs without
a snapshot token retain their conservative global-watermark behavior.
CSV/XLSX use bounded pages. PDF shares the worker with a lower row/page ceiling.
"""
import argparse
from contextlib import contextmanager, ExitStack
from dataclasses import dataclass
import csv
from datetime import datetime
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import sqlite3
import stat
import threading
import time
import uuid
from zoneinfo import ZoneInfo

from .exports import table
from .privacy import display_number
from .queries import Scope, _where
from .store import Archive, QueryDeadline
from . import visit_snapshots
from . import xlsx_stream
from . import pdf_stream

_ID=re.compile(r'[0-9a-f]{32}\Z')
_MODES={'full','masked','hidden','pseudonymous'}
_OUTCOMES={'answered','abandoned','waiting','connected','transferred','exitwithtimeout',
           'exitempty','exitwithkey','unknown','reentered_without_end'}


class ExportFailure(RuntimeError):
    """Safe, public reason code; never include payloads or private paths."""


class _Deferred(ExportFailure):
    pass


class _Cancelled(ExportFailure):
    pass


def _json(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)


def _identity(value):
    if not isinstance(value,str) or not _ID.fullmatch(value):raise ValueError('invalid_export_job_id')
    return value


def projection_watermark(archive):
    with archive.reader() as db:
        row=db.execute('SELECT after_id FROM report_projection WHERE pbx=?',(archive.pbx,)).fetchone()
    if row is None:raise ExportFailure('projection_unavailable')
    return int(row[0])


def _local_json(path):
    """One bounded regular-file snapshot; missing policies must never default."""
    path=Path(path)
    if path.is_symlink():raise ValueError('invalid_export_authorization_file')
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0)|getattr(os,'O_NONBLOCK',0))
    with os.fdopen(fd,'rb') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size>2*1024*1024:
            raise ValueError('invalid_export_authorization_file')
        data=stream.read(2*1024*1024+1)
    if len(data)>2*1024*1024:raise ValueError('invalid_export_authorization_file')
    return json.loads(data)


def local_authorizer(accounts_path,policies_path):
    """Return a fail-closed callback; no grant/account cache survives a check."""
    from qpanel.local_accounts import validate_identity
    from qpanel.queue_policies import validate_config
    from sanequeue.security.permissions import sections_for,validate_sections,ROLE_ACTIONS
    def authorize(spec):
        try:
            accounts=_local_json(accounts_path)
            if not isinstance(accounts,dict) or len(accounts)>100:return False
            for username,account in accounts.items():
                if not isinstance(account,dict):return False
                validate_identity(username,account.get('role'),account.get('phone',''))
                validate_sections(account['role'],account.get('menus'))
                if not str(account.get('password_hash','')).startswith('pbkdf2:sha256:'):return False
            account=accounts.get(spec['owner'])
            if not account or account['role'] not in ('admin','supervisor') or 'reports' not in sections_for(account['role'],account):return False
            raw=_local_json(policies_path)
            if not isinstance(raw,dict) or type(raw.get('version')) is not int or raw['version']!=1 or not all(key in raw for key in ('queues','supervisors')):return False
            policy=validate_config(raw);role=account['role']
            grant=policy['supervisors'].get(spec['owner'],{})
            def allowed(queue,capability):
                return capability in ROLE_ACTIONS[role] and (role=='admin' or
                    queue in grant.get('queues',[]) and capability in grant.get('actions',[]))
            queues=spec['scope']['queues'];modes=spec['number_modes']
            return bool(queues and set(modes)==set(queues) and all(
                allowed(queue,'view') and allowed(queue,'report_export') and
                (modes[queue]!='full' or allowed(queue,'caller_details')) for queue in queues))
        except Exception:return False
    return authorize


@dataclass(frozen=True)
class Limits:
    max_rows:int=100000
    max_bytes:int=32*1024*1024
    page_size:int=200
    max_seconds:float=300
    min_free_bytes:int=256*1024*1024
    max_load_per_cpu:float=.75
    lease_seconds:float=60

    def __post_init__(self):
        if not (1<=self.max_rows<=100000 and 1<=self.max_bytes<=32*1024*1024
                and 1<=self.page_size<=200 and 0<self.max_seconds<=3600
                and self.min_free_bytes>=0 and 0<=self.max_load_per_cpu<=4
                and 5<=self.lease_seconds<=300):raise ValueError('invalid_export_limits')


class JobStore:
    def __init__(self,path,output_dir):
        self.path=Path(path).absolute()
        self.output_dir=Path(output_dir).absolute()

    def initialize(self):
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.output_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
        if self.path.is_symlink() or self.output_dir.is_symlink():raise ValueError('export_storage_symlink')
        if os.name!='nt' and self.output_dir.stat().st_mode&0o077:raise ValueError('export_output_permissions')
        fd=os.open(self.path,os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):raise ValueError('invalid_export_database')
            if os.name!='nt':os.fchmod(fd,0o600)
        finally:os.close(fd)
        with self._db() as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'").fetchone():
                raise ValueError('export_jobs_database_is_archive')
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''CREATE TABLE IF NOT EXISTS export_jobs(
              id TEXT PRIMARY KEY,owner TEXT NOT NULL,state TEXT NOT NULL,
              spec TEXT NOT NULL,spec_hash TEXT NOT NULL,created REAL,updated REAL,
              available_at REAL,lease_until REAL,worker TEXT,attempts INTEGER DEFAULT 0,
              rows INTEGER DEFAULT 0,bytes INTEGER DEFAULT 0,error_code TEXT,checksum TEXT);
              CREATE INDEX IF NOT EXISTS ej_queue ON export_jobs(state,available_at,created);
              CREATE INDEX IF NOT EXISTS ej_owner ON export_jobs(owner,created,id);''')
            columns={row[1] for row in db.execute('PRAGMA table_info(export_jobs)')}
            for name in ('request_key','request_hash'):
                if name not in columns:db.execute('ALTER TABLE export_jobs ADD COLUMN '+name+' TEXT')
            db.execute('CREATE UNIQUE INDEX IF NOT EXISTS ej_request ON export_jobs(owner,request_key) WHERE request_key IS NOT NULL')

    @contextmanager
    def _db(self,*,write=False):
        if self.path.is_symlink() or self.output_dir.is_symlink():raise ValueError('export_storage_symlink')
        db=sqlite3.connect(self.path,timeout=.5)
        db.row_factory=sqlite3.Row
        try:
            db.execute('PRAGMA trusted_schema=OFF')
            db.execute('PRAGMA synchronous=FULL')
            if write:db.execute('BEGIN IMMEDIATE')
            with db:yield db
        finally:db.close()

    def create(self,owner,scope,start,end,*,watermark,pbx='primary',number_modes,
               language='en',outcome=None,format='csv',snapshot=None,request_key=None):
        if not isinstance(owner,str) or not 1<=len(owner)<=128:raise ValueError('invalid_export_owner')
        _where(pbx,scope,start,end)
        if not scope.queues:raise ValueError('empty_export_scope')
        if not isinstance(watermark,int) or isinstance(watermark,bool) or watermark<0:raise ValueError('invalid_export_watermark')
        if format not in ('csv','xlsx','pdf') or language not in ('fa','en'):raise ValueError('unsupported_export_format_or_language')
        if outcome is not None and outcome not in _OUTCOMES:raise ValueError('invalid_report_outcome')
        queues=tuple(dict.fromkeys(scope.queues));agents=tuple(dict.fromkeys(scope.agents))
        if any(not isinstance(v,str) or not 1<=len(v)<=256 for v in (*queues,*agents)):
            raise ValueError('invalid_export_scope')
        if set(number_modes)!=set(queues) or any(mode not in _MODES for mode in number_modes.values()):
            raise ValueError('invalid_export_number_policy')
        if not math.isfinite(float(scope.not_before)):raise ValueError('invalid_export_assignment_cutoff')
        if snapshot is not None:visit_snapshots.validate_token(snapshot)
        spec=dict(owner=owner,pbx=str(pbx),start=float(start),end=float(end),watermark=watermark,
                  scope=dict(queues=list(queues),agents=list(agents),self_only=bool(scope.self_only),not_before=float(scope.not_before)),
                  number_modes=dict(number_modes),language=language,outcome=outcome,format=format,
                  unit='queue_visit',number_policy_version='1')
        if snapshot is not None:spec['snapshot']=dict(snapshot)
        if request_key is not None and (not isinstance(request_key,str) or not re.fullmatch('[A-Za-z0-9_.:-]{1,128}',request_key)):
            raise ValueError('invalid_export_request_key')
        core={key:value for key,value in spec.items() if key not in ('watermark','snapshot')}
        request_hash=hashlib.sha256(_json(core).encode()).hexdigest()
        payload=_json(spec);ident=uuid.uuid4().hex;now=time.time()
        with self._db(write=True) as db:
            if request_key is not None:
                prior=db.execute('SELECT * FROM export_jobs WHERE owner=? AND request_key=?',(owner,request_key)).fetchone()
                if prior:
                    self._public(prior)
                    if prior['request_hash']!=request_hash:raise ExportFailure('export_request_conflict')
                    return prior['id']
            counts=db.execute("SELECT COUNT(*),COALESCE(SUM(owner=?),0) FROM export_jobs WHERE state IN ('queued','running')",(owner,)).fetchone()
            if counts[0]>=10 or counts[1]>=3:raise ExportFailure('export_queue_quota')
            db.execute('INSERT INTO export_jobs(id,owner,state,spec,spec_hash,created,updated,available_at,request_key,request_hash) VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (ident,owner,'queued',payload,hashlib.sha256(payload.encode()).hexdigest(),now,now,now,request_key,request_hash))
        return ident

    def by_request(self,owner,request_key):
        if not isinstance(owner,str) or not 1<=len(owner)<=128 or not isinstance(request_key,str) or not re.fullmatch('[A-Za-z0-9_.:-]{1,128}',request_key):raise ValueError('invalid_export_request_key')
        with self._db() as db:
            return self._public(db.execute('SELECT * FROM export_jobs WHERE owner=? AND request_key=?',(owner,request_key)).fetchone())

    @staticmethod
    def _public(row):
        if row is None:return None
        result=dict(row);payload=result.pop('spec');digest=result.pop('spec_hash')
        if hashlib.sha256(payload.encode()).hexdigest()!=digest:raise ExportFailure('export_spec_integrity')
        result['spec']=json.loads(payload)
        if result.get('request_key') is not None:
            core={key:value for key,value in result['spec'].items() if key not in ('watermark','snapshot')}
            if result.get('request_hash')!=hashlib.sha256(_json(core).encode()).hexdigest():
                raise ExportFailure('export_request_integrity')
        result.pop('request_hash',None)
        result.pop('worker',None);result.pop('lease_until',None)
        return result

    def get(self,ident,owner):
        _identity(ident)
        with self._db() as db:row=db.execute('SELECT * FROM export_jobs WHERE id=? AND owner=?',(ident,owner)).fetchone()
        return self._public(row)

    def list(self,owner,limit=20):
        limit=max(1,min(50,int(limit)))
        with self._db() as db:rows=db.execute('SELECT * FROM export_jobs WHERE owner=? ORDER BY created DESC,id DESC LIMIT ?',(owner,limit)).fetchall()
        return [self._public(row) for row in rows]

    def cancel(self,ident,owner):
        _identity(ident)
        with self._db(write=True) as db:
            return db.execute("UPDATE export_jobs SET state='cancelled',updated=?,error_code='cancelled' WHERE id=? AND owner=? AND state IN ('queued','running')",
                              (time.time(),ident,owner)).rowcount==1

    def claim(self,worker,*,lease_seconds=60,now=None):
        now=time.time() if now is None else float(now)
        with self._db(write=True) as db:
            db.execute("UPDATE export_jobs SET state=CASE WHEN attempts>=3 THEN 'failed' ELSE 'queued' END,error_code='lease_expired',worker=NULL,lease_until=NULL,available_at=?,updated=? WHERE state='running' AND lease_until<?",(now,now,now))
            row=db.execute("SELECT * FROM export_jobs WHERE state='queued' AND available_at<=? ORDER BY created,id LIMIT 1",(now,)).fetchone()
            if row is None:return None
            db.execute("UPDATE export_jobs SET state='running',worker=?,lease_until=?,attempts=attempts+1,updated=?,rows=CASE WHEN checksum IS NULL THEN 0 ELSE rows END,bytes=CASE WHEN checksum IS NULL THEN 0 ELSE bytes END,error_code=NULL WHERE id=?",(worker,now+lease_seconds,now,row['id']))
            return self._public(db.execute('SELECT * FROM export_jobs WHERE id=?',(row['id'],)).fetchone())

    def _update(self,ident,worker,*,state='running',rows=0,size=0,error=None,checksum=None,lease_seconds=60):
        now=time.time()
        with self._db(write=True) as db:
            return db.execute("UPDATE export_jobs SET state=?,rows=?,bytes=?,updated=?,lease_until=?,error_code=?,checksum=? WHERE id=? AND state='running' AND worker=?",
                              (state,rows,size,now,now+lease_seconds,error,checksum,ident,worker)).rowcount==1

    def _defer(self,ident,worker,error,*,preserve_manifest=False):
        with self._db(write=True) as db:
            db.execute("UPDATE export_jobs SET state='queued',available_at=?,updated=?,worker=NULL,lease_until=NULL,attempts=MAX(0,attempts-1),rows=CASE WHEN ? THEN rows ELSE 0 END,bytes=CASE WHEN ? THEN bytes ELSE 0 END,checksum=CASE WHEN ? THEN checksum ELSE NULL END,error_code=? WHERE id=? AND state='running' AND worker=?",
                       (time.time()+30,time.time(),preserve_manifest,preserve_manifest,preserve_manifest,error,ident,worker))

    def open_output(self,ident,owner):
        job=self.get(ident,owner)
        if job is None or job['state']!='completed':raise FileNotFoundError('export_not_completed')
        if self.output_dir.is_symlink():raise ValueError('export_storage_symlink')
        path=self.output_dir/(ident+'.'+job['spec']['format'])
        fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0))
        metadata=os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size!=job['bytes']:
            os.close(fd);raise ExportFailure('export_output_integrity')
        return fd,metadata.st_size


@contextmanager
def _worker_lock(path):
    fd=os.open(path,os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
    acquired=False
    try:
        if os.name=='nt':
            import msvcrt
            if not os.fstat(fd).st_size:os.write(fd,b'0')
            os.lseek(fd,0,os.SEEK_SET)
            try:msvcrt.locking(fd,msvcrt.LK_NBLCK,1);acquired=True
            except OSError:pass
        else:
            import fcntl
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);acquired=True
            except BlockingIOError:pass
        yield acquired
    finally:
        if acquired:
            if os.name=='nt':
                os.lseek(fd,0,os.SEEK_SET);msvcrt.locking(fd,msvcrt.LK_UNLCK,1)
            else:fcntl.flock(fd,fcntl.LOCK_UN)
        os.close(fd)


class ExportWorker:
    def __init__(self,store,archive,*,number_key=None,limits=None,authorize=None,disabled_file=None):
        self.store=store;self.archive=archive;self.number_key=number_key
        self.limits=limits or Limits();self.authorize=authorize if authorize is not None else (lambda spec:False)
        self.disabled_file=Path(disabled_file or os.getenv('SANEQUEUE_DISABLE_FILE','/var/lib/sanequeue/module.disabled'))
        if store.path.resolve()==archive.path.resolve():raise ValueError('export_jobs_database_is_archive')

    def _gate(self,deadline=None):
        if self.disabled_file and self.disabled_file.exists():raise _Deferred('module_disabled')
        if deadline is not None and time.monotonic()>=deadline:raise ExportFailure('export_time_limit')
        if shutil.disk_usage(self.store.output_dir).free<self.limits.min_free_bytes:raise _Deferred('export_disk_pressure')
        if self.limits.max_load_per_cpu and hasattr(os,'getloadavg'):
            if os.getloadavg()[0]/max(1,os.cpu_count() or 1)>self.limits.max_load_per_cpu:raise _Deferred('export_system_busy')

    def _check(self,spec):
        if not self.authorize(spec):raise ExportFailure('export_access_revoked')
        if spec['pbx']!=self.archive.pbx:raise ExportFailure('export_pbx_mismatch')
        if 'pseudonymous' in spec['number_modes'].values() and (not isinstance(self.number_key,bytes) or len(self.number_key)<32):
            raise ExportFailure('export_number_key_unavailable')
        if spec.get('snapshot') is not None:
            try:
                with self.archive.reader() as db:visit_snapshots.validate(db,self.archive.pbx,spec['snapshot'])
            except visit_snapshots.SnapshotUnavailable as error:
                raise ExportFailure(str(error)) from None
        elif projection_watermark(self.archive)!=spec['watermark']:
            raise ExportFailure('export_projection_changed')

    def _page(self,spec,before,deadline):
        remaining=deadline-time.monotonic()
        if remaining<=0:raise ExportFailure('export_time_limit')
        scope=Scope(**{**spec['scope'],'queues':tuple(spec['scope']['queues']),'agents':tuple(spec['scope']['agents'])})
        clause,args=_where(self.archive.pbx,scope,spec['start'],spec['end'])
        if spec['outcome']:
            clause+=' AND outcome=?';args.append(spec['outcome'])
        if before:
            clause+=' AND (entered<? OR (entered=? AND id<?))';args.extend((before[0],before[0],before[1]))
        bounded=Archive(self.archive.path,pbx=self.archive.pbx,read_seconds=min(2,remaining))
        with bounded.reader() as db:
            if spec.get('snapshot') is not None:
                try:
                    return visit_snapshots.page(db,self.archive.pbx,spec['snapshot'],scope,spec['start'],
                        spec['end'],before=before,outcome=spec['outcome'],limit=self.limits.page_size)
                except visit_snapshots.SnapshotUnavailable as error:
                    raise ExportFailure(str(error)) from None
            watermark=db.execute('SELECT after_id FROM report_projection WHERE pbx=?',(self.archive.pbx,)).fetchone()
            if not watermark or watermark[0]!=spec['watermark']:raise ExportFailure('export_projection_changed')
            return [dict(row) for row in db.execute('SELECT * FROM report_visits WHERE '+clause+
                ' ORDER BY entered DESC,id DESC LIMIT ?',(*args,self.limits.page_size))]

    def _published_matches(self,job,path,deadline):
        """Recover only a file authenticated by the pre-publication manifest."""
        if not job['checksum'] or not re.fullmatch('[0-9a-f]{64}',job['checksum']):return False
        max_rows=min(self.limits.max_rows,pdf_stream.MAX_ROWS) if job['spec']['format']=='pdf' else self.limits.max_rows
        max_bytes=min(self.limits.max_bytes,pdf_stream.MAX_BYTES) if job['spec']['format']=='pdf' else self.limits.max_bytes
        if not 0<=job['rows']<=max_rows or not 0<job['bytes']<=max_bytes:return False
        fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0))
        digest=hashlib.sha256()
        with os.fdopen(fd,'rb') as stream:
            metadata=os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size!=job['bytes']:return False
            while True:
                self._gate(deadline)
                chunk=stream.read(65536)
                if not chunk:break
                digest.update(chunk)
        return digest.hexdigest()==job['checksum']

    def run_once(self):
        with _worker_lock(str(self.store.path)+'.worker.lock') as acquired:
            if not acquired:return dict(state='busy')
            try:self._gate()
            except _Deferred as error:return dict(state='deferred',error=str(error))
            worker=uuid.uuid4().hex
            job=self.store.claim(worker,lease_seconds=self.limits.lease_seconds)
            if job is None:return dict(state='idle')
            ident=job['id'];spec=job['spec'];part=self.store.output_dir/(ident+'.'+worker+'.part')
            final=self.store.output_dir/(ident+'.'+spec['format']);published=False
            rows_written=0;size=0;digest=hashlib.sha256()
            deadline=time.monotonic()+self.limits.max_seconds
            try:
                if final.exists() or final.is_symlink():
                    if not self._published_matches(job,final,deadline):raise ExportFailure('export_output_exists')
                    # The durable manifest proves this artifact was ours. A
                    # revoked/stale recovery removes it instead of publishing.
                    published=True;rows_written=job['rows'];size=job['bytes']
                    self._check(spec)
                    for old in self.store.output_dir.glob(ident+'.*.part'):old.unlink()
                    if not self.store._update(ident,worker,state='completed',rows=rows_written,size=size,checksum=job['checksum']):raise _Cancelled('cancelled')
                    return dict(id=ident,state='completed',rows=rows_written,bytes=size,recovered=True)
                self._check(spec)
                # No active worker can own these remnants while this lock is held.
                for old in self.store.output_dir.glob(ident+'.*.part'):old.unlink()
                fd=os.open(part,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_BINARY',0),0o600)
                with os.fdopen(fd,'wb') as output, ExitStack() as cleanup:
                    def write(data):
                        nonlocal size
                        if size+len(data)>self.limits.max_bytes:raise ExportFailure('export_byte_limit')
                        output.write(data);digest.update(data);size+=len(data)
                    def line(values):
                        text=io.StringIO(newline='');writer=csv.writer(text)
                        writer.writerow(["'"+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@','\t','\r','\n')) else v for v in values])
                        write(text.getvalue().encode('utf-8'))
                    workbook=None;document=None
                    if spec['format']=='xlsx':
                        zone=ZoneInfo('Asia/Tehran')
                        period=datetime.fromtimestamp(spec['start'],zone).isoformat()+' .. '+datetime.fromtimestamp(spec['end'],zone).isoformat()+' [end exclusive]'
                        workbook=xlsx_stream.Workbook(output,spec['language'],period=period,max_bytes=self.limits.max_bytes)
                        cleanup.callback(workbook.abort)
                    elif spec['format']=='pdf':
                        def pdf_check():
                            self._gate(deadline);self._check(spec)
                            if not self.store._update(ident,worker,rows=rows_written,size=output.tell(),lease_seconds=self.limits.lease_seconds):
                                raise _Cancelled('cancelled')
                        document=pdf_stream.Document(output,spec['language'],start=spec['start'],end=spec['end'],
                            queues=spec['scope']['queues'],outcome=spec['outcome'],check=pdf_check,
                            max_rows=min(self.limits.max_rows,pdf_stream.MAX_ROWS),max_bytes=min(self.limits.max_bytes,pdf_stream.MAX_BYTES))
                        cleanup.callback(document.abort)
                    else:
                        write(b'\xef\xbb\xbf');headers,_=table([],spec['language']);line(headers)
                    before=None
                    while True:
                        self._gate(deadline);self._check(spec)
                        if not self.store._update(ident,worker,rows=rows_written,size=size,lease_seconds=self.limits.lease_seconds):raise _Cancelled('cancelled')
                        rows=self._page(spec,before,deadline)
                        if not rows:break
                        if rows_written+len(rows)>self.limits.max_rows:raise ExportFailure('export_row_limit')
                        for row in rows:
                            row['caller']=display_number(row['caller'],spec['number_modes'][row['queue']],
                                secret=self.number_key,tenant='default',pbx=spec['pbx'],version=spec['number_policy_version'])
                        _,body=table(rows,spec['language'])
                        if workbook:
                            workbook.append(body);size=output.tell()
                        elif document:
                            document.append(body);size=output.tell()
                        else:
                            for values in body:line(values)
                        rows_written+=len(rows)
                        before=(rows[-1]['entered'],rows[-1]['id'])
                        self._check(spec)
                        if not self.store._update(ident,worker,rows=rows_written,size=size,lease_seconds=self.limits.lease_seconds):raise _Cancelled('cancelled')
                    self._gate(deadline);self._check(spec)
                    if workbook:workbook.close();size=output.tell()
                    if document:document.close();size=output.tell()
                    output.flush();os.fsync(output.fileno())
                if spec['format'] in ('xlsx','pdf'):
                    digest=hashlib.sha256()
                    with part.open('rb') as completed:
                        while chunk:=completed.read(65536):
                            self._gate(deadline);digest.update(chunk)
                if not self.store._update(ident,worker,rows=rows_written,size=size,checksum=digest.hexdigest(),lease_seconds=self.limits.lease_seconds):raise _Cancelled('cancelled')
                self._gate(deadline);self._check(spec)
                os.link(part,final);published=True;part.unlink()
                if os.name!='nt':
                    directory=os.open(self.store.output_dir,os.O_RDONLY|os.O_DIRECTORY)
                    try:os.fsync(directory)
                    finally:os.close(directory)
                self._check(spec)
                if not self.store._update(ident,worker,state='completed',rows=rows_written,size=size,checksum=digest.hexdigest()):raise _Cancelled('cancelled')
                return dict(id=ident,state='completed',rows=rows_written,bytes=size)
            except _Deferred as error:
                self.store._defer(ident,worker,str(error),preserve_manifest=bool(job['checksum']) and not published and final.exists())
                return dict(id=ident,state='queued',error=str(error))
            except _Cancelled:
                return dict(id=ident,state='cancelled')
            except Exception as error:
                reason=str(error) if isinstance(error,(ExportFailure,xlsx_stream.SizeLimit,pdf_stream.PdfFailure)) else 'export_query_deadline' if isinstance(error,QueryDeadline) else 'export_failed'
                self.store._update(ident,worker,state='failed',rows=rows_written,size=0,error=reason)
                return dict(id=ident,state='failed',error=reason)
            finally:
                if part.exists() or part.is_symlink():part.unlink()
                if published:
                    current=self.store.get(ident,job['owner'])
                    if current is None or current['state']!='completed':final.unlink(missing_ok=True)


def _number_key(path):
    if not path:return None
    path=Path(path)
    if path.is_symlink() or not path.is_file():raise ValueError('invalid_number_key_file')
    if os.name!='nt' and path.stat().st_mode&0o077:raise ValueError('number_key_permissions')
    value=path.read_bytes()
    if len(value)==32:return value
    if re.fullmatch(rb'[0-9a-fA-F]{64}\s*',value):return bytes.fromhex(value.decode().strip())
    raise ValueError('invalid_number_key_length')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jobs-db',required=True);parser.add_argument('--output-dir',required=True)
    parser.add_argument('--archive',required=True);parser.add_argument('--pbx',default='primary')
    parser.add_argument('--accounts');parser.add_argument('--policies')
    parser.add_argument('--disabled-file');parser.add_argument('--number-key-file')
    parser.add_argument('--interval',type=float,default=10);parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    if not 1<=args.interval<=300:parser.error('interval must be between 1 and 300')
    store=JobStore(args.jobs_db,args.output_dir);store.initialize()
    state=Path(args.archive).absolute().parent
    worker=ExportWorker(store,Archive(args.archive,pbx=args.pbx),number_key=_number_key(args.number_key_file),
        disabled_file=args.disabled_file,authorize=local_authorizer(args.accounts or state/'local_accounts.json',
            args.policies or state/'local_queue_policies.json'))
    stopped=threading.Event()
    for signum in (signal.SIGINT,signal.SIGTERM):signal.signal(signum,lambda *_:stopped.set())
    while not stopped.is_set():
        result=worker.run_once()
        if args.once:print(_json(result));return
        stopped.wait(args.interval)


if __name__=='__main__':main()
