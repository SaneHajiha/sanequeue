"""Evidence-only endpoint work metrics over selected queue memberships.

Talk is a queue segment, never a whole conversation. ACW is measured only from
explicit wrap_up/wrapup/after_call_work states, never from gaps or pause reasons.
Missing state/identity/boundary evidence makes ratios NULL, not zero.
"""
import json
import math
import time

from .queries import _where
from .store import Archive,QueryDeadline

MAX_INTERVALS=10000
MAX_VISITS=10000
MAX_AGENTS=2000
_ACW={'wrap_up','wrapup','after_call_work'}
_CALL={'on_call','hold'}
_KNOWN=_ACW|_CALL|{'available','ringing','busy','paused','offline','removed'}
_COVERAGE={'observed','source_replaced','source_row_missing'}


def _overlap_sql(table,columns,clause):
    # Closed intervals seek their end rather than scanning every earlier start.
    # Open intervals live in their own small partial index. There is no ORDER BY:
    # metrics are commutative and sorting would consume all matches before LIMIT.
    if table=='report_visits':begin,finish,prefix='entered','ended','rv'
    elif table=='report_activity':begin,finish,prefix='starts','ends','ra'
    else:raise ValueError('invalid_metric_table')
    return (f'SELECT {columns} FROM {table} INDEXED BY {prefix}_queue_ended WHERE '+clause+
        f' AND {finish} IS NOT NULL AND {finish}>? AND {begin}<? AND {begin}>=? UNION ALL '+
        f'SELECT {columns} FROM {table} INDEXED BY {prefix}_queue_open WHERE '+clause+
        f' AND {finish} IS NULL AND {begin}<? AND {begin}>=? LIMIT ?')


def _union(intervals):
    output=[]
    for first,last in sorted(intervals):
        if first>=last:continue
        if output and first<=output[-1][1]:output[-1][1]=max(output[-1][1],last)
        else:output.append([first,last])
    return output


def _seconds(intervals):return sum(last-first for first,last in _union(intervals))


def _intersection(left,right):
    left=_union(left);right=_union(right);result=[];i=j=0
    while i<len(left) and j<len(right):
        first=max(left[i][0],right[j][0]);last=min(left[i][1],right[j][1])
        if first<last:result.append([first,last])
        if left[i][1]<right[j][1]:i+=1
        else:j+=1
    return result


def _stamp(value):
    if isinstance(value,bool):raise ValueError('invalid_agent_metric_time')
    value=float(value)
    if not math.isfinite(value) or value<0:raise ValueError('invalid_agent_metric_time')
    return value


def report(archive,scope,start,end,*,now=None):
    _where(archive.pbx,scope,start,end)
    now=_stamp(time.time() if now is None else now)
    first=max(float(start),_stamp(scope.not_before));last=min(float(end),now)
    deadline=time.monotonic()+min(5,archive.read_seconds)
    def check():
        if time.monotonic()>=deadline:raise QueryDeadline('agent_metric_deadline')
    groups={}
    def group(agent):
        if agent not in groups:
            if len(groups)>=MAX_AGENTS:raise QueryDeadline('agent_metric_agent_limit')
            groups[agent]=dict(agent=agent,observed=[],duty=[],calls=[],acw=[],unknown=[],talk=[],
                acw_rows=[],completed_ends=set(),answered_queue_segments=0,completed_queue_segments=0,
                known_talk_segment_count=0,unknown_talk_segment_count=0,known_talk_segment_seconds=0,
                reasons=set(),activity_identity_verified=True)
        return groups[agent]
    check();bounded=Archive(archive.path,pbx=archive.pbx,read_seconds=max(.001,min(archive.read_seconds,deadline-time.monotonic())))
    with bounded.reader() as db:
        checkpoint=db.execute('SELECT value FROM checkpoints WHERE pbx=? AND source=?',(archive.pbx,'activity_cache')).fetchone()
        checkpoint=json.loads(checkpoint[0]) if checkpoint else {}
        observed=_stamp(checkpoint.get('observed',0));evidence_end=min(last,observed)
        projection=db.execute('SELECT after_id FROM report_projection WHERE pbx=?',(archive.pbx,)).fetchone()
        latest=db.execute('SELECT MAX(id) FROM events WHERE pbx=?',(archive.pbx,)).fetchone()[0]
        caught_up=bool(projection and projection[0]>=(latest or 0))
        marks=','.join('?' for _ in scope.queues)
        clause='pbx=? AND queue IN ('+marks+')' if scope.queues else 'pbx=? AND 0'
        args=[archive.pbx,*scope.queues];activity_clause=clause;activity_args=list(args)
        if scope.self_only:
            if scope.agents:
                names=','.join('?' for _ in scope.agents)
                clause+=' AND agent IN ('+names+')';args.extend(scope.agents)
                activity_clause+=' AND (agent IN ('+names+') OR canonical_agent IN ('+names+'))'
                activity_args.extend((*scope.agents,*scope.agents))
            else:clause+=' AND 0';activity_clause+=' AND 0'
        activity=[];visits=[]
        eligible=bool(scope.queues) and (not scope.self_only or bool(scope.agents))
        if first<evidence_end and eligible:
            activity=db.execute(_overlap_sql('report_activity',
                'queue,agent,canonical_agent,state,reason,starts,ends,on_duty,coverage',activity_clause),
                (*activity_args,first,evidence_end,0,*activity_args,evidence_end,0,MAX_INTERVALS+1)).fetchall()
            if len(activity)>MAX_INTERVALS:raise QueryDeadline('agent_metric_interval_limit')
        if first<last and eligible:
            # Include carry-in segments for explicit censoring, but never any
            # call entered before the user's endpoint assignment cutoff.
            visits=db.execute(_overlap_sql('report_visits',
                'queue,agent,entered,answered,ended,talk_seconds,coverage,outcome',clause),
                (*args,first,last,scope.not_before,*args,last,scope.not_before,MAX_VISITS+1)).fetchall()
            if len(visits)>MAX_VISITS:raise QueryDeadline('agent_metric_visit_limit')
    by_alias={}
    for row in activity:
        check();agent=row['canonical_agent'] or row['agent'];item=group(agent)
        left=max(first,row['starts']);right=min(evidence_end,row['ends'] if row['ends'] is not None else observed)
        if left>=right:continue
        for alias in {row['agent'],row['canonical_agent']}:
            if alias:by_alias.setdefault((row['queue'],alias),[]).append((agent,left,right))
        if row['coverage'] not in _COVERAGE or row['coverage']!='observed' and row['ends'] is None:
            item['reasons'].add('unknown_activity_interval');continue
        item['observed'].append([left,right])
        if row['on_duty']:item['duty'].append([left,right])
        state=row['state']
        if state not in _KNOWN:item['unknown'].append([left,right])
        if state in _CALL:item['calls'].append([left,right])
        if state in _ACW:
            item['acw'].append([left,right]);item['acw_rows'].append((row['queue'],row['starts'],row['ends']))
            if row['starts']<first or row['ends'] is None or row['ends']>last:item['reasons'].add('censored_acw_interval')
    for visit in visits:
        check()
        if visit['answered'] is None or visit['answered']>=last:continue
        left=max(first,visit['answered']);right=min(last,visit['ended'] if visit['ended'] is not None else last)
        candidates=set()
        for candidate,a,b in by_alias.get((visit['queue'],visit['agent']),[]):
            check()
            if a<right and b>left:candidates.add(candidate)
        verified=len(candidates)==1
        agent=next(iter(candidates)) if verified else visit['agent']
        item=group(agent)
        if not verified:item['activity_identity_verified']=False;item['reasons'].add('activity_identity_unverified')
        item['answered_queue_segments']+=1
        if visit['entered']<first or visit['answered']<first or visit['ended'] is None or visit['ended']>last:
            item['reasons'].add('censored_queue_segment')
        completed=visit['ended'] is not None and visit['ended']<=last
        if completed:
            item['completed_queue_segments']+=1;item['completed_ends'].add((visit['queue'],visit['ended']))
        talk=visit['talk_seconds']
        if talk is None or not completed or visit['coverage']!='observed':
            item['unknown_talk_segment_count']+=1;item['reasons'].add('queue_talk_evidence_incomplete')
        else:
            item['known_talk_segment_count']+=1;item['known_talk_segment_seconds']+=talk
            if visit['ended']-visit['answered']!=talk:item['reasons'].add('queue_talk_clock_mismatch')
        if left<right:item['talk'].append([left,right])
    result=[]
    for agent,item in sorted(groups.items()):
        check();reasons=item['reasons'];observed_seconds=_seconds(item['observed']);duty=_seconds(item['duty'])
        acw=_seconds(item['acw']) if item['acw'] else None;calls=_seconds(item['calls']);talk=_seconds(item['talk'])
        complete=last>first and abs(observed_seconds-(last-first))<1e-6
        if not observed:reasons.add('activity_heartbeat_unavailable')
        if not caught_up:reasons.add('projection_incomplete')
        if not complete:reasons.add('activity_coverage_incomplete')
        if item['unknown']:reasons.add('unknown_activity_state')
        if acw is None:reasons.add('explicit_acw_unavailable')
        if not item['completed_queue_segments']:reasons.add('no_completed_queue_segments')
        if _seconds(item['talk'])+1e-6<sum(b-a for a,b in item['talk']):reasons.add('overlapping_queue_segments')
        if _seconds(_intersection(item['acw'],item['calls']))>1e-6:reasons.add('acw_on_call_overlap')
        if talk-_seconds(_intersection(item['talk'],item['calls']))>1e-6:reasons.add('queue_talk_state_incomplete')
        if any((queue,begin) not in item['completed_ends'] for queue,begin,_ in item['acw_rows']):
            reasons.add('acw_queue_boundary_unverified')
        work=_union(item['calls']+item['acw']);work_seconds=_seconds(work)
        if work_seconds-_seconds(_intersection(work,item['duty']))>1e-6:reasons.add('work_outside_on_duty_evidence')
        if duty<=0:reasons.add('on_duty_denominator_unavailable')
        aht=(talk+acw)/item['completed_queue_segments'] if not reasons else None
        occupancy=100*work_seconds/duty if not reasons else None
        result.append(dict(agent=agent,answered_queue_segments=item['answered_queue_segments'],
            completed_queue_segments=item['completed_queue_segments'],known_talk_segment_count=item['known_talk_segment_count'],
            unknown_talk_segment_count=item['unknown_talk_segment_count'],known_talk_segment_seconds=item['known_talk_segment_seconds'],
            unique_queue_talk_seconds=talk,observed_seconds=observed_seconds,on_duty_seconds=duty,
            on_call_seconds=calls,acw_seconds=acw,known_acw_seconds=acw or 0,occupied_seconds=work_seconds,
            aht_seconds=aht,occupancy_percent=occupancy,coverage=dict(complete=not reasons,
                presence_complete=complete,activity_identity_verified=item['activity_identity_verified'],reasons=sorted(reasons))))
    totals=dict(agents=len(result),answered_queue_segments=sum(row['answered_queue_segments'] for row in result),
        completed_queue_segments=sum(row['completed_queue_segments'] for row in result),
        known_talk_segment_count=sum(row['known_talk_segment_count'] for row in result),
        unknown_talk_segment_count=sum(row['unknown_talk_segment_count'] for row in result),
        known_talk_segment_seconds=sum(row['known_talk_segment_seconds'] for row in result),
        unique_queue_talk_seconds=sum(row['unique_queue_talk_seconds'] for row in result),
        on_duty_seconds=sum(row['on_duty_seconds'] for row in result),known_acw_seconds=sum(row['known_acw_seconds'] for row in result),
        aht_seconds=None,occupancy_percent=None)
    if result and all(row['coverage']['complete'] for row in result):
        totals['aht_seconds']=(totals['unique_queue_talk_seconds']+totals['known_acw_seconds'])/totals['completed_queue_segments']
        totals['occupancy_percent']=100*sum(row['occupied_seconds'] for row in result)/totals['on_duty_seconds']
    return dict(start=first,end=last,observed_until=observed or None,agents=result,totals=totals,
        coverage=dict(complete=bool(result) and all(row['coverage']['complete'] for row in result),projection_caught_up=caught_up),
        unit='queue_segment',complete_conversation=False,complete_history=False,
        definitions=dict(aht='unique_queue_segment_talk_plus_explicit_acw_per_completed_queue_segment',
            occupancy='union_observed_on_call_hold_and_acw_over_union_on_duty_selected_memberships',
            acw='explicit_wrap_up_wrapup_after_call_work_only_no_gap_or_pause_reason_inference',
            attribution='exact_queue_acw_start_matches_observed_queue_segment_end',
            cohort='answered_queue_segments_overlapping_range_entered_after_assignment_cutoff_censored_segments_disable_ratios',
            known_talk_segment_seconds='source_full_completed_segment_seconds_even_if_report_boundary_censors_segment',
            talk='queue_segment_includes_source_hold_semantics_not_whole_conversation',
            shared_time='union_across_visible_queue_memberships_per_frozen_endpoint',
            totals='sum_agent_person_seconds_ratios_only_when_every_agent_has_complete_evidence',
            unknown='null_ratio_or_acw_is_unknown_not_zero'))
