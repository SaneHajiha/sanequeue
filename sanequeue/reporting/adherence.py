"""Evidence-based, queue-aware shift adherence without PBX changes.

agent_aliases is None, a mapping, or callable(agent, starts, ends). A proof is
{agent: canonical_group, aliases: [exact interfaces], valid_from: timestamp,
 valid_until: timestamp_or_None}. It must cover the reportable shift window.
Without a resolver only exact SIP/PJSIP/Local interfaces are recognized.

Scheduled time is elapsed planned time. Heartbeat limits evidence, not the
schedule: stale or missing observations remain unknown, never absent. A shift
earns credit from its scheduled queue; agent totals union overlapping shifts.
"""
import json
import math
import re
import time

from .queries import Scope,_scope,_where
from .store import Archive,QueryDeadline

MAX_SHIFTS=2000
MAX_INTERVALS=10000
MAX_GROUPS=10000
_EXPLICIT=re.compile(r'(?:(?:SIP|PJSIP)/[^/\s]{1,128}|Local/[^@/\s]+@[^/\s]+(?:/n)?)\Z')
_KNOWN={'observed','source_replaced','source_row_missing'}
_EPS=1e-6


def _stamp(value):
    if isinstance(value,bool):raise ValueError('invalid_shift_time')
    value=float(value)
    if not math.isfinite(value) or not 0<=value<=32503680000:raise ValueError('invalid_shift_time')
    return value


def _union(intervals):
    result=[]
    for first,last in sorted(intervals):
        if last<=first:continue
        if result and first<=result[-1][1]:result[-1][1]=max(result[-1][1],last)
        else:result.append([first,last])
    if len(result)>MAX_INTERVALS:raise QueryDeadline('adherence_interval_limit_narrow_range')
    return result


def _seconds(intervals):
    return sum(last-first for first,last in intervals)


def _intersection(first,second):
    first,second=_union(first),_union(second);result=[];i=j=0
    while i<len(first) and j<len(second):
        begin=max(first[i][0],second[j][0]);end=min(first[i][1],second[j][1])
        if begin<end:result.append([begin,end])
        if first[i][1]<second[j][1]:i+=1
        else:j+=1
    if len(result)>MAX_INTERVALS:raise QueryDeadline('adherence_interval_limit_narrow_range')
    return result


def _identity(label,first,last,resolver):
    if resolver is None:
        return dict(agent=label,aliases=(label,),kind='exact_interface') if _EXPLICIT.fullmatch(label) else None
    proof=resolver(label,first,last) if callable(resolver) else resolver.get(label)
    if not isinstance(proof,dict):return None
    aliases=proof.get('aliases');agent=proof.get('agent')
    if not isinstance(agent,str) or not 1<=len(agent)<=256 or not agent.isprintable():return None
    if not isinstance(aliases,(list,tuple,set)) or not 1<=len(aliases)<=64:return None
    if any(not isinstance(alias,str) or not _EXPLICIT.fullmatch(alias) for alias in aliases):return None
    try:
        valid_from=_stamp(proof['valid_from'])
        valid_until=float('inf') if proof.get('valid_until') is None else _stamp(proof['valid_until'])
    except (ValueError,TypeError,KeyError):return None
    if valid_from>first or valid_until<last:return None
    return dict(agent=agent,aliases=tuple(sorted(set(aliases))),kind='as_of_assignment')


def _measure(windows,observed,duty,paused,reasons,*,deadline):
    if time.monotonic()>deadline:raise QueryDeadline('adherence_calculation_deadline')
    scheduled=_seconds(_union(windows));observed=_union(observed);duty=_union(duty);paused=_union(paused)
    seen=_seconds(observed);work=_seconds(duty);pause=_seconds(paused)
    complete=scheduled>0 and abs(scheduled-seen)<=_EPS
    result=dict(scheduled_seconds=scheduled,observed_seconds=seen,uncovered_seconds=max(0,scheduled-seen),
                on_duty_seconds=work,observed_not_on_duty_seconds=max(0,seen-work),paused_seconds=pause,
                exclusive_paused_seconds=max(0,pause-_seconds(_intersection(paused,duty))),
                coverage_percent=100*seen/scheduled if scheduled else None,
                on_duty_observed_percent=100*work/seen if seen else None,
                adherence_percent=100*work/scheduled if complete else None,coverage_complete=complete,
                pause_reasons=[],pause_reasons_nonadditive=True,paused_and_on_duty_nonadditive=True)
    for reason,intervals in sorted(reasons.items()):
        if time.monotonic()>deadline:raise QueryDeadline('adherence_calculation_deadline')
        intervals=_union(intervals)
        result['pause_reasons'].append(dict(reason=reason,seconds=_seconds(intervals),
            exclusive_seconds=max(0,_seconds(intervals)-_seconds(_intersection(intervals,duty)))))
    return result


def report(archive,scope,start,end,shifts,*,agent_aliases=None,now=None):
    _where(archive.pbx,scope,start,end)
    if not isinstance(shifts,(list,tuple)) or len(shifts)>MAX_SHIFTS:raise ValueError('shift_report_limit')
    if agent_aliases is not None and not callable(agent_aliases) and not isinstance(agent_aliases,dict):
        raise ValueError('invalid_shift_identity_resolver')
    now=_stamp(time.time() if now is None else now)
    first=max(float(start),_stamp(scope.not_before));last=min(float(end),now)
    deadline=time.monotonic()+min(5,archive.read_seconds)
    prepared=[];seen_ids=set()
    for shift in shifts:
        if time.monotonic()>deadline:raise QueryDeadline('adherence_calculation_deadline')
        if not isinstance(shift,dict):raise ValueError('invalid_shift')
        if shift.get('queue') not in scope.queues:continue
        begin,finish=_stamp(shift['starts']),_stamp(shift['ends'])
        if begin>=finish:raise ValueError('invalid_shift_period')
        planned_first=max(begin,first);planned_last=min(finish,float(end))
        if planned_first>=planned_last:continue
        ident=shift.get('id');label=shift.get('agent')
        if not isinstance(ident,(str,int)) or isinstance(ident,bool) or len(str(ident))>128:raise ValueError('invalid_shift_id')
        if ident in seen_ids:raise ValueError('duplicate_shift_id')
        seen_ids.add(ident)
        if not isinstance(label,str) or not 1<=len(label)<=256 or not label.isprintable():raise ValueError('invalid_shift_agent')
        clipped_last=min(finish,last)
        proof=_identity(label,planned_first,max(planned_first,clipped_last),agent_aliases)
        if scope.self_only and (proof is None or not set(proof['aliases']).issubset(scope.agents)):continue
        item=dict(id=ident,queue=shift['queue'],agent=label,starts=begin,ends=finish,
                  clipped_start=planned_first,clipped_end=clipped_last,
                  planned_seconds=planned_last-planned_first,identity_status='resolved' if proof else 'unknown',
                  canonical_agent=proof['agent'] if proof else None)
        prepared.append((item,proof))
    clause,args=_scope(archive.pbx,Scope(scope.queues))
    if scope.self_only:
        if not scope.agents:clause+=' AND 0'
        else:
            marks=','.join('?' for _ in scope.agents)
            clause+=' AND (agent IN ('+marks+') OR canonical_agent IN ('+marks+'))'
            args.extend((*scope.agents,*scope.agents))
    remaining=deadline-time.monotonic()
    if remaining<=0:raise QueryDeadline('adherence_calculation_deadline')
    bounded=Archive(archive.path,pbx=archive.pbx,read_seconds=min(archive.read_seconds,remaining))
    with bounded.reader() as db:
        checkpoint=db.execute('SELECT value FROM checkpoints WHERE pbx=? AND source=?',(archive.pbx,'activity_cache')).fetchone()
        checkpoint=json.loads(checkpoint[0]) if checkpoint else {}
        observed=_stamp(checkpoint.get('observed',0));rows=[]
        evidence_end=min(last,observed)
        if first<evidence_end and any(proof for _,proof in prepared):
            rows=db.execute('''SELECT queue,agent,canonical_agent,state,reason,starts,ends,on_duty,coverage
              FROM report_activity WHERE '''+clause+' AND starts<? AND COALESCE(ends,?)>? ORDER BY queue,starts LIMIT ?',
              (*args,evidence_end,observed,first,MAX_INTERVALS+1)).fetchall()
            if len(rows)>MAX_INTERVALS:raise QueryDeadline('adherence_interval_limit_narrow_range')
    by_queue={}
    for row in rows:
        if row['coverage'] not in _KNOWN or row['coverage']!='observed' and row['ends'] is None:continue
        begin=max(first,float(row['starts']));finish=min(evidence_end,float(row['ends']) if row['ends'] is not None else observed)
        if begin<finish:by_queue.setdefault(row['queue'],[]).append((row,begin,finish))
    output=[];agents={};groups=0
    for item,proof in prepared:
        if time.monotonic()>deadline:raise QueryDeadline('adherence_calculation_deadline')
        begin,finish=item['clipped_start'],item['clipped_end']
        windows=[[begin,finish]] if begin<finish else []
        if proof is None:
            item.update(scheduled_seconds=max(0,finish-begin),observed_seconds=None,uncovered_seconds=max(0,finish-begin),
                on_duty_seconds=None,observed_not_on_duty_seconds=None,paused_seconds=None,exclusive_paused_seconds=None,
                coverage_percent=None,on_duty_observed_percent=None,adherence_percent=None,coverage_complete=False,
                pause_reasons=[],first_login_at=None,first_on_duty_observed_at=None,tardiness_seconds=None,
                tardiness_status='unknown_identity')
            output.append(item);continue
        seen=[];duty=[];paused=[];reasons={};aliases=set(proof['aliases'])
        for index,(row,left,right) in enumerate(by_queue.get(item['queue'],[])):
            if index%128==0 and time.monotonic()>deadline:raise QueryDeadline('adherence_calculation_deadline')
            if row['agent'] not in aliases and row['canonical_agent'] not in aliases:continue
            left,right=max(left,begin),min(right,finish)
            if left>=right:continue
            seen.append([left,right])
            if row['on_duty']:duty.append([left,right])
            if row['state']=='paused':
                paused.append([left,right]);reasons.setdefault(row['reason'],[]).append([left,right])
        seen,duty,paused=_union(seen),_union(duty),_union(paused)
        item.update(_measure(windows,seen,duty,paused,reasons,deadline=deadline))
        login=duty[0][0] if duty else None
        full_prefix=login is not None and abs(begin-item['starts'])<=_EPS and abs(_seconds(_intersection(seen,[[item['starts'],login]]))-(login-item['starts']))<=_EPS
        item.update(first_on_duty_observed_at=login,first_login_at=login if full_prefix else None,
                    tardiness_seconds=login-item['starts'] if full_prefix else None,
                    tardiness_status='known' if full_prefix else 'partial_report_start' if begin>item['starts'] else 'no_login_or_incomplete_prefix')
        output.append(item);groups+=1+len(reasons)
        aggregate=agents.setdefault(proof['agent'],dict(agent=proof['agent'],scheduled=[],seen=[],duty=[],paused=[],reasons={},shift_count=0,
            known_tardy_shifts=0,known_on_time_shifts=0,unknown_login_shifts=0))
        for key,values in (('scheduled',windows),('seen',seen),('duty',duty),('paused',paused)):
            aggregate[key]=_union(aggregate[key]+values)
        for reason,values in reasons.items():aggregate['reasons'][reason]=_union(aggregate['reasons'].get(reason,[])+values)
        aggregate['shift_count']+=1
        aggregate['unknown_login_shifts']+=int(not full_prefix)
        aggregate['known_tardy_shifts']+=int(full_prefix and login>item['starts']+_EPS)
        aggregate['known_on_time_shifts']+=int(full_prefix and login<=item['starts']+_EPS)
        if groups>MAX_GROUPS:raise QueryDeadline('adherence_group_limit_narrow_scope')
    totals=[]
    for agent,aggregate in sorted(agents.items()):
        measure=_measure(aggregate['scheduled'],aggregate['seen'],aggregate['duty'],aggregate['paused'],aggregate['reasons'],deadline=deadline)
        groups+=1+len(aggregate['reasons'])
        if groups>MAX_GROUPS:raise QueryDeadline('adherence_group_limit_narrow_scope')
        measure.update(agent=agent,shift_count=aggregate['shift_count'],
                       **{key:aggregate[key] for key in ('known_tardy_shifts','known_on_time_shifts','unknown_login_shifts')})
        totals.append(measure)
    return dict(start=first,end=last,observed_until=observed or None,shifts=output,agents=totals,
                unknown_identity_shifts=sum(row['identity_status']=='unknown' for row in output),
                source_gaps=int(checkpoint.get('gaps',0)),per_shift_nonadditive=True,complete_history=False,
                definitions=dict(adherence='on_duty_over_elapsed_schedule_only_when_fully_observed',
                  observed_ratio='on_duty_over_observed_time_is_not_full_schedule_adherence',
                  scheduled_queue='credit_only_activity_in_a_queue_scheduled_at_that_time',
                  unknown='uncovered_time_is_unknown_not_absence',pause_reasons='overlap_across_queues_and_reasons_is_nonadditive',
                  tardiness='known_only_with_complete_coverage_from_actual_shift_start_to_first_on_duty',
                  future='future_scheduled_time_is_planned_not_elapsed'))
