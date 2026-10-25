"""Historical activity with coverage clipping and unioned multi-queue duty time."""
import time
import math
from .queries import _scope, _where
from .store import QueryDeadline


def summary(archive,scope,start,end,*,now=None):
    _where(archive.pbx,scope,start,end)  # Shared range and assignment validation.
    start=max(float(start),scope.not_before)
    end=min(float(end),time.time() if now is None else float(now))
    checkpoint=archive.checkpoint('activity_cache')
    observed=float(checkpoint.get('observed',0))
    clause,args=_scope(archive.pbx,scope)
    empty=dict(start=start,end=end,rows=[],agents=[],observed_until=observed or None,
               complete_history=False,source_gaps=int(checkpoint.get('gaps',0)),
               retention='no_automatic_deletion',unit='observed_queue_membership_interval')
    if start>=end or not observed:
        return empty
    clause+=' AND starts<? AND COALESCE(ends,?)>?'
    args.extend((end,observed,start))
    with archive.reader() as db:
        rows=[dict(r) for r in db.execute('''SELECT queue,agent,canonical_agent,state,reason,on_duty,
          SUM(MAX(0,MIN(COALESCE(ends,?),?)-MAX(starts,?))) seconds,
          MIN(MAX(starts,?)) first,MAX(MIN(COALESCE(ends,?),?)) last,
          SUM(coverage<>'observed') incomplete_intervals
          FROM report_activity WHERE '''+clause+''' GROUP BY queue,agent,canonical_agent,state,reason,on_duty
          HAVING seconds>0 ORDER BY queue,agent,state,reason LIMIT 2001''',
                                       (observed,end,start,start,observed,end,*args))]
        if len(rows)>2000:
            raise QueryDeadline('activity_group_limit_narrow_scope')
        intervals=db.execute('''SELECT canonical_agent agent,MAX(starts,?) first,
          MIN(COALESCE(ends,?),?) last FROM report_activity WHERE '''+clause+'''
          AND on_duty=1 ORDER BY canonical_agent,first,last LIMIT 10001''',(start,observed,end,*args)).fetchall()
        if len(intervals)>10000:
            raise QueryDeadline('activity_union_limit_narrow_range')
    unions={}
    for row in intervals:
        if row['last']<=row['first']:continue
        merged=unions.setdefault(row['agent'],[])
        if merged and row['first']<=merged[-1][1]:
            merged[-1][1]=max(merged[-1][1],row['last'])
        else:merged.append([row['first'],row['last']])
    agents={}
    for row in rows:
        item=agents.setdefault(row['canonical_agent'],dict(agent=row['canonical_agent'],membership_on_duty_seconds=0,
                                                unique_on_duty_seconds=0,paused_membership_seconds=0))
        if row['on_duty']:item['membership_on_duty_seconds']+=row['seconds']
        if row['state']=='paused':item['paused_membership_seconds']+=row['seconds']
    for agent,intervals in unions.items():
        agents[agent]['unique_on_duty_seconds']=sum(last-first for first,last in intervals)
    return dict(empty,rows=rows,agents=list(agents.values()))


def intervals(archive,scope,start,end,*,before=None,limit=100):
    _where(archive.pbx,scope,start,end)
    start=max(float(start),scope.not_before)
    observed=float(archive.checkpoint('activity_cache').get('observed',0))
    end=min(float(end),time.time())
    if not observed:return dict(rows=[],next=None)
    clause,args=_scope(archive.pbx,scope)
    clause+=' AND starts<? AND COALESCE(ends,?)>?'
    args.extend((end,observed,start))
    if before:
        if len(before)!=2 or not math.isfinite(float(before[0])) or len(str(before[1]))>128:
            raise ValueError('invalid_activity_cursor')
        clause+=' AND (starts<? OR (starts=? AND source_key<?))'
        args.extend((float(before[0]),float(before[0]),str(before[1])))
    limit=max(1,min(200,int(limit)))
    with archive.reader() as db:
        rows=[dict(r) for r in db.execute('''SELECT source_key id,queue,agent,state,reason,on_duty,
          starts,ends,MAX(starts,?) visible_start,MIN(COALESCE(ends,?),?) visible_end,coverage
          FROM report_activity WHERE '''+clause+' ORDER BY starts DESC,source_key DESC LIMIT ?',
                                       (start,observed,end,*args,limit+1))]
    more=len(rows)>limit;rows=rows[:limit]
    return dict(rows=rows,next=[rows[-1]['starts'],rows[-1]['id']] if more and rows else None)
