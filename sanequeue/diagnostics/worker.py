"""Opt-in, bounded archive-only diagnostic snapshots; no PBX or HTTP writes.

Machine findings are historical suspected queue segments requiring review, not
active fault/root-cause assertions. Later unrelated CEL changes are not fully
replayed here; consumers must revalidate current evidence before showing a
finding as current. Original evidence versions remain immutable.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import time

from sanequeue.reporting.store import Archive, QueryDeadline
from .rules import RULE_VERSION, short_after_answer
from .store import Store, Scope, Conflict, Unavailable, MAX_BATCH


GENERATION=re.compile(r'archive_[a-f0-9]{32}\Z')
HEX=re.compile(r'[a-f0-9]{64}\Z')
MAX_PAYLOAD=4096
MAX_IDENTITY_EVENTS=1000


def _hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def _queue(value):
    # Archive queue names may be Persian. Preserve exact spelling; these values
    # are SQL parameters and scopes, never dialplan/AMI command fragments.
    return isinstance(value,str) and 0<len(value)<=128 and value.isprintable()


class SourceUnavailable(RuntimeError):pass


class Worker:
    def __init__(self,archive,store,*,generation,threshold_seconds=5,disabled_file=None):
        if not isinstance(generation,str) or not GENERATION.fullmatch(generation):raise ValueError('diagnostic_archive_generation_required')
        short_after_answer({},threshold_seconds=threshold_seconds)
        if archive.pbx!=store.pbx:raise ValueError('diagnostic_pbx_mismatch')
        if archive.path.resolve()==store.path.resolve():raise ValueError('diagnostic_separate_database_required')
        self.archive=archive;self.store=store;self.generation=generation
        self.threshold=float(threshold_seconds);self.disabled_file=Path(disabled_file) if disabled_file else None
        # Policy-specific names avoid reusing a cursor/evidence identity after
        # a deliberate threshold/rule change. The archive generation stays bound.
        self.rule='short_after_answer_'+_hash([RULE_VERSION,self.threshold])[:8]
        self.name=self.rule

    def _identity(self):
        path=self.archive.path
        if path.is_symlink() or not path.is_file():raise SourceUnavailable('diagnostic_archive_unavailable')
        meta=path.stat()
        return _hash([str(path.resolve()),meta.st_dev,meta.st_ino,self.archive.pbx])

    def _candidate(self,db,row):
        """No phone/channel payload or arbitrary source text leaves this method."""
        if not row['current'] or not row['source'].startswith('queue_log') or row['kind'].upper() not in ('COMPLETECALLER','COMPLETEAGENT') or row['payload'] is None:return None,None
        try:payload=json.loads(row['payload'])
        except (ValueError,TypeError):return None,None
        if not isinstance(payload,dict):return None,None
        uid,queue=payload.get('callid'),payload.get('queue')
        if not isinstance(uid,str) or not 0<len(uid)<=512 or not uid.isprintable() or uid in ('NONE','REALTIME','<unknown>'):return None,None
        if not _queue(queue) or queue in ('NONE','ALL'):return None,None
        # Every current queue event for the identity participates in scope.
        # A high fanout identity is omitted, never reduced to a convenient queue.
        scopes=db.execute('''SELECT CASE WHEN length(q.queue)<=128 THEN q.queue ELSE NULL END queue
          FROM report_queue_events q INDEXED BY rq_identity
          JOIN events e ON e.pbx=q.pbx AND e.id=q.event_id
          JOIN source_items s ON s.pbx=e.pbx AND s.source=e.source
            AND s.source_key=e.source_key AND s.event_id=e.id
          WHERE q.pbx=? AND q.callid=? LIMIT ?''',
          (self.archive.pbx,uid,MAX_IDENTITY_EVENTS+1)).fetchall()
        if not scopes or len(scopes)>MAX_IDENTITY_EVENTS:return None,None
        observed={item['queue'] for item in scopes}
        if len(observed)>256 or any(not _queue(q) for q in observed):return None,None
        queues=sorted(observed)
        visits=db.execute('''SELECT id,queue,answered,ended,talk_seconds,outcome,coverage
          FROM report_visits INDEXED BY rv_call WHERE pbx=? AND callid=? AND queue=? AND ended=? LIMIT 2''',
          (self.archive.pbx,uid,queue,row['ts'])).fetchall()
        if len(visits)!=1 or not HEX.fullmatch(str(visits[0]['id'])):return None,None
        visit=dict(visits[0]);ident=_hash([self.archive.pbx,self.generation,visit['id'],self.rule])
        existing=self.store.get(ident,Scope(pbx_admin=True))
        finding=short_after_answer(visit,threshold_seconds=self.threshold)
        if existing and (existing['queues']!=queues or existing['visit_id']!=visit['id'] or finding is None):
            return None,ident
        if finding is None:return None,None
        return dict(incident_id=ident,kind=finding['kind'],queues=queues,visit_id=visit['id'],
            generation=self.generation,event_id=row['id'],source='queue_log',rule=self.rule,rule_version=1,
            rule_parameters={'threshold_seconds':self.threshold},occurred_at=finding['occurred_at'],
            reason='short_duration',severity='warning',confidence='suspected'),None

    def _superseded_reviews(self,db,row,deadline):
        """Withdraw known old snapshots when the same source key is corrected.

        This bounded check is deliberately not a full cross-event reconciliation
        engine. Ambiguous/rebuilt visits cannot produce a new machine finding.
        """
        if not row['current'] or not row['source'].startswith('queue_log'):return set()
        previous=db.execute('''SELECT e.ts,
          CASE WHEN length(CAST(e.payload AS BLOB))<=? THEN e.payload ELSE NULL END payload
          FROM events e INDEXED BY event_source WHERE e.pbx=? AND e.source=? AND e.source_key=?
            AND e.id<? AND upper(e.kind) IN ('COMPLETECALLER','COMPLETEAGENT')
          ORDER BY e.id DESC LIMIT ?''',
          (MAX_PAYLOAD,self.archive.pbx,row['source'],row['source_key'],row['id'],MAX_BATCH+1)).fetchall()
        if len(previous)>MAX_BATCH:raise SourceUnavailable('diagnostic_source_version_fanout')
        reviews=set()
        for old in previous:
            if time.monotonic()>=deadline:raise SourceUnavailable('diagnostic_archive_deadline')
            if old['payload'] is None:continue
            try:value=json.loads(old['payload'])
            except (ValueError,TypeError):continue
            if not isinstance(value,dict):continue
            uid,queue=value.get('callid'),value.get('queue')
            if not isinstance(uid,str) or not 0<len(uid)<=512 or not uid.isprintable():continue
            if not _queue(queue):continue
            visits=db.execute('''SELECT id FROM report_visits INDEXED BY rv_call
              WHERE pbx=? AND callid=? AND queue=? AND ended=? LIMIT 2''',
              (self.archive.pbx,uid,queue,old['ts'])).fetchall()
            for visit in visits:
                if not HEX.fullmatch(str(visit['id'])):continue
                ident=_hash([self.archive.pbx,self.generation,visit['id'],self.rule])
                incident=self.store.get(ident,Scope(pbx_admin=True))
                if incident and incident['reporter'] is None:reviews.add(ident)
            if len(reviews)>MAX_BATCH:raise SourceUnavailable('diagnostic_review_capacity')
        return reviews

    def run_batch(self,*,limit=250,now=None):
        if type(limit) is not int or not 1<=limit<=1000:raise ValueError('diagnostic_worker_batch_limit')
        now=time.time() if now is None else now
        if type(now) not in (int,float) or not math.isfinite(now) or not 0<=now<=32503680000:raise ValueError('invalid_diagnostic_time')
        if self.disabled_file and self.disabled_file.exists():return dict(state='disabled',processed=0,inserted=0)
        prior=self.store.worker_checkpoint(self.name);cursor=prior['cursor'];identity=self._identity()
        if prior['generation'] is not None and (prior['generation']!=self.generation or prior['archive_identity']!=identity):raise Conflict('diagnostic_source_changed')
        if cursor and prior['generation'] is None:raise Conflict('diagnostic_unbound_checkpoint_requires_review')
        observations=[];reviews=set();processed=0;next_cursor=cursor;anchor=prior['anchor']
        bounded=Archive(self.archive.path,pbx=self.archive.pbx,read_seconds=min(1,self.archive.read_seconds))
        deadline=time.monotonic()+bounded.read_seconds
        try:
            with bounded.reader() as db:
                if cursor:
                    check=db.execute('SELECT event_key FROM events WHERE pbx=? AND id=?',(self.archive.pbx,cursor)).fetchone()
                    if check is None or check['event_key']!=anchor:raise Conflict('diagnostic_archive_anchor_changed')
                head=db.execute('SELECT MAX(id) FROM events WHERE pbx=?',(self.archive.pbx,)).fetchone()[0] or 0
                projection=db.execute('SELECT after_id FROM report_projection WHERE pbx=?',(self.archive.pbx,)).fetchone()
                version=db.execute('SELECT version FROM report_projection_version WHERE pbx=?',(self.archive.pbx,)).fetchone()
                if not projection or not version or version[0]<9:return dict(state='projection_unavailable',processed=0,inserted=0)
                if prior['projection_version'] is not None and prior['projection_version']!=version[0]:raise Conflict('diagnostic_projection_changed_requires_review')
                if projection[0]>head:raise Conflict('diagnostic_archive_projection_reset')
                # Waiting for a caught-up snapshot also prevents a pending
                # foreign-queue event from escaping the all-queue scope check.
                if projection[0]<head:return dict(state='projection_lag',processed=0,inserted=0)
                rows=db.execute('''SELECT e.id,e.event_key,e.source,e.source_key,e.ts,e.kind,
                  s.event_id=e.id AS current,
                  CASE WHEN length(CAST(e.payload AS BLOB))<=? AND e.source LIKE 'queue_log%'
                    AND upper(e.kind) IN ('COMPLETECALLER','COMPLETEAGENT') THEN e.payload ELSE NULL END payload
                  FROM events e INDEXED BY event_cursor LEFT JOIN source_items s
                    ON s.pbx=e.pbx AND s.source=e.source AND s.source_key=e.source_key
                  WHERE e.pbx=? AND e.id>? AND e.id<=? ORDER BY e.id LIMIT ?''',
                  (MAX_PAYLOAD,self.archive.pbx,cursor,projection[0],limit)).fetchall()
                for row in rows:
                    if time.monotonic()>=deadline:raise SourceUnavailable('diagnostic_archive_deadline')
                    if len(observations)>=MAX_BATCH or len(reviews)>=MAX_BATCH:break
                    changed=self._superseded_reviews(db,row,deadline)
                    if len(reviews|changed)>MAX_BATCH:break
                    observation,review=self._candidate(db,row)
                    if review:changed.add(review)
                    if len(reviews|changed)>MAX_BATCH:break
                    if observation:observations.append(observation)
                    reviews.update(changed)
                    processed+=1;next_cursor=row['id'];anchor=row['event_key']
                if next_cursor and (not isinstance(anchor,str) or not HEX.fullmatch(anchor)):raise SourceUnavailable('diagnostic_archive_anchor_invalid')
        except QueryDeadline:raise SourceUnavailable('diagnostic_archive_deadline') from None
        except sqlite3.Error:raise SourceUnavailable('diagnostic_archive_unavailable') from None
        if self._identity()!=identity:raise Conflict('diagnostic_source_changed')
        if self.disabled_file and self.disabled_file.exists():return dict(state='disabled',processed=0,inserted=0)
        binding=dict(generation=self.generation,archive_identity=identity,anchor=anchor,projection_version=version[0])
        expected=prior if prior['generation'] is not None else None
        result=self.store.ingest_batch(self.name,cursor,next_cursor,observations,binding=binding,
            expected_binding=expected,review_incidents=sorted(reviews),now=now)
        return dict(state='processed' if processed else 'idle',processed=processed,**result,
            findings_require_review=True,current_state_verified=False,
            correction_reconciliation='historical_snapshot_requires_current_evidence_review')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',required=True)
    parser.add_argument('--database',required=True)
    parser.add_argument('--archive-generation',required=True,help='Opaque archive_ + 32 lowercase hex; rotate for a new archive, never reuse for unrelated data.')
    parser.add_argument('--pbx',default='primary')
    parser.add_argument('--threshold-seconds',type=float,default=5)
    parser.add_argument('--limit',type=int,default=250)
    parser.add_argument('--disabled-file')
    parser.add_argument('--once',action='store_true',required=True,help='Explicitly opt in to one bounded batch; no service is activated.')
    args=parser.parse_args(argv)
    store=Store(args.database,pbx=args.pbx)
    worker=Worker(Archive(args.archive,pbx=args.pbx),store,generation=args.archive_generation,
        threshold_seconds=args.threshold_seconds,disabled_file=args.disabled_file)
    if args.disabled_file and Path(args.disabled_file).exists():print(json.dumps(dict(state='disabled',processed=0,inserted=0)));return 0
    try:
        store.initialize()
        result=worker.run_batch(limit=args.limit)
    except (SourceUnavailable,Unavailable,Conflict,ValueError,OSError):
        print(json.dumps(dict(state='deferred',reason='diagnostic_source_or_checkpoint_requires_review')));return 1
    print(json.dumps(result,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
