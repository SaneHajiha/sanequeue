"""Bounded aggregates of observed queue caller numbers, never identities."""
from datetime import datetime
from .analytics import ZONE
from .customer_segments import number
from .queries import _where

MAX_VISITS = 50000


def report(archive, scope, start, end):
    clause,args = _where(archive.pbx,scope,start,end)
    with archive.reader() as db:
        # Ordering is unnecessary for aggregates and can force an expensive
        # cross-queue sort. Over-limit results never expose a partial sample.
        rows=db.execute('SELECT queue,entered,caller,coverage FROM report_visits WHERE '+clause+
                        ' LIMIT ?',(*args,MAX_VISITS+1)).fetchall()
        projection=db.execute('SELECT after_id,updated FROM report_projection WHERE pbx=?',(archive.pbx,)).fetchone()
    if len(rows)>MAX_VISITS:
        return dict(state='limited',reason='unique_caller_visit_limit',maximum_visits=MAX_VISITS)
    all_numbers=set();days={};queues={};unknown=0;missing_entry=0
    for row in rows:
        if row['coverage']=='missing_entry':
            missing_entry+=1
            continue
        try:caller=number(row['caller'])
        except (TypeError,ValueError):
            unknown+=1
            continue
        day=datetime.fromtimestamp(row['entered'],ZONE).date().isoformat()
        all_numbers.add(caller)
        item=days.setdefault(day,dict(numbers=set(),visits=0));item['numbers'].add(caller);item['visits']+=1
        item=queues.setdefault(row['queue'],dict(numbers=set(),visits=0));item['numbers'].add(caller);item['visits']+=1
    return dict(state='available',start=float(start),end=float(end),timezone='Asia/Tehran',
                total_unique=len(all_numbers),known_number_visits=sum(item['visits'] for item in days.values()),
                unknown_number_visits=unknown,missing_entry_visits=missing_entry,
                by_day=[dict(day=day,unique_numbers=len(item['numbers']),known_number_visits=item['visits'])
                        for day,item in sorted(days.items())],
                by_queue=[dict(queue=queue,unique_numbers=len(item['numbers']),known_number_visits=item['visits'])
                          for queue,item in sorted(queues.items())],
                projection=dict(projection) if projection else None,
                contract=dict(unit='distinct_normalized_caller_number',source='observed_queue_visits',
                              customer_identity_proven=False,includes_non_queue_inbound=False,
                              daily_or_queue_totals_additive=False,unknowns_in_unique_count=False,
                              country_prefix_equivalence=False,maximum_visits=MAX_VISITS))
