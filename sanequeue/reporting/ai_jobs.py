"""Private durable ASR/analysis queue; no models, audio files or PBX access.

HTTP adapters authorize source ownership before creation and every later read.
Worker adapters reauthorize the immutable queue/source specification. Stored
text is untrusted plain text and must never be inserted into HTML unescaped.
Use a fresh random worker token for each claim, never a reusable process name.
"""
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
import uuid

from .store import QueryDeadline

_ID=re.compile(r'[0-9a-f]{32}\Z')
_OPAQUE=re.compile(r'[A-Za-z0-9_.:-]{1,512}\Z')
_REASONS={'processing_failed','source_unavailable','resource_limit','timeout','access_revoked',
          'invalid_audio','model_unavailable','result_invalid','lease_expired','cancelled',
          'system_busy','disk_pressure','module_disabled','source_not_ready','model_not_ready'}


class AIConflict(RuntimeError):pass
class AIUnavailable(RuntimeError):pass


def _text(value,maximum,label):
    if not isinstance(value,str) or not 1<=len(value)<=maximum or not value.strip() or not value.isprintable():
        raise ValueError('invalid_ai_'+label)
    return value


def _opaque(value,label):
    if not isinstance(value,str) or not _OPAQUE.fullmatch(value):raise ValueError('invalid_ai_'+label)
    return value


def _id(value):
    if not isinstance(value,str) or not _ID.fullmatch(value):raise ValueError('invalid_ai_job_id')
    return value


def _number(value,low,high,label):
    if isinstance(value,bool) or not isinstance(value,(int,float)):raise ValueError('invalid_ai_'+label)
    try:valid=math.isfinite(value) and low<=value<=high
    except OverflowError:valid=False
    if not valid:raise ValueError('invalid_ai_'+label)
    return float(value)


def _reason(value):
    if not isinstance(value,str) or value not in _REASONS:raise ValueError('invalid_ai_reason')
    return value


def _json(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)


def _result(value,maximum_seconds):
    if not isinstance(value,dict) or set(value)-{'text','segments','normalized_text','analysis'} or 'text' not in value or 'segments' not in value:
        raise ValueError('invalid_ai_result')
    text_bytes=0
    def text(value):
        nonlocal text_bytes
        if not isinstance(value,str) or len(value)>1024*1024:raise ValueError('invalid_ai_result_text')
        size=len(value.encode('utf-8'))
        if size>1024*1024:raise ValueError('invalid_ai_result_text')
        text_bytes+=size
        if text_bytes>2*1024*1024:raise ValueError('ai_result_byte_limit')
        return value
    raw=text(value['text']);normalized=text(value.get('normalized_text',raw))
    segments=value['segments']
    if not isinstance(segments,list) or len(segments)>10000:raise ValueError('invalid_ai_result_segments')
    clean=[];last_start=-1
    for segment in segments:
        if not isinstance(segment,dict) or set(segment)!={'start','end','text'}:raise ValueError('invalid_ai_result_segment')
        start=_number(segment['start'],0,min(3600,maximum_seconds),'segment_offset')
        end=_number(segment['end'],start,min(3600,maximum_seconds),'segment_offset')
        if start<last_start:raise ValueError('invalid_ai_segment_order')
        last_start=start;clean.append(dict(start=start,end=end,text=text(segment['text'])))
    analysis=value.get('analysis',{})
    if not isinstance(analysis,dict):raise ValueError('invalid_ai_analysis')
    count=0
    def inspect(item,depth=0):
        nonlocal count
        count+=1
        if depth>12 or count>20000:raise ValueError('invalid_ai_analysis_complexity')
        if item is None or isinstance(item,bool):return
        if isinstance(item,str):text(item);return
        if isinstance(item,(int,float)):
            try:finite=math.isfinite(item)
            except OverflowError:finite=False
            if not finite:raise ValueError('invalid_ai_analysis_number')
            return
        if isinstance(item,list):
            for child in item:inspect(child,depth+1)
        elif isinstance(item,dict):
            for key,child in item.items():
                if not isinstance(key,str) or len(key)>128:raise ValueError('invalid_ai_analysis_key')
                text(key)
                inspect(child,depth+1)
        else:raise ValueError('invalid_ai_analysis_type')
    inspect(analysis)
    result=dict(text=raw,segments=clean,normalized_text=normalized,analysis=analysis)
    payload=_json(result)
    if len(payload.encode('utf-8'))>2*1024*1024:raise ValueError('ai_result_byte_limit')
    return payload


class AIJobs:
    def __init__(self,path,pbx='primary'):
        self.path=Path(path).absolute();self.pbx=_text(pbx,128,'pbx')

    def initialize(self):
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            if self.path.is_symlink():raise OSError('ai_symlink')
            fd=os.open(self.path,os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0),0o600)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):raise OSError('ai_not_regular')
                if os.name!='nt':os.fchmod(fd,0o600)
            finally:os.close(fd)
            with self._db(write=True) as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'").fetchone():raise OSError('ai_is_archive')
                db.commit()
                if db.execute('PRAGMA journal_mode=WAL').fetchone()[0].lower()!='wal':raise OSError('ai_wal_unavailable')
                db.executescript('''CREATE TABLE IF NOT EXISTS ai_jobs(
                  sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,pbx TEXT NOT NULL,
                  owner TEXT NOT NULL,state TEXT NOT NULL,spec TEXT NOT NULL,spec_hash TEXT NOT NULL,
                  request_key TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,available_at REAL NOT NULL,
                  worker TEXT,lease_until REAL,attempts INTEGER NOT NULL DEFAULT 0,progress REAL NOT NULL DEFAULT 0,
                  error TEXT,result TEXT,UNIQUE(pbx,owner,request_key));
                  CREATE INDEX IF NOT EXISTS aj_queue ON ai_jobs(pbx,state,available_at,sequence);
                  CREATE INDEX IF NOT EXISTS aj_owner ON ai_jobs(pbx,owner,sequence);
                  CREATE TRIGGER IF NOT EXISTS aj_spec_immutable BEFORE UPDATE OF id,pbx,owner,spec,spec_hash,request_key,created ON ai_jobs
                    BEGIN SELECT RAISE(ABORT,'immutable_ai_spec'); END;''')
        except (OSError,sqlite3.Error):raise AIUnavailable('ai_job_store_unavailable') from None

    @contextmanager
    def _db(self,write=False):
        db=None
        try:
            if self.path.is_symlink() or not self.path.is_file():raise OSError('ai_missing')
            if os.name!='nt' and self.path.stat().st_mode&0o077:raise OSError('ai_permissions')
            db=sqlite3.connect(self.path.as_uri()+('?mode=rw' if write else '?mode=ro'),uri=True,timeout=.25)
            db.row_factory=sqlite3.Row;db.execute('PRAGMA trusted_schema=OFF')
            if write:db.execute('PRAGMA synchronous=FULL');db.execute('BEGIN IMMEDIATE')
            else:
                deadline=time.monotonic()+.5;db.set_progress_handler(lambda:int(time.monotonic()>=deadline),100)
                db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            with db:yield db
        except sqlite3.OperationalError as error:
            if 'interrupt' in str(error).lower():raise QueryDeadline('ai_job_query_deadline') from None
            raise AIUnavailable('ai_job_store_unavailable') from None
        except (OSError,sqlite3.Error):raise AIUnavailable('ai_job_store_unavailable') from None
        finally:
            if db is not None:db.close()

    @staticmethod
    def _public(row,worker=False):
        if row is None:return None
        if hashlib.sha256(row['spec'].encode()).hexdigest()!=row['spec_hash']:raise AIUnavailable('ai_job_spec_integrity')
        result={key:row[key] for key in ('id','state','created','updated','attempts','progress','error')}
        result['spec']=json.loads(row['spec'])
        result['result']=json.loads(row['result']) if row['state']=='completed' and row['result'] is not None else None
        if worker:result.update(worker=row['worker'],lease_until=row['lease_until'])
        return result

    def create(self,owner,visit_id,recording_id,queue,language,request_key,*,maximum_seconds=1800,queues=None):
        owner=_text(owner,128,'owner');visit_id=_opaque(visit_id,'visit_id');recording_id=_opaque(recording_id,'recording_id')
        queue=_text(queue,128,'queue');request_key=_text(request_key,128,'request_key')
        if language not in ('fa','en'):raise ValueError('invalid_ai_language')
        maximum_seconds=_number(maximum_seconds,1,1800,'maximum_seconds')
        queues=[queue] if queues is None else queues
        if not isinstance(queues,(list,tuple)) or not 1<=len(queues)<=256:raise ValueError('invalid_ai_queue_scope')
        queues=sorted(set(_text(value,128,'queue') for value in queues))
        if queue not in queues:raise ValueError('invalid_ai_queue_scope')
        payload=_json(dict(owner=owner,visit_id=visit_id,recording_id=recording_id,queue=queue,language=language,
                           maximum_seconds=maximum_seconds,pbx=self.pbx,queues=queues))
        fingerprint=hashlib.sha256(payload.encode()).hexdigest();now=time.time()
        with self._db(write=True) as db:
            prior=db.execute('SELECT * FROM ai_jobs WHERE pbx=? AND owner=? AND request_key=?',(self.pbx,owner,request_key)).fetchone()
            if prior:
                if prior['spec_hash']!=fingerprint:raise AIConflict('ai_request_key_reused')
                return self._public(prior)
            quotas=db.execute("SELECT COUNT(*),COALESCE(SUM(owner=?),0) FROM ai_jobs WHERE state IN ('queued','running')",(owner,)).fetchone()
            if quotas[0]>=10 or quotas[1]>=3:raise AIConflict('ai_job_quota')
            ident=uuid.uuid4().hex
            db.execute('''INSERT INTO ai_jobs(id,pbx,owner,state,spec,spec_hash,request_key,created,updated,available_at)
              VALUES(?,?,?,'queued',?,?,?,?,?,?)''',(ident,self.pbx,owner,payload,fingerprint,request_key,now,now,now))
            return self._public(db.execute('SELECT * FROM ai_jobs WHERE id=?',(ident,)).fetchone())

    def get(self,ident,owner):
        _id(ident);owner=_text(owner,128,'owner')
        with self._db() as db:return self._public(db.execute('SELECT * FROM ai_jobs WHERE pbx=? AND id=? AND owner=?',(self.pbx,ident,owner)).fetchone())

    def list(self,owner,limit=100):
        owner=_text(owner,128,'owner')
        if isinstance(limit,bool) or not isinstance(limit,int) or limit<1:raise ValueError('invalid_ai_limit')
        with self._db() as db:
            return [self._public(row) for row in db.execute('SELECT id,state,created,updated,attempts,progress,error,spec,spec_hash,NULL result FROM ai_jobs WHERE pbx=? AND owner=? ORDER BY sequence DESC LIMIT ?',
                                                           (self.pbx,owner,min(100,limit)))]

    def claim(self,worker,lease=60,*,now=None):
        worker=_text(worker,128,'worker');lease=_number(lease,5,300,'lease')
        now=time.time() if now is None else _number(now,0,1e12,'now')
        with self._db(write=True) as db:
            db.execute("""UPDATE ai_jobs SET state=CASE WHEN attempts>=3 THEN 'failed' ELSE 'queued' END,
                available_at=?,updated=?,worker=NULL,lease_until=NULL,progress=0,result=NULL,error='lease_expired'
                WHERE pbx=? AND state='running' AND lease_until<?""",(now,now,self.pbx,now))
            row=db.execute("SELECT * FROM ai_jobs WHERE pbx=? AND state='queued' AND available_at<=? ORDER BY sequence LIMIT 1",(self.pbx,now)).fetchone()
            if row is None:return None
            db.execute("UPDATE ai_jobs SET state='running',worker=?,lease_until=?,attempts=attempts+1,updated=?,error=NULL WHERE id=?",
                       (worker,now+lease,now,row['id']))
            return self._public(db.execute('SELECT * FROM ai_jobs WHERE id=?',(row['id'],)).fetchone(),worker=True)

    def update_progress(self,ident,worker,progress,*,lease=60):
        _id(ident);worker=_text(worker,128,'worker');progress=_number(progress,0,100,'progress');lease=_number(lease,5,300,'lease');now=time.time()
        with self._db(write=True) as db:
            return db.execute("UPDATE ai_jobs SET progress=?,updated=?,lease_until=? WHERE pbx=? AND id=? AND state='running' AND worker=? AND lease_until>=? AND progress<=?",
                (progress,now,now+lease,self.pbx,ident,worker,now,progress)).rowcount==1

    def complete(self,ident,worker,result):
        _id(ident);worker=_text(worker,128,'worker');now=time.time()
        with self._db(write=True) as db:
            row=db.execute("SELECT * FROM ai_jobs WHERE pbx=? AND id=? AND state='running' AND worker=? AND lease_until>=?",(self.pbx,ident,worker,now)).fetchone()
            if row is None:return False
            payload=_result(result,json.loads(row['spec'])['maximum_seconds'])
            return db.execute("UPDATE ai_jobs SET state='completed',result=?,progress=100,error=NULL,worker=NULL,lease_until=NULL,updated=? WHERE id=?",
                              (payload,now,ident)).rowcount==1

    def fail(self,ident,worker,reason):
        _id(ident);worker=_text(worker,128,'worker');_reason(reason);now=time.time()
        with self._db(write=True) as db:
            return db.execute("UPDATE ai_jobs SET state='failed',error=?,result=NULL,worker=NULL,lease_until=NULL,updated=? WHERE pbx=? AND id=? AND state='running' AND worker=? AND lease_until>=?",
                (reason,now,self.pbx,ident,worker,now)).rowcount==1

    def defer(self,ident,worker,reason='system_busy',delay=30):
        _id(ident);worker=_text(worker,128,'worker');_reason(reason);delay=_number(delay,1,3600,'defer_delay');now=time.time()
        with self._db(write=True) as db:
            return db.execute("UPDATE ai_jobs SET state='queued',available_at=?,attempts=MAX(0,attempts-1),progress=0,error=?,result=NULL,worker=NULL,lease_until=NULL,updated=? WHERE pbx=? AND id=? AND state='running' AND worker=? AND lease_until>=?",
                (now+delay,reason,now,self.pbx,ident,worker,now)).rowcount==1

    def cancel(self,ident,owner):
        _id(ident);owner=_text(owner,128,'owner')
        with self._db(write=True) as db:
            return db.execute("UPDATE ai_jobs SET state='cancelled',result=NULL,error='cancelled',worker=NULL,lease_until=NULL,updated=? WHERE pbx=? AND id=? AND owner=? AND state IN ('queued','running')",
                (time.time(),self.pbx,ident,owner)).rowcount==1
