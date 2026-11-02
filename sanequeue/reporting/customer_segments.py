"""Temporal VIP labels and explicitly imported blocked-call observations.

Labels are reporting metadata, never routing/authentication or blacklist rules.
An imported observation is not independent proof that a PBX blocked a call.
"""
import argparse
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
import unicodedata
import uuid

from .queries import _where
from .store import QueryDeadline


class SegmentConflict(RuntimeError): pass


def number(value):
    if not isinstance(value,str) or len(value)>64:raise ValueError('invalid_customer_number')
    value=''.join(str(unicodedata.digit(c)) if c.isdecimal() else c for c in value.strip())
    value=re.sub(r'[\s().-]','',value)
    if not re.fullmatch(r'\+?[0-9]{1,24}',value):raise ValueError('invalid_customer_number')
    return value


def _key(value,maximum=128):
    if not isinstance(value,str) or not 1<=len(value)<=maximum or not value.isprintable():raise ValueError('invalid_segment_key')
    return value


def _time(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=4102444800:raise ValueError('invalid_segment_time')
    return float(value)


class CustomerSegments:
    def __init__(self,path,*,pbx='primary'):
        self.path=Path(path).absolute();self.pbx=_key(pbx)

    def initialize(self):
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        if self.path.is_symlink():raise ValueError('segments_symlink')
        fd=os.open(self.path,os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):raise ValueError('segments_regular_file_required')
            if os.name!='nt':os.fchmod(fd,0o600)
        finally:os.close(fd)
        with self.db(write=True,bootstrap=True) as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS customer_tags(
              id TEXT PRIMARY KEY,pbx TEXT,queue TEXT,number TEXT,effective REAL,enabled INTEGER,
              owner TEXT,request_key TEXT,created REAL,UNIQUE(pbx,owner,request_key));
              CREATE INDEX IF NOT EXISTS ct_match ON customer_tags(pbx,queue,number,effective DESC,id DESC);
              CREATE INDEX IF NOT EXISTS ct_page ON customer_tags(pbx,queue,created DESC,id DESC);
              CREATE TABLE IF NOT EXISTS blocked_observations(
              id TEXT PRIMARY KEY,pbx TEXT,source TEXT,event_key TEXT,queue TEXT,number TEXT,
              at REAL,reason TEXT,created REAL,UNIQUE(pbx,source,event_key));
              CREATE INDEX IF NOT EXISTS bo_time ON blocked_observations(pbx,queue,at,id);
              CREATE TRIGGER IF NOT EXISTS ct_no_update BEFORE UPDATE ON customer_tags BEGIN SELECT RAISE(ABORT,'immutable');END;
              CREATE TRIGGER IF NOT EXISTS ct_no_delete BEFORE DELETE ON customer_tags BEGIN SELECT RAISE(ABORT,'immutable');END;
              CREATE TRIGGER IF NOT EXISTS bo_no_update BEFORE UPDATE ON blocked_observations BEGIN SELECT RAISE(ABORT,'immutable');END;
              CREATE TRIGGER IF NOT EXISTS bo_no_delete BEFORE DELETE ON blocked_observations BEGIN SELECT RAISE(ABORT,'immutable');END;''')

    @contextmanager
    def db(self,*,write=False,bootstrap=False):
        if self.path.is_symlink():raise ValueError('segments_symlink')
        uri=self.path.as_uri()+('?mode=rw' if write else '?mode=ro')
        db=sqlite3.connect(uri,uri=True,timeout=.25);db.row_factory=sqlite3.Row
        deadline=time.monotonic()+2
        db.set_progress_handler(lambda:int(time.monotonic()>=deadline),1000)
        try:
            db.execute('PRAGMA trusted_schema=OFF');db.execute('PRAGMA cache_size=-1024')
            if bootstrap:db.execute('PRAGMA journal_mode=WAL')
            if write:db.execute('BEGIN IMMEDIATE')
            else:db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            yield db
            if write:db.commit()
        except sqlite3.OperationalError as error:
            if 'interrupt' in str(error).lower():raise QueryDeadline('customer_segments_deadline') from error
            raise
        finally:db.close()

    def tag(self,owner,queue,caller,enabled,*,effective,request_key):
        owner=_key(owner);queue=_key(queue);caller=number(caller);request_key=_key(request_key)
        if effective is not None:effective=_time(effective)
        if type(enabled) is not bool:raise ValueError('invalid_vip_state')
        with self.db(write=True) as db:
            prior=db.execute('SELECT * FROM customer_tags WHERE pbx=? AND owner=? AND request_key=?',(self.pbx,owner,request_key)).fetchone()
            if prior:
                if (prior['queue'],prior['number'],prior['enabled'],prior['effective'])!=(queue,caller,int(enabled),effective if effective is not None else prior['effective']):raise SegmentConflict('segment_request_conflict')
                return dict(prior)
            if effective is None:effective=time.time()
            if db.execute('SELECT COUNT(*) FROM customer_tags WHERE pbx=?',(self.pbx,)).fetchone()[0]>=50000:raise SegmentConflict('segment_label_quota')
            # Do not allow arbitrary tie-breaking of contradictory temporal facts.
            if db.execute('SELECT 1 FROM customer_tags WHERE pbx=? AND queue=? AND number=? AND effective=?',(self.pbx,queue,caller,effective)).fetchone():raise SegmentConflict('segment_effective_conflict')
            ident=uuid.uuid4().hex
            db.execute('INSERT INTO customer_tags VALUES(?,?,?,?,?,?,?,?,?)',(ident,self.pbx,queue,caller,effective,int(enabled),owner,request_key,time.time()))
            return dict(db.execute('SELECT * FROM customer_tags WHERE id=?',(ident,)).fetchone())

    def import_blocks(self,source,rows):
        if not isinstance(source,str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}',source):raise ValueError('invalid_block_source')
        if not isinstance(rows,list) or not 1<=len(rows)<=500:raise ValueError('invalid_block_batch')
        cleaned=[]
        for row in rows:
            if not isinstance(row,dict):raise ValueError('invalid_block_observation')
            reason=row.get('reason')
            if reason not in ('blacklist','policy','security','other'):raise ValueError('invalid_block_reason')
            cleaned.append((_key(row.get('id'),256),_key(row.get('queue')),number(row.get('number')),_time(row.get('at')),reason))
        inserted=0
        with self.db(write=True) as db:
            existing=db.execute('SELECT COUNT(*) FROM blocked_observations WHERE pbx=?',(self.pbx,)).fetchone()[0]
            for key,queue,caller,at,reason in cleaned:
                prior=db.execute('SELECT * FROM blocked_observations WHERE pbx=? AND source=? AND event_key=?',(self.pbx,source,key)).fetchone()
                if prior:
                    if (prior['queue'],prior['number'],prior['at'],prior['reason'])!=(queue,caller,at,reason):raise SegmentConflict('block_source_conflict')
                    continue
                if existing+inserted>=100000:raise SegmentConflict('block_observation_quota')
                db.execute('INSERT INTO blocked_observations VALUES(?,?,?,?,?,?,?,?,?)',(uuid.uuid4().hex,self.pbx,source,key,queue,caller,at,reason,time.time()));inserted+=1
        return inserted

    def report(self,archive,scope,start,end,*,sla_seconds=20):
        if end<=start or end-start>31*86400 or type(sla_seconds) is not int or not 1<=sla_seconds<=3600:raise ValueError('segment_range_or_sla_limit')
        if scope.self_only:raise PermissionError('segments_supervisor_scope_required')
        clause,args=_where(archive.pbx,scope,start,end)
        if not scope.queues:return dict(vip=[],blocks=[],observations=[],labels=[])
        if archive.pbx!=self.pbx or self.path.is_symlink():raise ValueError('segment_pbx_mismatch')
        allowed=tuple(scope.queues);marks=','.join('?' for _ in allowed)
        with archive.reader() as db:
            db.execute('ATTACH DATABASE ? AS customer_metadata',(self.path.as_uri()+'?mode=ro',))
            def canonical(value):
                try:return number(value)
                except ValueError:return None
            db.create_function('segment_number',1,canonical,deterministic=True)
            vip=[dict(row) for row in db.execute('''WITH scoped AS (SELECT * FROM report_visits WHERE '''+clause+'''),
              classified AS (SELECT *, (SELECT enabled FROM customer_metadata.customer_tags t INDEXED BY ct_match
                WHERE t.pbx=scoped.pbx AND t.queue=scoped.queue AND t.number=segment_number(scoped.caller)
                AND t.effective<=scoped.entered ORDER BY t.effective DESC,t.id DESC LIMIT 1) vip FROM scoped)
              SELECT queue,vip,COUNT(*) visits,SUM(answered IS NOT NULL OR outcome='answered') answered,
                SUM(outcome='abandoned') abandoned,COUNT(wait_seconds) known_wait,
                AVG(wait_seconds) average_wait_seconds,
                SUM((answered IS NOT NULL OR outcome='answered') AND wait_seconds IS NOT NULL) sla_denominator,
                SUM((answered IS NOT NULL OR outcome='answered') AND wait_seconds<=?) sla_numerator
              FROM classified GROUP BY queue,vip ORDER BY queue,vip LIMIT 3001''',(*args,sla_seconds))]
            if len(vip)>3000:raise QueryDeadline('segment_group_limit')
            for row in vip:
                row['classification']='vip' if row['vip']==1 else 'not_vip' if row['vip']==0 else 'unclassified'
                row['sla_percent']=100*row['sla_numerator']/row['sla_denominator'] if row['sla_denominator'] else None
            blocks=[dict(row) for row in db.execute('''SELECT queue,reason,COUNT(*) observations FROM customer_metadata.blocked_observations
              WHERE pbx=? AND queue IN ('''+marks+''') AND at>=? AND at<? GROUP BY queue,reason ORDER BY queue,reason LIMIT 4001''',(self.pbx,*allowed,max(start,scope.not_before),end))]
            if len(blocks)>4000:raise QueryDeadline('segment_group_limit')
            observations=[dict(row) for row in db.execute('''SELECT id,queue,number,at,reason,source FROM customer_metadata.blocked_observations
              WHERE pbx=? AND queue IN ('''+marks+''') AND at>=? AND at<? ORDER BY at DESC,id DESC LIMIT 100''',(self.pbx,*allowed,max(start,scope.not_before),end))]
            labels=[dict(row) for row in db.execute('''SELECT id,queue,number,effective,enabled,created FROM customer_metadata.customer_tags
              WHERE pbx=? AND queue IN ('''+marks+''') AND created>=? ORDER BY created DESC,id DESC LIMIT 100''',(self.pbx,*allowed,scope.not_before))]
        return dict(vip=vip,blocks=blocks,observations=observations,labels=labels,
                    sla_seconds=sla_seconds,sla_basis='answered_known_wait',labels_basis='operator_temporal_annotation',
                    blocks_basis='operator_imported_observation_not_independent_pbx_proof',detail_limit=100,range=dict(start=start,end=end))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True);parser.add_argument('--pbx',default='primary')
    parser.add_argument('--source',required=True);parser.add_argument('jsonl')
    args=parser.parse_args();store=CustomerSegments(args.database,pbx=args.pbx)
    inserted=0;batch=[];total=0
    # Trusted operator import only. Never offered as a web URL/file-path endpoint.
    try:
        store.initialize()
        with open(args.jsonl,'rb') as stream:
            while True:
                line=stream.readline(4097)
                if not line:break
                total+=len(line)
                if len(line)>4096 or total>8*1024**2:raise ValueError('block_import_size_limit')
                if not line.strip():continue
                batch.append(json.loads(line))
                if len(batch)==500:inserted+=store.import_blocks(args.source,batch);batch=[]
            if batch:inserted+=store.import_blocks(args.source,batch)
    except (OSError,sqlite3.Error,ValueError,SegmentConflict,QueryDeadline):
        parser.exit(1,'Import failed; '+str(inserted)+' observations committed before failure. Review the private source; retry uses stable IDs.\n')
    print(json.dumps(dict(inserted=inserted,source=args.source)))


if __name__=='__main__':main()
