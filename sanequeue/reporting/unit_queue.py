"""Organization-scoped historical queue summary; never reads a PBX directly."""
import math
from sanequeue.security.unit_scope import ScopeConflict
from .unit_cdr import UnitAccessDenied


def summary(archive,store,username,start,end,*,sla_seconds=20):
    if archive.pbx!=store.pbx:raise UnitAccessDenied('unit_pbx_mismatch')
    start,end=float(start),float(end);sla_seconds=float(sla_seconds)
    if not all(math.isfinite(x) for x in (start,end,sla_seconds)) or start<0 or end<=start or end-start>366*86400 or not 1<=sla_seconds<=3600:
        raise ValueError('invalid_unit_queue_range')
    scope=store.resolve_queues(username,'summary',start,end)
    if not scope['units']:raise UnitAccessDenied('unit_summary_not_granted')
    fragments=[];args=[archive.pbx,start,end]
    for item in scope['queue_assignments']:
        fragments.append('(queue=? AND entered>=?'+(' AND entered<? AND ended<=?' if item['ends'] is not None else '')+')')
        args.extend((item['queue'],item['starts']))
        if item['ends'] is not None:args.extend((item['ends'],item['ends']))
    clause='pbx=? AND entered>=? AND entered<? AND ended IS NOT NULL AND ended>=entered AND ('+(' OR '.join(fragments) if fragments else '0')+')'
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
