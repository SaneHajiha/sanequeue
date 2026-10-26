"""Explicit work sessions independent of queue membership and pause caches.

Session time is declared work time, not observed presence or unique talk time.
Call metrics count CDR segments started in the session, never linkedid groups.
HTTP adapters must authorize changes and mask call destinations before output.
"""
import base64
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import struct
import time
import uuid

from .queries import _scope, _where

_PURPOSES={'happy_call','survey'}
_ID=re.compile(r'[0-9a-f]{32}\Z')
_TOKEN=re.compile(r'[A-Za-z0-9_-]{12}\Z')


class SessionConflict(RuntimeError):
    pass


class SessionAccessDenied(PermissionError):
    pass


class SessionUnavailable(RuntimeError):
    pass


def _now():
    """Server clock isolated for deterministic tests without changing auth time."""
    return time.time()


def _text(value,maximum,label):
    if not isinstance(value,str) or not 1<=len(value)<=maximum or not value.strip() or not value.isprintable():
        raise ValueError('invalid_work_session_'+label)
    return value


def _ident(value):
    if not isinstance(value,str) or not _ID.fullmatch(value):raise ValueError('invalid_work_session_id')
    return value


def _limit(value):
    if isinstance(value,bool) or isinstance(value,float) and not value.is_integer():raise ValueError('invalid_work_session_limit')
    try:value=int(value)
    except (ValueError,TypeError,OverflowError):raise ValueError('invalid_work_session_limit') from None
    if value<1:raise ValueError('invalid_work_session_limit')
    return min(100,value)


def _cursor(sequence):
    return base64.urlsafe_b64encode(struct.pack('>BQ',1,sequence)).decode()


def _sequence(value):
    if not isinstance(value,str) or not _TOKEN.fullmatch(value):raise ValueError('invalid_work_session_cursor')
    try:version,sequence=struct.unpack('>BQ',base64.b64decode(value,altchars=b'-_',validate=True))
    except (ValueError,struct.error):raise ValueError('invalid_work_session_cursor') from None
    if version!=1 or not 0<sequence<=9223372036854775807:raise ValueError('invalid_work_session_cursor')
    return sequence


def _check_scope(scope):
    _scope('primary',scope)
    if not math.isfinite(float(scope.not_before)) or scope.not_before<0:raise ValueError('invalid_work_session_cutoff')


def _authorized(session,scope):
    _check_scope(scope)
    if not isinstance(session,dict):return False
    queues=session.get('queues')
    if not queues or not set(queues).issubset(scope.queues):return False
    if scope.self_only and (session.get('agent') not in scope.agents or session.get('started_at',0)<scope.not_before):return False
    return True


class WorkSessions:
    def __init__(self,path,pbx='primary'):
        self.path=Path(path).absolute();self.pbx=_text(pbx,128,'pbx')

    def initialize(self):
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            if self.path.is_symlink():raise OSError('invalid_session_file')
            fd=os.open(self.path,os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0),0o600)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):raise OSError('invalid_session_file')
                if os.name!='nt':os.fchmod(fd,0o600)
            finally:os.close(fd)
            with self._db(write=True) as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'").fetchone():raise OSError('session_database_is_archive')
                db.commit()
                if db.execute('PRAGMA journal_mode=WAL').fetchone()[0].lower()!='wal':raise OSError('session_wal_unavailable')
                db.executescript('''CREATE TABLE IF NOT EXISTS work_sessions(
                  sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,pbx TEXT NOT NULL,
                  actor TEXT NOT NULL,agent TEXT NOT NULL,purpose TEXT NOT NULL,title TEXT NOT NULL,
                  started_at REAL NOT NULL,ended_at REAL,closed_by TEXT,request_key TEXT NOT NULL,spec_hash TEXT NOT NULL,
                  UNIQUE(pbx,actor,request_key));
                  CREATE UNIQUE INDEX IF NOT EXISTS ws_one_open ON work_sessions(pbx,agent) WHERE ended_at IS NULL;
                  CREATE INDEX IF NOT EXISTS ws_agent_time ON work_sessions(pbx,agent,started_at,ended_at);
                  CREATE INDEX IF NOT EXISTS ws_cursor ON work_sessions(pbx,sequence);
                  CREATE TABLE IF NOT EXISTS work_session_queues(session_id TEXT,queue TEXT,
                    PRIMARY KEY(session_id,queue));
                  CREATE INDEX IF NOT EXISTS ws_queue ON work_session_queues(queue,session_id);''')
        except (OSError,sqlite3.Error):raise SessionUnavailable('work_session_store_unavailable') from None

    @contextmanager
    def _db(self,write=False):
        db=None
        try:
            if self.path.is_symlink() or not self.path.is_file():raise OSError('invalid_session_file')
            if os.name!='nt' and self.path.stat().st_mode&0o077:raise OSError('session_file_permissions')
            db=sqlite3.connect(self.path.as_uri()+('?mode=rw' if write else '?mode=ro'),uri=True,timeout=.1)
            db.row_factory=sqlite3.Row;db.execute('PRAGMA trusted_schema=OFF')
            if write:db.execute('PRAGMA synchronous=FULL');db.execute('BEGIN IMMEDIATE')
            else:
                deadline=time.monotonic()+.25
                db.set_progress_handler(lambda:int(time.monotonic()>=deadline),100)
                db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            with db:yield db
        except (OSError,sqlite3.Error):raise SessionUnavailable('work_session_store_unavailable') from None
        finally:
            if db is not None:db.close()

    @staticmethod
    def _public(row,queues):
        if row is None:return None
        return {key:row[key] for key in ('id','pbx','actor','agent','purpose','title','started_at','ended_at','closed_by')} | {
            'queues':list(queues),'state':'open' if row['ended_at'] is None else 'closed'}

    def open(self,actor,agent,purpose,title,queues,request_key):
        actor=_text(actor,128,'actor');agent=_text(agent,256,'agent')
        title=_text(title,160,'title').strip();request_key=_text(request_key,128,'request_key')
        if not isinstance(purpose,str) or purpose not in _PURPOSES:raise ValueError('invalid_work_session_purpose')
        if not isinstance(queues,(tuple,list,set)) or not 1<=len(queues)<=256:raise ValueError('invalid_work_session_queues')
        queues=tuple(sorted({_text(queue,128,'queue') for queue in queues}))
        specification=json.dumps([agent,purpose,title,queues],ensure_ascii=False,separators=(',',':'))
        fingerprint=hashlib.sha256(specification.encode()).hexdigest()
        with self._db(write=True) as db:
            prior=db.execute('SELECT * FROM work_sessions WHERE pbx=? AND actor=? AND request_key=?',(self.pbx,actor,request_key)).fetchone()
            if prior:
                if prior['spec_hash']!=fingerprint:raise SessionConflict('work_session_request_key_reused')
                return self._public(prior,queues)
            if db.execute('SELECT 1 FROM work_sessions WHERE pbx=? AND agent=? AND ended_at IS NULL',(self.pbx,agent)).fetchone():
                raise SessionConflict('work_session_already_open')
            now=_now()
            previous=db.execute('SELECT MAX(ended_at) FROM work_sessions WHERE pbx=? AND agent=?',(self.pbx,agent)).fetchone()[0]
            if previous is not None and now<previous:raise SessionConflict('work_session_clock_regressed')
            ident=uuid.uuid4().hex
            db.execute('''INSERT INTO work_sessions(id,pbx,actor,agent,purpose,title,started_at,request_key,spec_hash)
              VALUES(?,?,?,?,?,?,?,?,?)''',(ident,self.pbx,actor,agent,purpose,title,now,request_key,fingerprint))
            db.executemany('INSERT INTO work_session_queues VALUES(?,?)',[(ident,queue) for queue in queues])
            row=db.execute('SELECT * FROM work_sessions WHERE id=?',(ident,)).fetchone()
            return self._public(row,queues)

    def close(self,ident,actor):
        _ident(ident);actor=_text(actor,128,'actor')
        with self._db(write=True) as db:
            row=db.execute('SELECT * FROM work_sessions WHERE pbx=? AND id=?',(self.pbx,ident)).fetchone()
            if row is None:return None
            if row['ended_at'] is None:
                now=_now()
                if now<row['started_at']:raise SessionConflict('work_session_clock_regressed')
                db.execute('UPDATE work_sessions SET ended_at=?,closed_by=? WHERE id=?',(now,actor,ident))
                row=db.execute('SELECT * FROM work_sessions WHERE id=?',(ident,)).fetchone()
            queues=[r[0] for r in db.execute('SELECT queue FROM work_session_queues WHERE session_id=? ORDER BY queue',(ident,))]
            return self._public(row,queues)

    def _clause(self,scope):
        _check_scope(scope)
        if not scope.queues:return 's.pbx=? AND 0',[self.pbx]
        clause='s.pbx=? AND EXISTS (SELECT 1 FROM work_session_queues q WHERE q.session_id=s.id) AND NOT EXISTS (SELECT 1 FROM work_session_queues q WHERE q.session_id=s.id AND q.queue NOT IN ('+','.join('?' for _ in scope.queues)+'))'
        args=[self.pbx,*scope.queues]
        if scope.self_only:
            if not scope.agents:return clause+' AND 0',args
            clause+=' AND s.agent IN ('+','.join('?' for _ in scope.agents)+') AND s.started_at>=?'
            args.extend((*scope.agents,scope.not_before))
        return clause,args

    def get(self,ident,scope):
        _ident(ident);clause,args=self._clause(scope)
        with self._db() as db:
            row=db.execute('SELECT s.* FROM work_sessions s WHERE '+clause+' AND s.id=?',(*args,ident)).fetchone()
            if row is None:return None
            queues=[r[0] for r in db.execute('SELECT queue FROM work_session_queues WHERE session_id=? ORDER BY queue',(ident,))]
            return self._public(row,queues)

    def list(self,scope,before=None,limit=50,state=None,purpose=None):
        limit=_limit(limit);clause,args=self._clause(scope)
        if before is not None:clause+=' AND s.sequence<?';args.append(_sequence(before))
        if state is not None:
            if not isinstance(state,str) or state not in ('open','closed'):raise ValueError('invalid_work_session_state')
            clause+=' AND s.ended_at IS '+('NULL' if state=='open' else 'NOT NULL')
        if purpose is not None:
            if not isinstance(purpose,str) or purpose not in _PURPOSES:raise ValueError('invalid_work_session_purpose')
            clause+=' AND s.purpose=?';args.append(purpose)
        with self._db() as db:
            rows=db.execute('SELECT s.* FROM work_sessions s WHERE '+clause+' ORDER BY s.sequence DESC LIMIT ?',(*args,limit+1)).fetchall()
            more=len(rows)>limit;rows=rows[:limit]
            queues={row['id']:[] for row in rows}
            if rows:
                for row in db.execute('SELECT session_id,queue FROM work_session_queues WHERE session_id IN ('+','.join('?' for _ in rows)+') ORDER BY queue',tuple(queues)):
                    queues[row[0]].append(row[1])
            return dict(rows=[self._public(row,queues[row['id']]) for row in rows],
                        next=_cursor(rows[-1]['sequence']) if more and rows else None)


def _range(archive,session,scope,start,end,direction):
    if not _authorized(session,scope):raise SessionAccessDenied('work_session_access_denied')
    if session.get('pbx')!=archive.pbx:raise SessionAccessDenied('work_session_access_denied')
    _where(archive.pbx,scope,start,end)
    if direction not in ('outbound','internal'):raise ValueError('invalid_work_session_direction')
    started=float(session['started_at']);ended=session['ended_at']
    if not math.isfinite(started) or started<0 or ended is not None and (not math.isfinite(float(ended)) or ended<started):
        raise ValueError('invalid_work_session_time')
    first=max(float(start),started,scope.not_before)
    last=min(float(end),time.time(),float(ended) if ended is not None else float('inf'))
    return first,last


def calls(archive,session,scope,start,end,direction='outbound',before=None,limit=100,ident=None):
    first,last=_range(archive,session,scope,start,end,direction);limit=_limit(limit)
    result=dict(rows=[],next=None,start=first,end=last,direction=direction,unit='cdr_segment',
                duration_definition='full_segment_billsec_not_session_overlap',audio_granted=False)
    if before is not None:
        if not isinstance(before,(tuple,list)) or len(before)!=2 or not math.isfinite(float(before[0])) or not isinstance(before[1],str) or not 1<=len(before[1])<=512:
            raise ValueError('invalid_work_session_call_cursor')
    if ident is not None:_text(ident,512,'recording_id')
    if first>=last:return result
    clause='c.pbx=? AND p.agent=? AND p.direction=? AND c.ts>=? AND c.ts<?'
    args=[archive.pbx,session['agent'],direction,first,last]
    if ident is not None:clause+=' AND c.source_key=?';args.append(ident)
    if before is not None:
        clause+=' AND (c.ts<? OR (c.ts=? AND c.source_key<?))';args.extend((float(before[0]),float(before[0]),before[1]))
    with archive.reader() as db:
        rows=[dict(row) for row in db.execute('''SELECT c.source_key id,c.ts,c.dst destination,
          c.duration,c.billsec,c.disposition,p.agent,CASE WHEN c.recording<>'' THEN 1 ELSE 0 END has_recording
          FROM report_cdr c JOIN report_cdr_parties p ON p.pbx=c.pbx AND p.source_key=c.source_key
          WHERE '''+clause+' ORDER BY c.ts DESC,c.source_key DESC LIMIT ?',(*args,limit+1))]
    more=len(rows)>limit;rows=rows[:limit]
    result.update(rows=rows,next=[rows[-1]['ts'],rows[-1]['id']] if more and rows else None)
    return result


def summary(archive,session,scope,start,end,direction='outbound'):
    first,last=_range(archive,session,scope,start,end,direction)
    totals=dict(segments_started=0,answered_segments=0,unanswered_segments=0,unknown_disposition_segments=0,
                known_billsec_sum=0,known_billsec_count=0,unknown_billsec_count=0,
                answered_known_billsec_count=0,average_answered_billsec=None)
    result=dict(start=first,end=last,direction=direction,unit='cdr_segment',totals=totals,
                declared_seconds=max(0,last-first),time_basis='declared_session_not_observed_queue_presence',
                duration_definition='full_segment_billsec_not_session_overlap',complete_history=False,
                coverage='unknown_sql_coverage',sql_health=None,projection=None,stale=True,
                observed_until=None,source_gap=False,counts_are_observed=True)
    if first>=last:result['coverage']='outside_session_range';return result
    with archive.reader() as db:
        row=db.execute('''WITH matched AS (SELECT c.billsec,UPPER(TRIM(COALESCE(c.disposition,''))) disposition
          FROM report_cdr c JOIN report_cdr_parties p ON p.pbx=c.pbx AND p.source_key=c.source_key
          WHERE c.pbx=? AND p.agent=? AND p.direction=? AND c.ts>=? AND c.ts<?)
          SELECT COUNT(*) segments_started,COALESCE(SUM(disposition='ANSWERED'),0) answered_segments,
          COALESCE(SUM(disposition IN ('BUSY','NO ANSWER','FAILED','CONGESTION','CANCEL','CHANUNAVAIL')),0) unanswered_segments,
          COALESCE(SUM(disposition NOT IN ('ANSWERED','BUSY','NO ANSWER','FAILED','CONGESTION','CANCEL','CHANUNAVAIL')),0) unknown_disposition_segments,
          COALESCE(SUM(billsec),0) known_billsec_sum,COUNT(billsec) known_billsec_count,
          COUNT(*)-COUNT(billsec) unknown_billsec_count,
          COALESCE(SUM(disposition='ANSWERED' AND billsec IS NOT NULL),0) answered_known_billsec_count,
          AVG(CASE WHEN disposition='ANSWERED' THEN billsec END) average_answered_billsec FROM matched''',
          (archive.pbx,session['agent'],direction,first,last)).fetchone()
        result['totals']=dict(row)
        health=db.execute('SELECT value FROM checkpoints WHERE pbx=? AND source=?',(archive.pbx,'health:sql')).fetchone()
        raw=json.loads(health[0]) if health else {}
        if not isinstance(raw,dict):raw={}
        progress=raw.get('progress',{})
        if not isinstance(progress,dict):progress={}
        checked=raw.get('checked')
        if isinstance(checked,bool) or not isinstance(checked,(int,float)) or not math.isfinite(checked) or checked<0:checked=None
        safe=dict(ok=raw.get('ok') is True,checked=checked,
                  progress={key:progress.get(key) is True for key in ('cdr_caught_up','cel_caught_up')},
                  source_gap=raw.get('source_gap') is True or raw.get('coverage_gap') is True or progress.get('source_gap') is True)
        projection=db.execute('SELECT after_id,updated FROM report_projection WHERE pbx=?',(archive.pbx,)).fetchone()
        latest=db.execute('SELECT MAX(id) FROM events WHERE pbx=?',(archive.pbx,)).fetchone()[0] or 0
        caught_up=projection is not None and projection['after_id']>=latest
        result['projection']=dict(caught_up=caught_up,updated=projection['updated'] if projection else None)
        result['sql_health']=safe;result['observed_until']=checked;result['source_gap']=safe['source_gap']
        result['stale']=checked is None or not 0<=time.time()-checked<=90
        if safe['ok'] and all(safe['progress'].values()) and not safe['source_gap'] and not result['stale'] and caught_up:
            result['coverage']='observed_sql_snapshot'
    return result
