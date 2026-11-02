"""Private durable incident-audio conversion. No PBX or network operations."""
import argparse
from contextlib import contextmanager
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import stat
import tempfile
import time
import uuid

ID = re.compile(r'[a-f0-9]{32}\Z')
MAX_INPUT = 8 * 1024 * 1024


def local_authorizer(path):
    """A fresh bounded account/menu snapshot for every authorization decision."""
    from sanequeue.security.permissions import sections_for, validate_sections
    from qpanel.local_accounts import validate_identity
    def authorize(owner):
        try:
            path_value = Path(path)
            if path_value.is_symlink():return False
            fd = os.open(path_value, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
            with os.fdopen(fd, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > 2*1024*1024:return False
                accounts = json.loads(stream.read(2*1024*1024+1))
            if not isinstance(accounts, dict) or len(accounts)>100:return False
            account = accounts.get(owner)
            if not isinstance(account, dict):return False
            validate_identity(owner, account.get('role'), account.get('phone', ''))
            validate_sections(account['role'], account.get('menus'))
            return (account['role']=='admin' and 'telephony' in sections_for('admin', account)
                and str(account.get('password_hash','')).startswith('pbkdf2:sha256:'))
        except Exception:return False
    return authorize


class MediaJobs:
    def __init__(self, state):
        self.state = Path(state);self.path=self.state/'incident-media.sqlite3'
        self.inputs=self.state/'incident-media-inputs'

    def initialize(self):
        if self.state.is_symlink() or self.path.is_symlink() or self.inputs.is_symlink():raise ValueError('unsafe_media_store')
        self.state.mkdir(parents=True, exist_ok=True);self.inputs.mkdir(mode=0o700, exist_ok=True)
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY,owner TEXT NOT NULL,binding TEXT NOT NULL,input_hash TEXT NOT NULL,state TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,lease TEXT NOT NULL DEFAULT "",lease_until REAL NOT NULL DEFAULT 0,attempts INTEGER NOT NULL DEFAULT 0,audio TEXT,seconds REAL,error TEXT)')
            db.execute('CREATE INDEX IF NOT EXISTS media_due ON jobs(state,created)')
        if os.name!='nt':os.chmod(self.path,0o600);os.chmod(self.inputs,0o700)

    @contextmanager
    def db(self):
        if self.path.is_symlink():raise ValueError('unsafe_media_store')
        db=sqlite3.connect(self.path, timeout=2);db.row_factory=sqlite3.Row
        try:
            with db:yield db
        finally:db.close()

    def enqueue(self, owner, binding, content, *, authorize=lambda owner:False, now=None):
        if not authorize(owner):raise PermissionError('media_not_authorized')
        if not content or len(content)>MAX_INPUT:raise ValueError('audio_max_8mb')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',binding or ''):raise ValueError('invalid_media_binding')
        self.initialize();now=time.time() if now is None else now
        if (self.state/'module.disabled').exists():raise ValueError('module_disabled')
        if shutil.disk_usage(self.state).free<256*1024*1024:raise ValueError('media_low_disk')
        ident=uuid.uuid4().hex;digest=hashlib.sha256(content).hexdigest();target=self.inputs/(ident+'.input')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            previous=db.execute("SELECT id,state FROM jobs WHERE owner=? AND binding=? AND input_hash=? AND state IN ('queued','running') ORDER BY created DESC LIMIT 1",(owner,binding,digest)).fetchone()
            if previous:return dict(previous)
            if db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]>=10000:raise ValueError('media_history_capacity')
            if db.execute("SELECT COUNT(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0]>=4:raise ValueError('media_queue_full')
            if db.execute("SELECT COUNT(*) FROM jobs WHERE owner=? AND state IN ('queued','running')",(owner,)).fetchone()[0]>=2:raise ValueError('media_owner_queue_full')
            fd,name=tempfile.mkstemp(prefix='.media-',dir=self.inputs)
            try:
                with os.fdopen(fd,'wb') as stream:stream.write(content);stream.flush();os.fsync(stream.fileno())
                os.replace(name,target)
                if not authorize(owner):raise PermissionError('media_not_authorized')
                db.execute('INSERT INTO jobs(id,owner,binding,input_hash,state,created,updated) VALUES (?,?,?,?,?,?,?)',(ident,owner,binding,digest,'queued',now,now))
            except Exception:
                target.unlink(missing_ok=True);raise
            finally:
                if os.path.exists(name):os.unlink(name)
        return dict(id=ident,state='queued')

    def status(self, ident, owner, authorize=lambda owner:False):
        if not authorize(owner):raise PermissionError('media_not_authorized')
        if not isinstance(ident,str) or not ID.fullmatch(ident):raise ValueError('invalid_media_job')
        if not self.path.exists():raise LookupError('media_job_not_found')
        with self.db() as db:row=db.execute('SELECT id,state,audio,seconds,error,binding FROM jobs WHERE id=? AND owner=?',(ident,owner)).fetchone()
        if row is None:raise LookupError('media_job_not_found')
        return dict(row)

    def claim(self, now=None):
        now=time.time() if now is None else now;lease=secrets.token_hex(16)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("UPDATE jobs SET state=CASE WHEN attempts<2 THEN 'queued' ELSE 'failed' END,error='worker_interrupted',lease='',lease_until=0 WHERE state='running' AND lease_until<?",(now,))
            db.execute("UPDATE jobs SET state='failed',error='media_job_expired',updated=? WHERE state='queued' AND created<?",(now,now-86400))
            if db.execute("SELECT 1 FROM jobs WHERE state='running' AND lease_until>=?",(now,)).fetchone():return None
            row=db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
            if row is None:return None
            db.execute("UPDATE jobs SET state='running',lease=?,lease_until=?,attempts=attempts+1,updated=? WHERE id=?",(lease,now+90,now,row['id']))
            return dict(row,lease=lease)

    def finish(self, job, state, *, result=None, error=None):
        result=result or {}
        with self.db() as db:
            changed=db.execute("UPDATE jobs SET state=?,audio=?,seconds=?,error=?,updated=?,lease='',lease_until=0 WHERE id=? AND state='running' AND lease=?",(state,result.get('audio'),result.get('seconds'),error,time.time(),job['id'],job['lease'])).rowcount
        if changed:(self.inputs/(job['id']+'.input')).unlink(missing_ok=True)
        return bool(changed)

    def lease_current(self, job):
        with self.db() as db:return db.execute("SELECT 1 FROM jobs WHERE id=? AND state='running' AND lease=? AND lease_until>=?",(job['id'],job['lease'],time.time())).fetchone() is not None

    def cleanup(self):
        """Remove only bounded stale staging/orphans; retain all job metadata."""
        with self.db() as db:active={r[0] for r in db.execute("SELECT id FROM jobs WHERE state IN ('queued','running')")}
        now=time.time()
        for entry in itertools.islice(self.inputs.iterdir(),100):
            name=entry.name
            if not (re.fullmatch(r'[a-f0-9]{32}\.input',name) or name.startswith('.media-')):continue
            if name.endswith('.input') and name[:-6] in active:continue
            try:
                if now-entry.lstat().st_mtime>300:entry.unlink()
            except OSError:pass


class MediaWorker:
    def __init__(self, jobs, *, authorize=lambda owner:False, allowed=lambda:{}, convert=None, ready=None):
        self.jobs=jobs;self.authorize=authorize;self.allowed=allowed
        if convert is None:
            from .features import convert_audio
            convert=convert_audio
        self.convert=convert;self.ready=ready or self.resources_ready

    def resources_ready(self):
        if (self.jobs.state/'module.disabled').exists():return False
        if shutil.disk_usage(self.jobs.state).free<256*1024*1024:return False
        return not hasattr(os,'getloadavg') or os.getloadavg()[0]/max(1,os.cpu_count() or 1)<.75

    def tick(self):
        self.jobs.initialize();self.jobs.cleanup()
        if (self.jobs.state/'module.disabled').exists() or not self.ready():return False
        job=self.jobs.claim()
        if job is None:return False
        try:
            if not self.authorize(job['owner']) or job['binding'] not in self.allowed():raise PermissionError()
            path=self.jobs.inputs/(job['id']+'.input')
            fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
            with os.fdopen(fd,'rb') as stream:
                meta=os.fstat(stream.fileno())
                if not stat.S_ISREG(meta.st_mode) or meta.st_nlink!=1 or not 0<meta.st_size<=MAX_INPUT:raise ValueError('invalid_media_input')
                content=stream.read(MAX_INPUT+1)
            if hashlib.sha256(content).hexdigest()!=job['input_hash']:raise ValueError('media_input_changed')
            audio,seconds=self.convert(content)
            # A second worker recovering an expired lease cannot race publication.
            with self.jobs.db() as db:
                db.execute('BEGIN IMMEDIATE')
                current=db.execute("SELECT 1 FROM jobs WHERE id=? AND state='running' AND lease=? AND lease_until>=?",(job['id'],job['lease'],time.time())).fetchone()
                if not current:return True
                if not self.authorize(job['owner']) or job['binding'] not in self.allowed():raise PermissionError()
                if (self.jobs.state/'module.disabled').exists():raise ValueError('module_disabled')
                if not self.ready():raise ValueError('media_resources_changed')
                from .incidents import IncidentStore
                result=IncidentStore(self.jobs.state).publish(audio,seconds)
                if not self.authorize(job['owner']) or job['binding'] not in self.allowed():raise PermissionError()
                db.execute("UPDATE jobs SET state='completed',audio=?,seconds=?,error=NULL,lease='',lease_until=0,updated=? WHERE id=? AND lease=?",(result['audio'],result['seconds'],time.time(),job['id'],job['lease']))
            path.unlink(missing_ok=True)
        except PermissionError:self.jobs.finish(job,'failed',error='media_not_authorized')
        except ValueError as error:self.jobs.finish(job,'failed',error=str(error) if re.fullmatch('[a-z0-9_]{1,80}',str(error)) else 'media_conversion_failed')
        except Exception:self.jobs.finish(job,'failed',error='media_conversion_failed')
        return True


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--state',default='/var/lib/sanequeue');parser.add_argument('--accounts',default='/var/lib/sanequeue/local_accounts.json');parser.add_argument('--bindings',default='/etc/sanequeue/incident-bindings.json');parser.add_argument('--once',action='store_true');args=parser.parse_args()
    from .incidents import bindings
    worker=MediaWorker(MediaJobs(args.state),authorize=local_authorizer(args.accounts),allowed=lambda:bindings(args.bindings))
    while True:
        worker.tick()
        if args.once:return
        time.sleep(5)


if __name__=='__main__':main()
