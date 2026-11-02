"""Scoped endpoint rankings from known queue visits, never a quality score.

Counted units are queue visits/segments, not unique conversations or customers.
Local/numeric aliases require contemporaneous recorded canonical identity;
the current PBX inventory is never used to rewrite historical membership.
"""
import math
import re
import sqlite3
import time

from .agent_metrics import _overlap_sql
from .queries import Scope,_where
from .store import Archive,QueryDeadline

MAX_VISITS=10000
MAX_INTERVALS=10000
MAX_AGENTS=2000
_ENDPOINT=re.compile(r'(?:PJSIP|SIP|IAX2|DAHDI)/[A-Za-z0-9_.+-]{1,128}\Z')
_METRICS={'answered_count':'descending','avg_queue_talk_seconds':'ascending'}


class _Limit(RuntimeError):pass


def _number(value):
    return type(value) in (int,float) and math.isfinite(value) and value>=0


def rank_agents(archive,scope,start,end,*,metric='answered_count',min_samples=5,top=10):
    if not isinstance(scope,Scope) or type(scope.self_only) is not bool:raise ValueError('invalid_agent_ranking_scope')
    if (not isinstance(scope.queues,(tuple,list)) or not isinstance(scope.agents,(tuple,list))
        or any(not isinstance(value,str) or not 0<len(value)<=128 or not value.isprintable() for value in scope.queues)
        or any(not isinstance(value,str) or not 0<len(value)<=256 or not value.isprintable() for value in scope.agents)):
        raise ValueError('invalid_agent_ranking_scope')
    if not _number(scope.not_before):raise ValueError('invalid_agent_ranking_cutoff')
    if not isinstance(metric,str) or metric not in _METRICS:raise ValueError('invalid_agent_ranking_metric')
    if type(min_samples) is not int or not 1<=min_samples<=100:raise ValueError('invalid_agent_ranking_samples')
    if type(top) is not int or not 1<=top<=20:raise ValueError('invalid_agent_ranking_top')
    if type(start) not in (int,float) or type(end) not in (int,float):raise ValueError('invalid_report_range')
    clause,args=_where(archive.pbx,scope,start,end)
    first=max(float(start),scope.not_before)
    base=dict(start=float(start),end=float(end),effective_start=first,metric=metric,
        direction=_METRICS[metric],min_samples=min_samples,top=top,rows=[],unit='queue_visit',
        talk_unit='completed_queue_segment',conversation_unique=False,quality_score=None,
        lower_talk_is_not_quality=True,complete_source_coverage=False,
        sample_unit='answered_queue_visits' if metric=='answered_count' else 'completed_segments_with_known_talk',
        time_filter='entered in [max(start, assignment_cutoff), end); answered before end',
        average_definition='sum known completed queue-segment talk / known completed segment count',
        identity='observed_endpoint_or_contemporaneous_activity_alias',projection=None)
    def unavailable(state,reason):return dict(base,state=state,reason=reason)
    if not scope.queues or scope.self_only and not scope.agents or first>=end:
        return unavailable('empty','no_scoped_visits')
    deadline=time.monotonic()+min(2,archive.read_seconds)
    def check():
        if time.monotonic()>=deadline:raise _Limit('ranking_deadline')
    try:
        bounded=Archive(archive.path,pbx=archive.pbx,read_seconds=min(2,archive.read_seconds))
        with bounded.reader() as db:
            projection=db.execute('SELECT after_id,updated FROM report_projection WHERE pbx=?',(archive.pbx,)).fetchone()
            version=db.execute('SELECT version FROM report_projection_version WHERE pbx=?',(archive.pbx,)).fetchone()
            head=db.execute('SELECT MAX(id) FROM events WHERE pbx=?',(archive.pbx,)).fetchone()[0] or 0
            if not projection or not version or version[0]<10:return unavailable('unavailable','projection_unavailable')
            base['projection']=dict(projection)
            if projection['after_id']!=head:return unavailable('unavailable','projection_not_current')
            visits=db.execute('''SELECT queue,CASE WHEN length(agent)<=256 THEN agent END agent,
              entered,answered,ended,talk_seconds,coverage,outcome
              FROM report_visits INDEXED BY rv_queue_time WHERE '''+clause+' LIMIT ?',(*args,MAX_VISITS+1)).fetchall()
            if len(visits)>MAX_VISITS:raise _Limit('ranking_visit_limit')
            known=[row for row in visits if _number(row['answered']) and row['entered']<=row['answered']<end
                   and row['coverage'] in ('observed','missing_end')]
            aliases_needed=any(not isinstance(row['agent'],str) or not _ENDPOINT.fullmatch(row['agent']) for row in known)
            activity=[]
            if aliases_needed:
                activity_clause='pbx=? AND queue IN ('+','.join('?' for _ in scope.queues)+')'
                activity_args=[archive.pbx,*scope.queues]
                if scope.self_only:
                    marks=','.join('?' for _ in scope.agents)
                    activity_clause+=' AND (agent IN ('+marks+') OR canonical_agent IN ('+marks+'))'
                    activity_args.extend((*scope.agents,*scope.agents))
                activity=db.execute(_overlap_sql('report_activity',
                    'queue,CASE WHEN length(agent)<=256 THEN agent END agent,CASE WHEN length(canonical_agent)<=256 THEN canonical_agent END canonical_agent,starts,ends,coverage',activity_clause),
                    (*activity_args,first,end,0,*activity_args,end,0,MAX_INTERVALS+1)).fetchall()
                if len(activity)>MAX_INTERVALS:raise _Limit('ranking_identity_interval_limit')
        by_alias={}
        for interval in activity:
            check();canonical=interval['canonical_agent']
            if interval['coverage']!='observed' or not isinstance(canonical,str) or not _ENDPOINT.fullmatch(canonical):continue
            by_alias.setdefault((interval['queue'],interval['agent']),[]).append(interval)
        agents={}
        for visit in known:
            check();agent=visit['agent']
            if not isinstance(agent,str) or not _ENDPOINT.fullmatch(agent):
                candidates=set()
                for interval in by_alias.get((visit['queue'],agent),[]):
                    check()
                    if interval['starts']<=visit['answered'] and (interval['ends'] is None or visit['answered']<interval['ends']):candidates.add(interval['canonical_agent'])
                if len(candidates)!=1:return unavailable('unavailable','agent_identity_unresolved')
                agent=next(iter(candidates))
            if agent not in agents:
                if len(agents)>=MAX_AGENTS:raise _Limit('ranking_agent_limit')
                agents[agent]=dict(agent=agent,answered_count=0,talk=[])
            item=agents[agent];item['answered_count']+=1
            answered,ended,talk=visit['answered'],visit['ended'],visit['talk_seconds']
            if (visit['coverage']=='observed' and visit['outcome']=='answered' and _number(ended)
                and answered<=ended<=end and _number(talk) and talk<=315360000
                and abs(ended-answered-talk)<=2):item['talk'].append(talk)
        rows=[]
        for agent,item in agents.items():
            check();count=len(item['talk']);average=math.fsum(item['talk'])/count if count else None
            samples=item['answered_count'] if metric=='answered_count' else count
            if samples<min_samples:continue
            value=item['answered_count'] if metric=='answered_count' else average
            rows.append(dict(agent=agent,value=value,answered_count=item['answered_count'],
                talk_known_count=count,talk_unknown_count=item['answered_count']-count,
                avg_queue_talk_seconds=average,sample_count=samples))
        rows.sort(key=lambda row:((-row['value'] if metric=='answered_count' else row['value']),row['agent']))
        rank=0;previous=None
        for position,row in enumerate(rows,1):
            if position==1 or row['value']!=previous:rank=position
            row['rank']=rank;previous=row['value']
        selected=rows[:top]
        return dict(base,state='available' if selected else 'empty',reason=None if selected else 'minimum_samples_not_met',
            rows=selected,eligible_agent_count=len(rows),known_endpoint_count=len(agents),
            top_truncated=len(rows)>top,tie_at_boundary=len(rows)>top and rows[top-1]['value']==rows[top]['value'])
    except (QueryDeadline,_Limit) as error:
        return unavailable('limited',str(error) if isinstance(error,_Limit) else 'ranking_deadline')
    except (OSError,sqlite3.Error):return unavailable('unavailable','archive_unavailable')
