"""Bounded recovery of abandoned private export files, without retention deletes.

Called only under the export worker's exclusive filesystem lock. Inactive
artifacts move into a private, non-downloadable quarantine on the same volume.
Durable intents fence process death between link, unlink and database commit.
"""
from contextlib import contextmanager
import os
import re
import stat
import sqlite3
import time
import uuid

_NAME=re.compile(r'(?P<job>[a-f0-9]{32})\.(?:(?P<worker>[a-f0-9]{32})\.part|(?P<format>csv|xlsx|pdf))\Z')


def initialize(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS export_artifacts(
      id TEXT PRIMARY KEY,owner TEXT NOT NULL,job_id TEXT NOT NULL,
      source TEXT NOT NULL,target TEXT NOT NULL,state TEXT NOT NULL,reason TEXT NOT NULL,
      device TEXT NOT NULL,inode TEXT NOT NULL,size INTEGER NOT NULL,mtime TEXT NOT NULL,
      created REAL NOT NULL,updated REAL NOT NULL,
      UNIQUE(source,device,inode,mtime,size));
      CREATE INDEX IF NOT EXISTS ea_pending ON export_artifacts(state,created,id);
      CREATE INDEX IF NOT EXISTS ea_owner ON export_artifacts(owner,created DESC,id DESC);''')


def _identity(meta):
    return (str(meta.st_dev),str(meta.st_ino),meta.st_size,str(meta.st_mtime_ns))


def _regular(path):
    try:
        meta=path.lstat()
        if not stat.S_ISREG(meta.st_mode):return None
        if os.name!='nt' and meta.st_uid!=os.geteuid():return None
        return meta
    except FileNotFoundError:return None


def _same(path,row):
    meta=_regular(path)
    return bool(meta and _identity(meta)==(row['device'],row['inode'],row['size'],row['mtime']))


class _BudgetExpired(RuntimeError):pass


class ArtifactReconciler:
    def __init__(self,store,*,grace_seconds=300):
        if not 0<=grace_seconds<=86400:raise ValueError('invalid_export_recovery_grace')
        self.store=store;self.grace=grace_seconds;self.iterator=None;self.deadline=None
        self.directory=store.output_dir/'quarantine'

    def __del__(self):
        try:self.close()
        except OSError:pass

    def close(self):
        if self.iterator is not None:self.iterator.close();self.iterator=None

    def _directories(self,*,create=False):
        for path in (self.store.output_dir,self.directory):
            if path==self.directory:
                if not create and not path.exists() and not path.is_symlink():continue
                if create:
                    try:path.mkdir(mode=0o700)
                    except FileExistsError:pass
            meta=path.lstat()
            if not stat.S_ISDIR(meta.st_mode):raise ValueError('export_recovery_storage_unavailable')
            if os.name!='nt' and (meta.st_uid!=os.geteuid() or meta.st_mode&0o077):
                raise ValueError('export_recovery_storage_unavailable')

    @contextmanager
    def _db(self,*,write=False):
        remaining=self.deadline-time.monotonic() if self.deadline is not None else 1
        if remaining<=0:raise _BudgetExpired('export_recovery_budget')
        with self.store._db(write=write,timeout=min(.05,remaining),deadline=self.deadline) as db:yield db

    def _job(self,ident):
        with self._db() as db:
            return db.execute('SELECT id,owner,state,worker,updated,bytes FROM export_jobs WHERE id=?',(ident,)).fetchone()

    def _eligible(self,name,meta,job,active,now):
        match=_NAME.fullmatch(name)
        if not match or not job or meta.st_mtime>now-self.grace:return None
        if job['state'] in ('failed','cancelled') and job['updated']<=now-self.grace:
            return 'terminal_unpublished'
        worker=match['worker']
        if worker and active==(job['id'],job['worker']) and worker!=job['worker'] and job['state']=='running':
            return 'superseded_attempt'
        # A process can die between hard-link publication and staging unlink.
        # Retire staging only while a completed artifact still exists. The
        # downloadable final is never moved, and partial bytes stay preserved.
        if worker and job['state']=='completed':
            for suffix in ('csv','xlsx','pdf'):
                final=_regular(self.store.output_dir/(job['id']+'.'+suffix))
                if final and final.st_size==job['bytes']:
                    return 'redundant_completed_link' if _identity(final)==_identity(meta) else 'completed_attempt_staging'
        return None

    def _intent(self,name,meta,job,reason,now):
        with self._db(write=True) as db:
            if db.execute("SELECT 1 FROM export_artifacts WHERE source=? AND state IN ('conflict','source_changed') LIMIT 1",(name,)).fetchone():return None
            pending=db.execute("SELECT COUNT(*) FROM (SELECT 1 FROM export_artifacts WHERE state='pending' LIMIT 100)").fetchone()[0]
            if pending>=100:return None
            current=db.execute('SELECT * FROM export_artifacts WHERE source=? AND device=? AND inode=? AND mtime=? AND size=?',
                (name,*_identity(meta)[:2],str(meta.st_mtime_ns),meta.st_size)).fetchone()
            if current:
                if current['state']=='protected':
                    db.execute("UPDATE export_artifacts SET state='pending',reason=?,updated=? WHERE id=?",(reason,now,current['id']))
                    return dict(db.execute('SELECT * FROM export_artifacts WHERE id=?',(current['id'],)).fetchone())
                return dict(current) if current['state']=='pending' else None
            ident=uuid.uuid4().hex
            db.execute('''INSERT INTO export_artifacts(id,owner,job_id,source,target,state,reason,device,inode,size,mtime,created,updated)
                VALUES(?,?,?,?,?,'pending',?,?,?,?,?,?,?)''',
                (ident,job['owner'],job['id'],name,ident+'.artifact',reason,*_identity(meta),now,now))
            return dict(db.execute('SELECT * FROM export_artifacts WHERE id=?',(ident,)).fetchone())

    def _finish(self,row,state,now):
        with self._db(write=True) as db:
            db.execute("UPDATE export_artifacts SET state=?,updated=? WHERE id=? AND state='pending'",(state,now,row['id']))

    def _allowed_now(self,row,active,now):
        job=self._job(row['job_id'])
        if not job or job['owner']!=row['owner']:return False
        if row['reason']=='terminal_unpublished':return job['state'] in ('failed','cancelled')
        if row['reason']=='superseded_attempt':
            match=_NAME.fullmatch(row['source'])
            return bool(match and match['worker'] and job['state']=='running' and
                        active==(job['id'],job['worker']) and match['worker']!=job['worker'])
        if row['reason'] in ('redundant_completed_link','completed_attempt_staging') and job['state']=='completed':
            return any((meta:=_regular(self.store.output_dir/(job['id']+'.'+suffix))) is not None and meta.st_size==job['bytes'] for suffix in ('csv','xlsx','pdf'))
        return False

    def _move(self,row,active,now):
        # Database fields are not allowed to select arbitrary paths.
        match=_NAME.fullmatch(row['source'])
        if not match or match['job']!=row['job_id'] or row['target']!=row['id']+'.artifact' or not re.fullmatch('[a-f0-9]{32}',row['id']):
            self._finish(row,'conflict',now);return 'conflict'
        self._directories(create=True)
        source=self.store.output_dir/row['source'];target=self.directory/row['target']
        source_ok=_same(source,row);target_ok=_same(target,row)
        if target_ok and not source.exists() and not source.is_symlink():
            job=self._job(row['job_id'])
            if job and job['owner']==row['owner']:
                self._finish(row,'quarantined',now);return 'quarantined'
        if not self._allowed_now(row,active,now):
            self._finish(row,'protected',now);return 'protected'
        if target.exists() or target.is_symlink():
            if not target_ok:self._finish(row,'conflict',now);return 'conflict'
        elif source_ok:
            # No overwrite; never follow a source symlink. Identity is checked
            # again before either name is removed after a raced replacement.
            os.link(source,target,follow_symlinks=False)
            if not _same(target,row):self._finish(row,'conflict',now);return 'conflict'
            target_ok=True
        else:
            self._finish(row,'source_changed' if source.exists() or source.is_symlink() else 'missing',now)
            return 'protected'
        if source.exists() or source.is_symlink():
            if not _same(source,row):self._finish(row,'source_changed',now);return 'protected'
            if not self._allowed_now(row,active,now):
                self._finish(row,'protected',now);return 'protected'
            if not _same(source,row):
                self._finish(row,'source_changed',now);return 'protected'
            source.unlink()
        if target_ok:
            if os.name!='nt':
                for directory in (self.directory,self.store.output_dir):
                    fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|getattr(os,'O_NOFOLLOW',0))
                    try:os.fsync(fd)
                    finally:os.close(fd)
            self._finish(row,'quarantined',now);return 'quarantined'
        return 'protected'

    def run_once(self,*,active=None,max_entries=20,max_seconds=.1,now=None):
        if type(max_entries) is not int or not 1<=max_entries<=100 or not 0<max_seconds<=1:
            raise ValueError('invalid_export_recovery_budget')
        now=time.time() if now is None else float(now)
        deadline=time.monotonic()+max_seconds;self.deadline=deadline
        summary=dict(state='ready',examined=0,quarantined=0,conflicts=0,scan_complete=False)
        try:
            self._directories()
            with self._db() as db:
                pending=[dict(row) for row in db.execute("SELECT * FROM export_artifacts WHERE state='pending' ORDER BY created,id LIMIT 10")]
            for row in pending:
                if summary['examined']>=max_entries or time.monotonic()>=deadline:break
                summary['examined']+=1
                state=self._move(row,active,now)
                summary['quarantined']+=state=='quarantined';summary['conflicts']+=state=='conflict'
            if self.iterator is None:self.iterator=os.scandir(self.store.output_dir)
            while summary['examined']<max_entries and time.monotonic()<deadline:
                try:entry=next(self.iterator)
                except StopIteration:
                    self.close();summary['scan_complete']=True;break
                summary['examined']+=1
                match=_NAME.fullmatch(entry.name)
                if not match:continue
                meta=_regular(self.store.output_dir/entry.name)
                if meta is None:continue
                job=self._job(match['job'])
                reason=self._eligible(entry.name,meta,job,active,now)
                if reason:
                    row=self._intent(entry.name,meta,job,reason,now)
                    if row:
                        state=self._move(row,active,now)
                        summary['quarantined']+=state=='quarantined';summary['conflicts']+=state=='conflict'
        except _BudgetExpired:
            summary['budget_exhausted']=True
        except sqlite3.Error as error:
            if time.monotonic()>=deadline or 'interrupt' in str(error).lower():
                # A normal cooperative budget boundary must not restart every
                # scan at the beginning and starve files later in the directory.
                summary['budget_exhausted']=True
            else:self.close();summary['state']='unavailable'
        except (OSError,ValueError,RuntimeError):
            self.close();summary['state']='unavailable'
        finally:self.deadline=None
        return summary


def owner_artifacts(store,owner,limit=20):
    """Metadata only: quarantine has deliberately no web download/restore route."""
    if not isinstance(owner,str) or not 1<=len(owner)<=128 or type(limit) is not int or not 1<=limit<=20:
        raise ValueError('invalid_export_recovery_owner')
    with store._db() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='export_artifacts' AND type='table'").fetchone():return []
        deadline=time.monotonic()+.2
        db.set_progress_handler(lambda:int(time.monotonic()>=deadline),100)
        return [dict(row) for row in db.execute('''SELECT id,job_id,state,reason,size,created FROM export_artifacts
            WHERE owner=? ORDER BY created DESC,id DESC LIMIT ?''',(owner,limit))]
