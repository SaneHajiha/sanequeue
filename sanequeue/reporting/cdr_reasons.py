"""Private human classifications attached to observed CDR segment keys.

Labels are declared by an operator, not inferred call causes. The HTTP layer
must separately authorize the referenced CDR and the current user.
"""
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import stat
import time
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo
from .exports import persian_date
from .store import QueryDeadline


class ReasonUnavailable(RuntimeError):pass


def _text(value,maximum):
    if not isinstance(value,str) or len(value)>maximum or value and not value.isprintable():raise ValueError('invalid_cdr_reason')
    return value.strip()


def _key(value):
    clean=_text(value,512)
    if not clean or clean!=value:raise ValueError('invalid_cdr_reason_key')
    return clean


class Reasons:
    def __init__(self,path,pbx='primary'):
        self.path=Path(path).absolute();self.pbx=_text(pbx,120)
        if not self.pbx:raise ValueError('invalid_cdr_reason_pbx')

    def initialize(self):
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            if self.path.is_symlink():raise OSError('symlink')
            fd=os.open(self.path,os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0),0o600)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):raise OSError('not_regular')
                if os.name!='nt':os.fchmod(fd,0o600)
            finally:os.close(fd)
            with closing(self.connect()) as db, db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'").fetchone():raise ReasonUnavailable('wrong_database')
                db.executescript('''CREATE TABLE IF NOT EXISTS cdr_reason_meta(pbx TEXT PRIMARY KEY,revision INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS cdr_reason_current(pbx TEXT,source_key TEXT,reason TEXT,subreason TEXT,outcome TEXT,
                  actor TEXT,updated REAL,PRIMARY KEY(pbx,source_key));
                CREATE TABLE IF NOT EXISTS cdr_reason_audit(pbx TEXT,source_key TEXT,reason TEXT,subreason TEXT,outcome TEXT,
                  actor TEXT,updated REAL);
                CREATE TABLE IF NOT EXISTS cdr_reason_catalog(pbx TEXT,reason TEXT,subreason TEXT,active INTEGER NOT NULL,
                  PRIMARY KEY(pbx,reason,subreason));
                CREATE TABLE IF NOT EXISTS cdr_reason_catalog_audit(pbx TEXT,reason TEXT,subreason TEXT,active INTEGER NOT NULL,
                  actor TEXT NOT NULL,updated REAL NOT NULL);''')
                db.execute('INSERT OR IGNORE INTO cdr_reason_meta VALUES(?,0)',(self.pbx,))
        except (sqlite3.Error,OSError) as error:raise ReasonUnavailable('cdr_reason_unavailable') from error

    def connect(self):
        if not self.path.is_file() or self.path.is_symlink():raise ReasonUnavailable('cdr_reason_unavailable')
        try:
            db=sqlite3.connect(self.path.as_uri()+'?mode=rw',uri=True,timeout=2)
            db.row_factory=sqlite3.Row;return db
        except (sqlite3.Error,OSError) as error:raise ReasonUnavailable('cdr_reason_unavailable') from error

    def get(self,key):
        key=_key(key)
        with closing(self.connect()) as db:
            row=db.execute('SELECT reason,subreason,outcome FROM cdr_reason_current WHERE pbx=? AND source_key=?',(self.pbx,key)).fetchone()
        return dict(row) if row else dict(reason='',subreason='',outcome='')

    def catalog(self):
        with closing(self.connect()) as db:
            rows=db.execute('SELECT reason,subreason FROM cdr_reason_catalog WHERE pbx=? AND active=1 ORDER BY reason,subreason LIMIT 501',(self.pbx,)).fetchall()
        if len(rows)>500:raise ReasonUnavailable('cdr_reason_catalog_limit')
        return [dict(row) for row in rows]

    def set_catalog(self,reason,subreason,active,actor):
        reason=_text(reason,120);subreason=_text(subreason,120);actor=_text(actor,120)
        if not reason or not actor or type(active) is not bool:raise ValueError('invalid_cdr_reason_catalog')
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            exists=db.execute('SELECT 1 FROM cdr_reason_catalog WHERE pbx=? AND reason=? AND subreason=?',(self.pbx,reason,subreason)).fetchone()
            count=db.execute('SELECT COUNT(*) FROM cdr_reason_catalog WHERE pbx=?',(self.pbx,)).fetchone()[0]
            if not exists and count>=500:raise ValueError('cdr_reason_catalog_limit')
            db.execute('INSERT OR REPLACE INTO cdr_reason_catalog VALUES(?,?,?,?)',(self.pbx,reason,subreason,int(active)))
            db.execute('INSERT INTO cdr_reason_catalog_audit VALUES(?,?,?,?,?,?)',(self.pbx,reason,subreason,int(active),actor,time.time()))
        return self.catalog()

    def set(self,key,reason,subreason,outcome,actor):
        key=_key(key);actor=_text(actor,120);reason=_text(reason,120);subreason=_text(subreason,120);outcome=_text(outcome,120)
        if not key or not actor or subreason and not reason:raise ValueError('invalid_cdr_reason')
        now=time.time()
        with closing(self.connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            values=(self.pbx,key,reason,subreason,outcome,actor,now)
            db.execute('INSERT OR REPLACE INTO cdr_reason_current VALUES(?,?,?,?,?,?,?)',values)
            db.execute('INSERT INTO cdr_reason_audit VALUES(?,?,?,?,?,?,?)',values)
            db.execute('UPDATE cdr_reason_meta SET revision=revision+1 WHERE pbx=?',(self.pbx,))
        return dict(reason=reason,subreason=subreason,outcome=outcome)

    def summarize(self,keys,*,timestamps=None,bucket=None):
        if not isinstance(keys,list) or len(keys)>50000:raise QueryDeadline('cdr_reason_segment_limit')
        if bucket is not None and (bucket not in ('hour','weekday','day','month') or not isinstance(timestamps,list) or len(timestamps)!=len(keys)):
            raise ValueError('invalid_cdr_reason_bucket')
        counts=Counter();found={}
        with closing(self.connect()) as db:
            db.execute('BEGIN')
            revision=db.execute('SELECT revision FROM cdr_reason_meta WHERE pbx=?',(self.pbx,)).fetchone()
            if revision is None:raise ReasonUnavailable('cdr_reason_unavailable')
            for i in range(0,len(keys),400):
                chunk=keys[i:i+400]
                for row in db.execute('SELECT source_key,reason,subreason,outcome FROM cdr_reason_current WHERE pbx=? AND source_key IN ('+','.join('?' for _ in chunk)+')',(self.pbx,*chunk)):
                    found[row['source_key']]=(row['reason'],row['subreason'],row['outcome'])
            db.commit()
        for key in keys:
            label=found.get(key,('','',''));counts[label]+=1
            if len(counts)>1000:raise QueryDeadline('cdr_reason_group_limit')
        rows=[dict(reason=k[0],subreason=k[1],outcome=k[2],is_labeled=bool(k[0]),count=v) for k,v in sorted(counts.items(),key=lambda item:(-item[1],item[0]))]
        labelled=sum(row['count'] for row in rows if row['reason'])
        result=dict(rows=rows,segments=len(keys),labelled=labelled,unlabelled=len(keys)-labelled,unit='cdr_segment',complete_history=False)
        if bucket is not None:
            timeline=Counter();zone=ZoneInfo('Asia/Tehran')
            for key,stamp in zip(keys,timestamps):
                local=datetime.fromtimestamp(stamp,zone)
                if bucket=='month' and not 1900<=local.year<=2099:raise ValueError('invalid_cdr_reason_calendar_range')
                period=(str(local.hour).zfill(2) if bucket=='hour' else str((local.weekday()+2)%7) if bucket=='weekday' else
                        local.date().isoformat() if bucket=='day' else persian_date(local.date())[:7])
                reason=found.get(key,('','',''))[0]
                timeline[(period,reason)]+=1
                if len(timeline)>5000:raise QueryDeadline('cdr_reason_timeline_limit')
            result['timeline']=[dict(period=key[0],reason=key[1],count=count) for key,count in sorted(timeline.items())]
            result['bucket']=bucket
        with closing(self.connect()) as db:
            latest=db.execute('SELECT revision FROM cdr_reason_meta WHERE pbx=?',(self.pbx,)).fetchone()
        if latest is None or latest[0]!=revision[0]:raise ReasonUnavailable('cdr_reason_changed')
        return result
