"""Bounded, evidence-based queue visit outcomes, not PBX-wide calls."""
from datetime import datetime
import math
from .analytics import ZONE
from .queries import _where

MAX_VISITS=50000
UNANSWERED=('abandoned','exitwithtimeout','exitwithkey','exitempty')


def class_clause(kind):
    """SQL equivalent of _classify, restricted to observed queue entries."""
    if kind=='answered':
        return (" AND COALESCE(coverage,'')<>'missing_entry' AND COALESCE(outcome,'') NOT IN "
                "('abandoned','exitwithtimeout','exitwithkey','exitempty') "
                "AND (answered IS NOT NULL OR outcome='answered')")
    if kind=='unanswered':
        return (" AND COALESCE(coverage,'')<>'missing_entry' AND outcome IN "
                "('abandoned','exitwithtimeout','exitwithkey','exitempty') AND answered IS NULL")
    raise ValueError('invalid_queue_outcome_class')


def _empty():
    return dict(visits=0,answered=0,unanswered=0,unresolved=0,
                abandoned=0,exitwithtimeout=0,exitwithkey=0,exitempty=0,
                wait_samples=0,wait_sum=0.0,talk_samples=0,talk_sum=0.0,
                answered_wait_samples=0,answered_wait_sum=0.0,
                answered_talk_samples=0,answered_talk_sum=0.0,
                unanswered_wait_samples=0,unanswered_wait_sum=0.0)


def _classify(row):
    outcome=row['outcome']
    answered=row['answered'] is not None or outcome=='answered'
    if outcome in UNANSWERED:return 'unresolved' if answered else 'unanswered'
    if answered:return 'answered'
    return 'unresolved'


def _add(item,row):
    category=_classify(row);item['visits']+=1;item[category]+=1
    if category=='unanswered':item[row['outcome']]+=1
    for field in ('wait','talk'):
        value=row[field+'_seconds']
        if type(value) in (int,float) and math.isfinite(value) and 0<=value<=315360000:
            item[field+'_samples']+=1;item[field+'_sum']+=value
            key=category+'_'+field
            if key+'_samples' in item:
                item[key+'_samples']+=1;item[key+'_sum']+=value


def _finish(item):
    for field in ('wait','talk','answered_wait','answered_talk','unanswered_wait'):
        total=item.pop(field+'_sum');count=item[field+'_samples']
        item['average_'+field+'_seconds']=total/count if count else None
    denominator=item['answered']+item['unanswered']
    item['known_outcomes']=denominator
    item['answered_percent_of_known']=100*item['answered']/denominator if denominator else None
    item['unanswered_percent_of_known']=100*item['unanswered']/denominator if denominator else None
    return item


def report(archive,scope,start,end):
    clause,args=_where(archive.pbx,scope,start,end)
    with archive.reader() as db:
        rows=db.execute('SELECT queue,entered,answered,outcome,coverage,wait_seconds,talk_seconds '
                        'FROM report_visits WHERE '+clause+' LIMIT ?',(*args,MAX_VISITS+1)).fetchall()
        projection=db.execute('SELECT after_id,updated FROM report_projection WHERE pbx=?',(archive.pbx,)).fetchone()
    if len(rows)>MAX_VISITS:return dict(state='limited',reason='queue_outcome_visit_limit',maximum_visits=MAX_VISITS)
    totals=_empty();queues={};hours={};days={};missing=0
    for row in rows:
        if row['coverage']=='missing_entry':missing+=1;continue
        local=datetime.fromtimestamp(row['entered'],ZONE);day=local.date().isoformat();hour=local.hour
        for item in (totals,queues.setdefault(row['queue'],_empty()),hours.setdefault(hour,_empty()),days.setdefault(day,_empty())):
            _add(item,row)
    return dict(state='available',start=float(start),end=float(end),timezone='Asia/Tehran',unit='queue_visit',
        totals=_finish(totals),missing_entry_visits=missing,
        queues=[dict(queue=k,**_finish(v)) for k,v in sorted(queues.items())],
        hours=[dict(hour=k,**_finish(v)) for k,v in sorted(hours.items())],
        days=[dict(day=k,**_finish(v)) for k,v in sorted(days.items())],
        projection=dict(projection) if projection else None,
        contract=dict(range_basis='queue_entry',answered='connected_or_completed_evidence',
                      unanswered=list(UNANSWERED),unresolved_includes_open_or_conflicting=True,
                      missing_entry_excluded=True,not_unique_conversations=True,
                      rate_denominator='answered_plus_unanswered_known_outcomes',
                      exit_empty_is_not_proof_no_staff=True,maximum_visits=MAX_VISITS))
