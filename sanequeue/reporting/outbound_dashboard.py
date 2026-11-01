"""Bounded outbound CDR analysis; technical answers are not human outcomes."""
from datetime import datetime
from . import cdr_queries
from .store import QueryDeadline

MAX_SEGMENTS=50000
MAX_ORIGINS=1000
SHORT_SECONDS=10
MAX_SOURCE_BYTES=8*1024*1024


def report(archive,start,end,filters=None,*,numbers=False):
    filters=dict(filters or {})
    if filters.get('direction') not in (None,'','outbound'):
        raise ValueError('invalid_outbound_direction')
    filters['direction']='outbound'
    clause,args,clean=cdr_queries._where(archive,start,end,filters)
    with archive.reader() as db:
        cdr_queries._functions(db)
        rows=db.execute('''SELECT c.ts,CASE WHEN length(CAST(c.dst AS BLOB))<=2048 THEN c.dst END dst,
            c.duration,c.billsec,CASE WHEN length(CAST(c.disposition AS BLOB))<=2048 THEN '''+cdr_queries._DISPOSITION+
            ''' END disposition,CASE WHEN length(CAST(e.internal_caller_ext AS BLOB))<=2048 THEN e.internal_caller_ext END origin,
            CASE WHEN length(CAST(c.dst AS BLOB))>2048 OR length(CAST(c.disposition AS BLOB))>2048
              OR length(CAST(e.internal_caller_ext AS BLOB))>2048 THEN 1 ELSE 0 END oversized '''+cdr_queries._JOIN+' WHERE '+clause+
            ' LIMIT ?',(*args,MAX_SEGMENTS+1)).fetchall()
    if len(rows)>MAX_SEGMENTS:raise QueryDeadline('outbound_segment_limit')
    if any(row['oversized'] for row in rows):raise QueryDeadline('outbound_field_limit')
    if sum(sum(len(v.encode('utf8')) if isinstance(v,str) else 16 for v in row) for row in rows)>MAX_SOURCE_BYTES:
        raise QueryDeadline('outbound_source_byte_limit')
    groups={};days={};destinations=set();unknown_destination=0
    dispositions={name:0 for name in ('ANSWERED','BUSY','NO ANSWER','FAILED','CONGESTION','CANCEL','CHANUNAVAIL','OTHER')}
    def blank():return dict(segments=0,answered=0,unanswered=0,unknown=0,known_billsec=0,billsec_sum=0,
                            answered_known_billsec=0,answered_billsec_sum=0,short_answered=0,
                            known_setup=0,setup_sum=0,last_started=None)
    totals=blank()
    for row in rows:
        disposition=row['disposition'];dispositions[disposition if disposition in dispositions and disposition!='OTHER' else 'OTHER']+=1
        origin=cdr_queries._phone(row['origin'])
        if origin not in groups:
            if len(groups)>=MAX_ORIGINS:raise QueryDeadline('outbound_origin_limit')
            groups[origin]=blank()
        day=datetime.fromtimestamp(row['ts'],cdr_queries._ZONE).date().isoformat()
        day_item=days.setdefault(day,blank())
        if numbers:
            dest=cdr_queries._phone(row['dst'])
            if dest:destinations.add(dest)
            else:unknown_destination+=1
        for item in (totals,groups[origin],day_item):
            item['segments']+=1;item['last_started']=max(item['last_started'] or row['ts'],row['ts'])
            result=row['disposition'];answered=result=='ANSWERED'
            if answered:item['answered']+=1
            elif result in ('BUSY','NO ANSWER','FAILED','CONGESTION','CANCEL','CHANUNAVAIL'):item['unanswered']+=1
            else:item['unknown']+=1
            bill=row['billsec'];duration=row['duration']
            if type(bill) in (int,float) and 0<=bill<=315360000:
                item['known_billsec']+=1;item['billsec_sum']+=bill
                if answered:
                    item['answered_known_billsec']+=1;item['answered_billsec_sum']+=bill
                    if bill<SHORT_SECONDS:item['short_answered']+=1
                    if type(duration) in (int,float) and bill<=duration<=315360000:
                        item['known_setup']+=1;item['setup_sum']+=duration-bill
    def finish(item):
        denominator=item['answered']+item['unanswered']
        item['technical_answer_rate']=100*item['answered']/denominator if denominator else None
        item['known_dispositions']=denominator
        item['short_answered_rate']=100*item['short_answered']/item['answered_known_billsec'] if item['answered_known_billsec'] else None
        item['average_answered_billsec']=item['answered_billsec_sum']/item['answered_known_billsec'] if item['answered_known_billsec'] else None
        item['average_pre_answer']=item['setup_sum']/item['known_setup'] if item['known_setup'] else None
        return item
    return dict(state='available',start=float(start),end=float(end),unit='outbound_cdr_segment',scope='global_pbx',
        timezone='Asia/Tehran',filters=clean if numbers else {},totals=finish(totals),
        origins=[dict(origin=origin,**finish(group)) for origin,group in sorted(groups.items(),key=lambda pair:pair[0] or '')],
        days=[dict(day=day,**finish(group)) for day,group in sorted(days.items())],dispositions=dispositions,
        unique_destinations=len(destinations) if numbers else None,unknown_destination=unknown_destination if numbers else None,
        short_seconds=SHORT_SECONDS,complete_history=False,
        definitions=dict(technical_answer='cdr_answered_not_proof_of_human_contact',
            pre_answer='duration_minus_billsec_for_valid_answered_segments_not_necessarily_ringing',
            count='cdr_segments_not_unique_calls',short='answered_with_known_billsec_below_threshold'))
