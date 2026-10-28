"""Scoped evidence for outbound CDR segments started during an observed pause."""
import math
import json
import time
from .queries import _scope, _where
from .store import QueryDeadline

MAX_SUMMARY_GROUPS=2000
MAX_PAUSE_INTERVALS=10000

_METRICS='''COUNT(*) segments_started,
 COALESCE(SUM(disposition='ANSWERED'),0) answered_segments,
 COALESCE(SUM(disposition IN ('BUSY','NO ANSWER','FAILED','CONGESTION','CANCEL','CHANUNAVAIL')),0) unanswered_segments,
 COALESCE(SUM(disposition NOT IN ('ANSWERED','BUSY','NO ANSWER','FAILED','CONGESTION','CANCEL','CHANUNAVAIL')),0) unknown_disposition_segments,
 COALESCE(SUM(disposition='BUSY'),0) busy_segments,
 COALESCE(SUM(disposition='NO ANSWER'),0) no_answer_segments,
 COALESCE(SUM(disposition='FAILED'),0) failed_segments,
 COALESCE(SUM(disposition IN ('CONGESTION','CANCEL','CHANUNAVAIL')),0) other_unanswered_segments,
 COALESCE(SUM(billsec),0) known_billsec_sum,COUNT(billsec) known_billsec_count,
 COUNT(*)-COUNT(billsec) unknown_billsec_count,
 COALESCE(SUM(disposition='ANSWERED' AND billsec IS NOT NULL),0) answered_known_billsec_count,
 AVG(CASE WHEN disposition='ANSWERED' THEN billsec END) average_answered_billsec,
 COUNT(DISTINCT group_key) linkedid_groups'''


def _empty_metrics():
    return dict(segments_started=0,answered_segments=0,unanswered_segments=0,
                unknown_disposition_segments=0,busy_segments=0,no_answer_segments=0,
                failed_segments=0,other_unanswered_segments=0,known_billsec_sum=0,
                known_billsec_count=0,unknown_billsec_count=0,answered_known_billsec_count=0,
                average_answered_billsec=None,linkedid_groups=0,unique_pause_seconds=0)


def _union_seconds(intervals):
    total=0;last=None
    for first,end in sorted(intervals):
        if last is None or first>last:
            total+=end-first
        elif end>last:
            total+=end-last
        last=max(last,end) if last is not None else end
    return total


def summary(archive,scope,start,end,direction='outbound'):
    """Aggregate every matched CDR segment; never aggregate a display page.

    Segment billsec is not unique talk time or pause-overlap talk time.
    Queue/reason breakdowns overlap and must never be added to form a total.
    """
    _where(archive.pbx,scope,start,end)
    if direction not in ('outbound','internal'):raise ValueError('invalid_pause_call_direction')
    start=max(float(start),scope.not_before)
    end=min(float(end),time.time())
    result=dict(start=start,end=end,observed_until=None,direction=direction,unit='cdr_segment',
                totals=_empty_metrics(),agents=[],queue_reasons=[],queue_reasons_nonadditive=True,
                linkedid_groups_nonadditive=True,complete_history=False,
                coverage='activity_unavailable',
                duration_definition='full_segment_billsec_not_pause_overlap',
                pause_definition='unioned_observed_agent_pause_seconds_clipped_to_range',
                linkedid_definition='linkedid_else_uid_else_source_key_not_unique_conversations',
                group_limit=MAX_SUMMARY_GROUPS,interval_limit=MAX_PAUSE_INTERVALS)
    clause,args=_scope(archive.pbx,scope)
    clause=clause.replace('pbx=','a.pbx=').replace('queue IN','a.queue IN').replace('agent IN','a.agent IN')
    with archive.reader() as db:
        checkpoint=db.execute('SELECT value FROM checkpoints WHERE pbx=? AND source=?',
                              (archive.pbx,'activity_cache')).fetchone()
        checkpoint=json.loads(checkpoint[0]) if checkpoint else {}
        observed=float(checkpoint.get('observed',0))
        if not math.isfinite(observed) or observed<0:raise ValueError('invalid_activity_heartbeat')
        result['observed_until']=observed or None
        result['source_gaps']=int(checkpoint.get('gaps',0))
        if not observed:return result
        end=min(end,observed);result['end']=end
        result['coverage']='known_endpoint_pair_and_observed_pause'
        if start>=end:return result
        predicate=clause+" AND a.state='paused' AND a.canonical_agent=p.agent AND a.starts<=c.ts AND COALESCE(a.ends,?)>c.ts"
        cte='''WITH matched AS (SELECT c.source_key,p.agent,c.ts,c.billsec,
          UPPER(TRIM(COALESCE(c.disposition,''))) disposition,
          CASE WHEN c.linkedid<>'' THEN 'L:'||c.linkedid WHEN c.uid<>'' THEN 'U:'||c.uid
               ELSE 'S:'||c.source_key END group_key
          FROM report_cdr c JOIN report_cdr_parties p ON p.pbx=c.pbx AND p.source_key=c.source_key
          WHERE c.pbx=? AND c.ts>=? AND c.ts<? AND p.direction=?
          AND EXISTS (SELECT 1 FROM report_activity a WHERE '''+predicate+'))'
        values=(archive.pbx,start,end,direction,*args,observed)
        totals=dict(db.execute(cte+' SELECT '+_METRICS+' FROM matched',values).fetchone())
        agents=[dict(row) for row in db.execute(cte+' SELECT agent,'+_METRICS+
                    ' FROM matched GROUP BY agent ORDER BY agent LIMIT ?',(*values,MAX_SUMMARY_GROUPS+1))]
        reason_cte=cte+''', memberships AS (SELECT DISTINCT m.source_key,m.agent,m.billsec,m.disposition,
          m.group_key,a.queue,a.reason FROM matched m JOIN report_activity a ON a.canonical_agent=m.agent
          WHERE '''+clause+" AND a.state='paused' AND a.starts<=m.ts AND COALESCE(a.ends,?)>m.ts)"
        reasons=[dict(row) for row in db.execute(reason_cte+' SELECT agent,queue,reason,'+_METRICS+
                    ' FROM memberships GROUP BY agent,queue,reason ORDER BY agent,queue,reason LIMIT ?',
                    (*values,*args,observed,MAX_SUMMARY_GROUPS+1))]
        if len(agents)>MAX_SUMMARY_GROUPS or len(reasons)>MAX_SUMMARY_GROUPS:
            raise QueryDeadline('outbound_summary_group_limit_narrow_scope')
        pauses=db.execute('''SELECT a.canonical_agent agent,a.queue,a.reason,
          MAX(a.starts,?) first,MIN(COALESCE(a.ends,?),?) last FROM report_activity a WHERE '''+
          clause+" AND a.state='paused' AND a.starts<? AND COALESCE(a.ends,?)>? LIMIT ?",
          (start,observed,end,*args,end,observed,start,MAX_PAUSE_INTERVALS+1)).fetchall()
        if len(pauses)>MAX_PAUSE_INTERVALS:raise QueryDeadline('outbound_pause_union_limit_narrow_scope')
    by_agent={row['agent']:row for row in agents}
    by_reason={(row['agent'],row['queue'],row['reason']):row for row in reasons}
    agent_intervals={};reason_intervals={}
    for row in pauses:
        if row['last']<=row['first']:continue
        pair=(row['first'],row['last'])
        agent_intervals.setdefault(row['agent'],[]).append(pair)
        reason_intervals.setdefault((row['agent'],row['queue'],row['reason']),[]).append(pair)
    if len(set(by_agent)|set(agent_intervals))>MAX_SUMMARY_GROUPS or len(set(by_reason)|set(reason_intervals))>MAX_SUMMARY_GROUPS:
        raise QueryDeadline('outbound_summary_group_limit_narrow_scope')
    for agent,intervals in agent_intervals.items():
        item=by_agent.setdefault(agent,dict(_empty_metrics(),agent=agent))
        item['unique_pause_seconds']=_union_seconds(intervals)
    for key,intervals in reason_intervals.items():
        item=by_reason.setdefault(key,dict(_empty_metrics(),agent=key[0],queue=key[1],reason=key[2]))
        item['unique_pause_seconds']=_union_seconds(intervals)
    totals['unique_pause_seconds']=sum(row.get('unique_pause_seconds',0) for row in by_agent.values())
    for row in (*by_agent.values(),*by_reason.values()):row.setdefault('unique_pause_seconds',0)
    result.update(totals=totals,agents=[by_agent[key] for key in sorted(by_agent)],
                  queue_reasons=[by_reason[key] for key in sorted(by_reason)])
    return result


def page(archive,scope,start,end,*,before=None,limit=100,ident=None,direction='outbound'):
    _where(archive.pbx,scope,start,end)
    if direction not in ('outbound','internal'):raise ValueError('invalid_pause_call_direction')
    start=max(float(start),scope.not_before)
    observed=float(archive.checkpoint('activity_cache').get('observed',0))
    if not observed:return dict(rows=[],next=None,coverage='activity_unavailable')
    clause,args=_scope(archive.pbx,scope)
    # Qualify scope fields inside the correlated activity subquery.
    clause=clause.replace('pbx=','a.pbx=').replace('queue IN','a.queue IN').replace('agent IN','a.agent IN')
    predicate=clause+" AND a.state='paused' AND a.canonical_agent=p.agent AND a.starts<=c.ts AND COALESCE(a.ends,?)>c.ts"
    match_args=[*args,observed]
    where="c.pbx=? AND c.ts>=? AND c.ts<? AND p.direction=? AND EXISTS (SELECT 1 FROM report_activity a WHERE "+predicate+')'
    values=[archive.pbx,start,float(end),direction,*match_args]
    if ident is not None:
        if not isinstance(ident,str) or not 1<=len(ident)<=512:raise ValueError('invalid_outbound_identity')
        where+=' AND c.source_key=?'
        values.append(ident)
    if before:
        if len(before)!=2 or not math.isfinite(float(before[0])) or len(str(before[1]))>256:
            raise ValueError('invalid_outbound_cursor')
        where+=' AND (c.ts<? OR (c.ts=? AND c.source_key<?))'
        values.extend((float(before[0]),float(before[0]),str(before[1])))
    limit=max(1,min(200,int(limit)))
    with archive.reader() as db:
        rows=[dict(row) for row in db.execute('''SELECT c.source_key id,c.ts,c.dst destination,c.duration,
          c.billsec,c.disposition,c.uid,c.linkedid,p.agent,p.inventory_observed,
          CASE WHEN c.recording<>'' THEN 1 ELSE 0 END has_recording
          FROM report_cdr c JOIN report_cdr_parties p ON p.pbx=c.pbx AND p.source_key=c.source_key
          WHERE '''+where+' ORDER BY c.ts DESC,c.source_key DESC LIMIT ?',(*values,limit+1))]
        more=len(rows)>limit;rows=rows[:limit]
        if rows:
            candidates=','.join('(?,?,?)' for _ in rows)
            params=[value for row in rows for value in (row['id'],row['agent'],row['ts'])]
            matches=db.execute('WITH candidates(id,agent,ts) AS (VALUES '+candidates+''')
              SELECT c.id,a.queue,a.reason,a.starts,MIN(COALESCE(a.ends,?),?) ends
              FROM candidates c JOIN report_activity a ON a.canonical_agent=c.agent
              WHERE '''+clause+" AND a.state='paused' AND a.starts<=c.ts AND COALESCE(a.ends,?)>c.ts LIMIT 4001",
                               (*params,observed,observed,*args,observed)).fetchall()
            if len(matches)>4000:raise QueryDeadline('outbound_membership_limit_narrow_scope')
            memberships={row['id']:[] for row in rows}
            for match in matches:
                memberships[match['id']].append({key:match[key] for key in ('queue','reason','starts','ends')})
            for row in rows:
                row['memberships']=memberships[row['id']]
                # Raw identifiers are not needed by the presentation layer.
                row.pop('uid');row.pop('linkedid')
    return dict(rows=rows,next=[rows[-1]['ts'],rows[-1]['id']] if more and rows else None,
                coverage='known_endpoint_pair_and_observed_pause',unit='cdr_segment',direction=direction,
                duration_definition='full_segment_billsec_not_pause_overlap',observed_until=observed)
