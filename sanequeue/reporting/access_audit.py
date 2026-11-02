"""Private request-level audio audit, separate from the reporting archive.

An entry records a play/download request, not proof that a human listened.
Callers must deny audio if append raises AuditUnavailable. Deduplication uses
fixed thirty-second buckets and pagination follows insertion sequence rather
than wall time, which can move backwards. Startup explicitly initializes it.
"""
import base64
from contextlib import contextmanager
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import struct
import time
import uuid

_ACTIONS={'play_request','download_request'}
_WRITE_TIMEOUT=.1
_READ_SECONDS=.25
_CURSOR=re.compile(r'[A-Za-z0-9_-]{12}\Z')


class AuditUnavailable(RuntimeError):
    """Audit persistence could not be proven; audio must remain denied."""


def _text(value,maximum,label):
    if not isinstance(value,str) or not 1<=len(value)<=maximum or not value.strip() or not value.isprintable():
        raise ValueError('invalid_audit_'+label)
    return value


def _cursor(sequence):
    return base64.urlsafe_b64encode(struct.pack('>BQ',1,sequence)).decode('ascii')


def _sequence(cursor):
    if not isinstance(cursor,str) or not _CURSOR.fullmatch(cursor):raise ValueError('invalid_audit_cursor')
    try:
        version,value=struct.unpack('>BQ',base64.b64decode(cursor,altchars=b'-_',validate=True))
    except (ValueError,struct.error):raise ValueError('invalid_audit_cursor') from None
    if version!=1 or not 0<value<=9223372036854775807:raise ValueError('invalid_audit_cursor')
    return value


class AuditStore:
    def __init__(self,path):
        self.path=Path(path).absolute()

    def initialize(self):
        """Only startup may create the database; requests open it mode=rw/ro."""
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            if self.path.is_symlink():raise OSError('invalid_audit_file')
            fd=os.open(self.path,os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0),0o600)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):raise OSError('invalid_audit_file')
                if os.name!='nt':os.fchmod(fd,0o600)
            finally:os.close(fd)
            with self._db(write=True) as db:
                # Refuse a mistaken configuration pointing at the raw archive.
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'").fetchone():
                    raise OSError('audit_database_is_archive')
                db.commit()
                if db.execute('PRAGMA journal_mode=WAL').fetchone()[0].lower()!='wal':
                    raise OSError('audit_wal_unavailable')
                db.executescript('''CREATE TABLE IF NOT EXISTS recording_access(
                  sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,
                  user TEXT NOT NULL,recording TEXT NOT NULL,timestamp REAL NOT NULL,
                  action TEXT NOT NULL,bucket INTEGER NOT NULL,
                  UNIQUE(user,recording,action,bucket));
                  CREATE INDEX IF NOT EXISTS ra_access_time ON recording_access(recording,timestamp,sequence);
                  CREATE INDEX IF NOT EXISTS ra_access_cursor ON recording_access(recording,sequence);''')
        except (OSError,sqlite3.Error):raise AuditUnavailable('recording_audit_unavailable') from None

    @contextmanager
    def _db(self,*,write=False):
        db=None
        try:
            if self.path.is_symlink() or not self.path.is_file():raise OSError('invalid_audit_file')
            if os.name!='nt' and self.path.stat().st_mode&0o077:raise OSError('audit_file_permissions')
            mode='rw' if write else 'ro'
            db=sqlite3.connect(self.path.as_uri()+'?mode='+mode,uri=True,timeout=_WRITE_TIMEOUT)
            db.row_factory=sqlite3.Row
            db.execute('PRAGMA trusted_schema=OFF')
            if write:
                db.execute('PRAGMA synchronous=FULL')
                db.execute('BEGIN IMMEDIATE')
            else:
                deadline=time.monotonic()+_READ_SECONDS
                db.set_progress_handler(lambda:int(time.monotonic()>=deadline),100)
                db.execute('PRAGMA query_only=ON')
                db.execute('BEGIN')
            with db:yield db
        except (OSError,sqlite3.Error):raise AuditUnavailable('recording_audit_unavailable') from None
        finally:
            if db is not None:db.close()

    def append(self,owner,recording_id,action,*,now=None):
        owner=_text(owner,128,'owner');recording_id=_text(recording_id,512,'recording')
        if not isinstance(action,str) or action not in _ACTIONS:raise ValueError('invalid_audit_action')
        now=time.time() if now is None else now
        if isinstance(now,bool) or not isinstance(now,(int,float)) or not math.isfinite(now) or not 0<=now<=32503680000:
            raise ValueError('invalid_audit_timestamp')
        bucket=math.floor(now/30)
        with self._db(write=True) as db:
            result=db.execute('''INSERT OR IGNORE INTO recording_access(id,user,recording,timestamp,action,bucket)
              VALUES(?,?,?,?,?,?)''',(uuid.uuid4().hex,owner,recording_id,float(now),action,bucket))
            row=db.execute('''SELECT id,user,timestamp,action FROM recording_access
              WHERE user=? AND recording=? AND action=? AND bucket=?''',(owner,recording_id,action,bucket)).fetchone()
            if row is None:raise AuditUnavailable('recording_audit_unavailable')
            answer=dict(row);answer['created']=result.rowcount==1
        # Return only after the synchronous transaction committed successfully.
        return answer

    def page(self,recording_id,before=None,limit=50):
        recording_id=_text(recording_id,512,'recording')
        if isinstance(limit,bool) or isinstance(limit,float) and not limit.is_integer():raise ValueError('invalid_audit_limit')
        try:limit=int(limit)
        except (TypeError,ValueError,OverflowError):raise ValueError('invalid_audit_limit') from None
        if limit<1:raise ValueError('invalid_audit_limit')
        limit=min(100,limit)
        clause='recording=?';args=[recording_id]
        if before is not None:
            clause+=' AND sequence<?';args.append(_sequence(before))
        with self._db() as db:
            rows=db.execute('SELECT sequence,id,user,timestamp,action FROM recording_access WHERE '+
                            clause+' ORDER BY sequence DESC LIMIT ?',(*args,limit+1)).fetchall()
        more=len(rows)>limit;rows=rows[:limit]
        return dict(rows=[{key:row[key] for key in ('id','user','timestamp','action')} for row in rows],
                    next=_cursor(rows[-1]['sequence']) if more and rows else None)
