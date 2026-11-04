"""Organization-scoped historical queue summary; never reads a PBX directly."""
import math
import hashlib
import json
from sanequeue.security.unit_scope import ScopeConflict
from .unit_cdr import UnitAccessDenied
from .privacy import display_number


def _scope(archive,store,username,start,end,capability):
    if archive.pbx!=store.pbx:raise UnitAccessDenied('unit_pbx_mismatch')
    start,end=float(start),float(end)
    if not all(math.isfinite(x) for x in (start,end)) or start<0 or end<=start or end-start>366*86400:
        raise ValueError('invalid_unit_queue_range')
    scope=store.resolve_queues(username,capability,start,end)
    if not scope['units']:raise UnitAccessDenied('unit_queue_not_granted')
    fragments=[];args=[archive.pbx,start,end]
    for item in scope['queue_assignments']:
        fragments.append('(queue=? AND entered>=?'+(' AND entered<? AND ended<=?' if item['ends'] is not None else '')+')')
        args.extend((item['queue'],item['starts']))
        if item['ends'] is not None:args.extend((item['ends'],item['ends']))
    clause='pbx=? AND entered>=? AND entered<? AND ended IS NOT NULL AND ended>=entered AND ('+(' OR '.join(fragments) if fragments else '0')+')'
    return start,end,scope,clause,args


def summary(archive,store,username,start,end,*,sla_seconds=20):
    sla_seconds=float(sla_seconds)
    if not math.isfinite(sla_seconds) or not 1<=sla_seconds<=3600:raise ValueError('invalid_unit_queue_range')
    start,end,scope,clause,args=_scope(archive,store,username,start,end,'summary')
    with archive.reader() as db:
        rows=[dict(row) for row in db.execute('''SELECT queue,COUNT(*) visits,
          SUM(answered IS NOT NULL OR outcome='answered') answered,
          SUM(outcome='abandoned') abandoned,SUM(outcome='transferred') transferred,
          SUM(coverage<>'observed') incomplete,AVG(wait_seconds) average_wait_seconds,
          AVG(talk_seconds) average_talk_seconds,
          SUM((answered IS NOT NULL OR outcome='answered') AND wait_seconds IS NOT NULL) sla_known,
          SUM((answered IS NOT NULL OR outcome='answered') AND wait_seconds<=?) sla_met
          FROM report_visits WHERE '''+clause+' GROUP BY queue ORDER BY queue',(sla_seconds,*args))]
    for row in rows:row['sla_percent']=100*row['sla_met']/row['sla_known'] if row['sla_known'] else None
    if not store.still_current(scope):raise ScopeConflict('unit_scope_changed')
    return dict(start=start,end=end,queues=rows,unit='queue_visit',scope='organization_unit',
                sla_seconds=sla_seconds,sla_definition='answered_with_known_wait',complete_history=False,
                eligibility='closed_visits_contained_in_assignment')


def visits(archive,store,username,start,end,*,cursor=None,limit=50,secret,allow_full=False):
    if type(limit) is not int or not 1<=limit<=100:raise ValueError('invalid_unit_page_limit')
    start,end,scope,clause,args=_scope(archive,store,username,start,end,'call_details')
    numbers=store.resolve_queues(username,'full_numbers',start,end)
    if numbers['revision']!=scope['revision']:raise ScopeConflict('unit_scope_changed')
    query_hash=hashlib.sha256(json.dumps(['unit_queue_visits',start,end,limit],separators=(',',':')).encode()).hexdigest()
    before=store.load_cursor(username,scope,query_hash,cursor) if cursor else None
    if before:
        clause+=' AND (entered<? OR (entered=? AND id<?))';args.extend((before[0],before[0],before[1]))
    with archive.reader() as db:
        raw=db.execute('SELECT id,queue,entered,ended,caller,outcome,wait_seconds,talk_seconds,coverage FROM report_visits WHERE '+clause+
                       ' ORDER BY entered DESC,id DESC LIMIT ?',(*args,limit+1)).fetchall()
    more=len(raw)>limit;raw=raw[:limit];rows=[]
    for item in raw:
        full=allow_full and any(x['queue']==item['queue'] and x['starts']<=item['entered'] and
             (x['ends'] is None or item['ended']<=x['ends']) for x in numbers['queue_assignments'])
        rows.append(dict(queue=item['queue'],entered=item['entered'],ended=item['ended'],outcome=item['outcome'],
                         wait_seconds=item['wait_seconds'],talk_seconds=item['talk_seconds'],coverage=item['coverage'],
                         caller=display_number(item['caller'],mode='full' if full else 'masked',secret=secret,
                                               tenant='default',pbx=archive.pbx,version='1')))
    next_cursor=store.save_cursor(username,scope,query_hash,(raw[-1]['entered'],raw[-1]['id'])) if more and raw else None
    if not store.still_current(scope):raise ScopeConflict('unit_scope_changed')
    return dict(start=start,end=end,rows=rows,next=next_cursor,unit='queue_visit',scope='organization_unit',
                eligibility='closed_visits_contained_in_assignment',audio_available=False,complete_history=False)
