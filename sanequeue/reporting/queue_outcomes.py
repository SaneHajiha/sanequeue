"""Bounded, evidence-based queue visit outcomes, not PBX-wide calls."""
from datetime import datetime
import csv
import io
import math
from .analytics import ZONE
from .queries import _where

MAX_VISITS=50000
UNANSWERED=('abandoned','exitwithtimeout','exitwithkey','exitempty')
WAIT_BOUNDARIES=(0,10,20,30,60,120,300)


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
    wait_distribution={kind:dict(counts=[0]*len(WAIT_BOUNDARIES),unknown=0) for kind in ('answered','unanswered')}
    for row in rows:
        if row['coverage']=='missing_entry':missing+=1;continue
        category=_classify(row)
        if category in wait_distribution:
            value=row['wait_seconds'];distribution=wait_distribution[category]
            if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=315360000:
                distribution['unknown']+=1
            else:
                index=next((i for i in range(len(WAIT_BOUNDARIES)-1) if value<WAIT_BOUNDARIES[i+1]),len(WAIT_BOUNDARIES)-1)
                distribution['counts'][index]+=1
        local=datetime.fromtimestamp(row['entered'],ZONE);day=local.date().isoformat();hour=local.hour
        for item in (totals,queues.setdefault(row['queue'],_empty()),hours.setdefault(hour,_empty()),days.setdefault(day,_empty())):
            _add(item,row)
    return dict(state='available',start=float(start),end=float(end),timezone='Asia/Tehran',unit='queue_visit',
        totals=_finish(totals),missing_entry_visits=missing,
        queues=[dict(queue=k,**_finish(v)) for k,v in sorted(queues.items())],
        hours=[dict(hour=k,**_finish(v)) for k,v in sorted(hours.items())],
        days=[dict(day=k,**_finish(v)) for k,v in sorted(days.items())],
        wait_distribution={kind:dict(known=sum(item['counts']),unknown=item['unknown'],
            buckets=[dict(start_seconds=lower,end_seconds=WAIT_BOUNDARIES[i+1] if i+1<len(WAIT_BOUNDARIES) else None,count=item['counts'][i])
                     for i,lower in enumerate(WAIT_BOUNDARIES)]) for kind,item in wait_distribution.items()},
        projection=dict(projection) if projection else None,
        contract=dict(range_basis='queue_entry',answered='connected_or_completed_evidence',
                      unanswered=list(UNANSWERED),unresolved_includes_open_or_conflicting=True,
                      missing_entry_excluded=True,not_unique_conversations=True,
                      rate_denominator='answered_plus_unanswered_known_outcomes',
                      exit_empty_is_not_proof_no_staff=True,maximum_visits=MAX_VISITS,
                      wait_distribution='half_open_seconds_by_known_outcome_and_recorded_wait'))


def distribution_csv(result,kind,language,queues):
    if kind not in ('answered','unanswered') or language not in ('fa','en') or result.get('state')!='available':
        raise ValueError('invalid_wait_distribution_export')
    from .exports import persian_date
    def stamp(value):
        local=datetime.fromtimestamp(value,ZONE)
        return (persian_date(local.date()) if language=='fa' else local.date().isoformat())+local.strftime(' %H:%M:%S')
    fa=language=='fa';item=result['wait_distribution'][kind];output=io.StringIO(newline='');writer=csv.writer(output)
    headers=(['شروع تهران','پایان انحصاری تهران','صف‌های انتخابی','دسته','از ثانیه شامل','تا ثانیه غیرشامل','تعداد مراجعه','مخرج انتظار معلوم','درصد از انتظار معلوم'] if fa else
             ['period_start_tehran','period_end_exclusive_tehran','queues','category','start_inclusive_seconds','end_exclusive_seconds','visits','known_wait_denominator','percent_known_wait'])
    writer.writerow(headers);queue_text="'"+','.join(queues)
    category=('پاسخ‌داده' if kind=='answered' else 'بدون پاسخ') if fa else kind
    common=[stamp(result['start']),stamp(result['end']),queue_text,category]
    for bucket in item['buckets']:
        writer.writerow(common+[bucket['start_seconds'],bucket['end_seconds'] if bucket['end_seconds'] is not None else '',bucket['count'],item['known'],100*bucket['count']/item['known'] if item['known'] else ''])
    writer.writerow(common+[('نامعلوم' if fa else 'unknown'),'',item['unknown'],item['known'],''])
    return output.getvalue().encode('utf-8-sig')


def aggregate_csv(result, kind, table, language, queues):
    """Export the displayed aggregates with scope, denominators and missing data."""
    if (kind not in ('answered', 'unanswered') or table not in ('queues', 'days', 'hours', 'reasons')
            or table == 'reasons' and kind != 'unanswered' or language not in ('fa', 'en')
            or result.get('state') != 'available'):
        raise ValueError('invalid_queue_aggregate_export')
    from .exports import persian_date
    fa=language=='fa'
    def stamp(value):
        local=datetime.fromtimestamp(value,ZONE)
        return (persian_date(local.date()) if fa else local.date().isoformat())+local.strftime(' %H:%M:%S')
    def safe(value):
        # Queue identifiers and any future textual dimensions must stay literal in spreadsheets.
        return "'"+str(value) if value is not None else ''
    common=[stamp(result['start']),stamp(result['end']),safe(','.join(queues)),kind]
    output=io.StringIO(newline='');writer=csv.writer(output)
    base=['شروع تهران','پایان انحصاری تهران','صف‌های انتخابی','دسته'] if fa else ['period_start_tehran','period_end_exclusive_tehran','queues','category']
    if table=='reasons':
        writer.writerow(base+(['علت','تعداد','مخرج بدون پاسخ','درصد از بدون پاسخ'] if fa else ['reason','visits','unanswered_denominator','percent_unanswered']))
        total=result['totals']['unanswered']
        labels={'abandoned':'انصراف تماس‌گیرنده','exitwithtimeout':'پایان زمان انتظار','exitwithkey':'خروج با کلید','exitempty':'خروج صف خالی'}
        for name in UNANSWERED:
            value=result['totals'][name]
            writer.writerow(common+[(labels[name] if fa else name),value,total,100*value/total if total else ''])
    else:
        dimension=({'queues':'صف','days':'روز','hours':'ساعت ورود تهران'} if fa else {'queues':'queue','days':'day','hours':'entry_hour_tehran'})[table]
        headers=['تعداد','مخرج نتایج معلوم','درصد از نتایج معلوم','میانگین انتظار ثانیه','نمونه انتظار معلوم'] if fa else ['visits','known_outcomes_denominator','percent_known_outcomes','mean_wait_seconds','known_wait_samples']
        if kind=='answered':headers+=['میانگین مکالمه ثانیه','نمونه مکالمه معلوم'] if fa else ['mean_talk_seconds','known_talk_samples']
        writer.writerow(base+[dimension]+headers)
        rows=result[table]
        for row in rows:
            value=row[{'queues':'queue','days':'day','hours':'hour'}[table]]
            if table=='days' and fa:
                value=persian_date(datetime.fromisoformat(value).date())
            fields=[row[kind],row['known_outcomes'],row[kind+'_percent_of_known'],row['average_'+kind+'_wait_seconds'],row[kind+'_wait_samples']]
            if kind=='answered':fields += [row['average_answered_talk_seconds'],row['answered_talk_samples']]
            writer.writerow(common+[safe(value)]+['' if item is None else item for item in fields])
        if not rows:writer.writerow(common+[('بدون داده' if fa else 'No records')]+['']*len(headers))
    return output.getvalue().encode('utf-8-sig')
