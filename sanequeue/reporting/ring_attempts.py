"""Bounded archival queue-member RINGNOANSWER attempts, never unique callers.

No AMI, source import, schema write or PBX query. The existing event_time index
bounds every inspected source row, including unrelated event kinds. Large
windows fail explicitly rather than yielding misleading partial aggregates.
"""
import base64
import hashlib
import json
import math
import re
import time
from .facts import _endpoint
from .store import QueryDeadline

MAX_EVENTS=10000
MAX_GROUPS=1000
MAX_PAYLOAD=4096
MAX_BYTES=4*1024*1024
MAX_VISITS=1000
MAX_CORRELATION_ROWS=10000
EVENT_SQL='''SELECT e.id,e.ts,e.event_key,e.source,
 CASE WHEN e.source LIKE 'queue_log%' AND UPPER(e.kind)='RINGNOANSWER'
 THEN CASE WHEN length(CAST(e.payload AS BLOB))<=4096 THEN e.payload ELSE '' END
 ELSE NULL END payload, s.event_id=e.id current_version
 FROM events e INDEXED BY event_time LEFT JOIN source_items s
 ON s.pbx=e.pbx AND s.source=e.source AND s.source_key=e.source_key
 WHERE e.pbx=? AND e.ts>=? AND e.ts<? ORDER BY e.ts,e.id LIMIT ?'''


def _finite(value):
    return type(value) in (int,float) and math.isfinite(value)


def _label(value,maximum=128):
    return isinstance(value,str) and 0<len(value)<=maximum and value.isprintable()


def _cursor(value):
    if value is None:return None
    try:
        if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,192}',value):raise ValueError()
        stamp,ident=json.loads(base64.urlsafe_b64decode(value+'='*(-len(value)%4)))
        if not _finite(stamp) or stamp<0 or type(ident) is not int or ident<1:raise ValueError()
        return stamp,ident
    except (ValueError,TypeError,UnicodeError):raise ValueError('invalid_ring_attempt_cursor') from None


def _encode(row):
    return base64.urlsafe_b64encode(json.dumps([row['_ts'],row['_event']],separators=(',',':')).encode()).decode().rstrip('=')


def _duration(values):
    if not isinstance(values,list) or not values:return None
    value=values[0]
    if isinstance(value,str):
        if not re.fullmatch(r'[0-9]{1,10}(?:\.[0-9]{1,3})?',value):return None
        value=float(value)
    if not _finite(value) or not 0<=value<=86400000:return None
    return value/1000


def report(archive,scope,start,end,*,before=None,limit=100,now=None):
    """Full-range attempt aggregates plus one descending keyset detail page.

    Agent self-reporting is deliberately unsupported until a versioned member
    identity proof exists for these queue_log rows. A member name is not an
    assignment proof. visit_id is only a queue-visit link, never an audio grant.
    """
    if scope.self_only:raise ValueError('ring_attempt_agent_scope_unsupported')
    if not _finite(start) or not _finite(end) or start<0 or end<=start or end-start>31*86400:raise ValueError('invalid_ring_attempt_range')
    if not _finite(scope.not_before) or scope.not_before<0:raise ValueError('invalid_ring_attempt_cutoff')
    if len(scope.queues)>256 or any(not _label(q) for q in scope.queues):raise ValueError('invalid_ring_attempt_scope')
    if type(limit) is not int or not 1<=limit<=100:raise ValueError('invalid_ring_attempt_limit')
    cursor=_cursor(before);current=time.time() if now is None else now
    if not _finite(current) or current<0:raise ValueError('invalid_ring_attempt_now')
    first=min(float(end),max(float(start),scope.not_before));last=max(first,min(float(end),current))
    deadline=time.monotonic()+min(5,archive.read_seconds);allowed=set(scope.queues)
    rows=[];groups={};bytes_seen=0;cache={};correlation_rows=0
    def check():
        if time.monotonic()>=deadline:raise QueryDeadline('ring_attempt_deadline')
    with archive.reader() as db:
        db.set_progress_handler(lambda:int(time.monotonic()>=deadline),1000)
        projection=db.execute('SELECT after_id,updated FROM report_projection WHERE pbx=?',(archive.pbx,)).fetchone()
        latest=db.execute('SELECT MAX(id) FROM events WHERE pbx=?',(archive.pbx,)).fetchone()[0] or 0
        projected=bool(projection and projection['after_id']>=latest)
        def checkpoint(name):
            row=db.execute('SELECT CASE WHEN length(CAST(value AS BLOB))<=8192 THEN value ELSE NULL END FROM checkpoints WHERE pbx=? AND source=?',(archive.pbx,name)).fetchone()
            try:value=json.loads(row[0]) if row and row[0] else {}
            except (ValueError,TypeError):value={}
            return value if isinstance(value,dict) else {}
        health=checkpoint('health:queue_log');source=checkpoint('queue_log')
        checked=health.get('checked');fresh=_finite(checked) and 0<=current-checked<=90
        progress=health.get('progress',{});progress=progress if isinstance(progress,dict) else {}
        gaps=source.get('coverage_gaps',[]);gap=False
        if not isinstance(gaps,list) or len(gaps)>32:gap=True
        else:
            for item in gaps:
                if not isinstance(item,list) or len(item)!=2 or not all(_finite(v) for v in item) or item[1]<item[0]:gap=True;break
                if first<=item[1] and last>=item[0]:gap=True
        if source.get('last_rotation_detected') and not gaps:gap=True
        raw=db.execute(EVENT_SQL,(archive.pbx,first,last,MAX_EVENTS+1)).fetchall() if allowed and first<last else []
        if len(raw)>MAX_EVENTS:raise QueryDeadline('ring_attempt_source_event_limit')
        for event in raw:
            check()
            if event['payload'] is None or not event['current_version']:continue
            if not event['payload']:raise QueryDeadline('ring_attempt_payload_limit')
            bytes_seen+=len(event['payload'].encode())
            if bytes_seen>MAX_BYTES:raise QueryDeadline('ring_attempt_payload_budget')
            try:payload=json.loads(event['payload'])
            except (ValueError,TypeError):raise ValueError('invalid_ring_attempt_evidence') from None
            if not isinstance(payload,dict):raise ValueError('invalid_ring_attempt_evidence')
            queue=payload.get('queue')
            if queue not in allowed:continue
            callid=payload.get('callid');stamp=event['ts'];agent=payload.get('agent')
            endpoint=_endpoint(agent) if _label(agent,256) else None
            # Named queue members without explicit endpoint syntax stay unknown.
            duration=_duration(payload.get('values'));visit_id=None;reason='projection_incomplete'
            if projected:
                if not _label(callid,512) or callid in ('NONE','REALTIME'):reason='caller_identity_unavailable'
                else:
                    key=(queue,callid)
                    if key not in cache:
                        candidates=db.execute('''SELECT id,entered,answered,ended,outcome,coverage FROM report_visits INDEXED BY rv_call
                          WHERE pbx=? AND callid=? AND queue=? ORDER BY entered,id LIMIT ?''',
                          (archive.pbx,callid,queue,MAX_VISITS+1)).fetchall()
                        if len(candidates)>MAX_VISITS:raise QueryDeadline('ring_attempt_visit_evidence_limit')
                        correlation_rows+=len(candidates)
                        if correlation_rows>MAX_CORRELATION_ROWS:raise QueryDeadline('ring_attempt_correlation_budget')
                        cache[key]=candidates
                    candidates=[v for v in cache[key] if v['entered']<=stamp and (v['ended'] is None or stamp<=v['ended'])]
                    if len(candidates)>1:reason='ambiguous_queue_visit'
                    elif not candidates:reason='queue_visit_unproven'
                    else:
                        visit=candidates[0]
                        if visit['entered']<scope.not_before:reason='visit_before_assignment_cutoff'
                        elif visit['coverage']=='missing_entry':reason='queue_entry_unproven'
                        elif visit['outcome']=='reentered_without_end':reason='ambiguous_reentry'
                        elif visit['answered'] is not None and stamp>=visit['answered']:reason='attempt_after_answer_or_timestamp_tie'
                        else:visit_id=visit['id'];reason='explicit_queue_visit_interval'
            row=dict(id=hashlib.sha256((archive.pbx+':'+event['event_key']).encode()).hexdigest(),queue=queue,agent=endpoint,
                timestamp=stamp,ring_seconds=duration,visit_id=visit_id,correlation=reason,source='queue_log',_ts=stamp,_event=event['id'])
            rows.append(row);key=(queue,endpoint)
            if key not in groups:
                if len(groups)>=MAX_GROUPS:raise QueryDeadline('ring_attempt_group_limit')
                groups[key]=dict(queue=queue,agent=endpoint,attempts=0,known_duration_attempts=0,unknown_duration_attempts=0,
                    known_ring_seconds=0,matched_visit_attempts=0,unmatched_visit_attempts=0)
            group=groups[key];group['attempts']+=1;group['known_duration_attempts']+=int(duration is not None);group['unknown_duration_attempts']+=int(duration is None)
            group['known_ring_seconds']+=duration or 0;group['matched_visit_attempts']+=int(visit_id is not None);group['unmatched_visit_attempts']+=int(visit_id is None)
        check()
    totals={key:sum(g[key] for g in groups.values()) for key in ('attempts','known_duration_attempts','unknown_duration_attempts','known_ring_seconds','matched_visit_attempts','unmatched_visit_attempts')}
    for group in [totals,*groups.values()]:
        group['average_known_ring_seconds']=group['known_ring_seconds']/group['known_duration_attempts'] if group['known_duration_attempts'] else None
    ordered=sorted((r for r in rows if cursor is None or (r['_ts'],r['_event'])<cursor),key=lambda r:(r['_ts'],r['_event']),reverse=True)
    page=ordered[:limit];next_cursor=_encode(page[-1]) if len(ordered)>limit else None
    for row in page:row.pop('_ts');row.pop('_event')
    return dict(start=float(start),end=float(end),effective_start=first,effective_end=last,unit='queue_member_ring_attempt',rows=page,next=next_cursor,
        totals=totals,groups=sorted(groups.values(),key=lambda g:(g['queue'],g['agent'] or '')),
        coverage=dict(complete=False,reason='archived_attempts_only_not_unique_missed_callers',projection_caught_up=projected,
            queue_log=dict(ok=health.get('ok') is True,checked=checked if _finite(checked) else None,fresh=fresh,
                caught_up=progress.get('caught_up') is True,source_time=source.get('source_time') if _finite(source.get('source_time')) else None),
            source_gap=gap,unknown_agent_attempts=sum(r['agent'] is None for r in rows),
            source_event_limit=MAX_EVENTS,group_limit=MAX_GROUPS,retention='no_automatic_deletion'))
