"""Global PBX CDR-segment reports, not queue-scoped conversation reports.

The HTTP adapter must require explicit global administrator/report permission,
authorize number searches, mask every number, and separately authorize audio.
These functions intentionally accept no queue Scope and never call the PBX.
All full-range aggregates share one bounded SQLite read transaction.
"""
from collections import Counter
import csv
from datetime import datetime
import io
import math
import re
import unicodedata
from zoneinfo import ZoneInfo

from .store import QueryDeadline

MAX_GROUPS=1000
MAX_UNIQUE_INBOUND_SEGMENTS=50000
_ZONE=ZoneInfo('Asia/Tehran')
_NUMBER_FIELDS={'src':'c.src','dst':'c.dst','origin':'e.internal_caller_ext',
                'outbound_cid':'e.outbound_cid','did':'e.did'}
_KEYS=set(_NUMBER_FIELDS)|{'party','match','src_length','dst_length','direction','disposition','trunk',
    'hour_from','hour_to','time_from','time_to','weekdays','duration_min','duration_max','billsec_min','billsec_max'}
_DIRECTION="COALESCE(p.direction,'unknown')"
_DISPOSITION="CASE WHEN TRIM(COALESCE(c.disposition,''))='' THEN 'UNKNOWN' ELSE UPPER(TRIM(c.disposition)) END"
_JOIN='''FROM report_cdr c LEFT JOIN report_cdr_parties p ON p.pbx=c.pbx AND p.source_key=c.source_key
 LEFT JOIN report_cdr_extra e ON e.pbx=c.pbx AND e.event_id=c.event_id'''
_METRICS='''COUNT(*) segments_started,
 COALESCE(SUM(disposition='ANSWERED'),0) answered_segments,
 COALESCE(SUM(disposition IN ('BUSY','NO ANSWER','FAILED','CONGESTION','CANCEL','CHANUNAVAIL')),0) unanswered_segments,
 COALESCE(SUM(disposition NOT IN ('ANSWERED','BUSY','NO ANSWER','FAILED','CONGESTION','CANCEL','CHANUNAVAIL')),0) unknown_disposition_segments,
 COUNT(duration) known_duration_count,COUNT(*)-COUNT(duration) unknown_duration_count,
 SUM(duration) known_duration_sum,AVG(duration) average_duration_seconds,
 COUNT(billsec) known_billsec_count,COUNT(*)-COUNT(billsec) unknown_billsec_count,
 SUM(billsec) known_billsec_sum,AVG(billsec) average_billsec_seconds,
 AVG(CASE WHEN disposition='ANSWERED' THEN billsec END) average_answered_billsec,
 COALESCE(SUM(internal_caller_ext IS NULL),0) unknown_origin_segments,
 COALESCE(SUM(outbound_cid IS NULL),0) unknown_outbound_cid_segments,
 COALESCE(SUM(did IS NULL),0) unknown_did_segments,COALESCE(SUM(trunk IS NULL),0) unknown_trunk_segments'''


def _phone(value):
    if value is None:return None
    value=str(value)
    if len(value)>256:return None
    value=value.strip()
    value=''.join(str(unicodedata.digit(char)) if char.isdecimal() else char for char in value)
    if value.startswith('+'):value=value[1:]
    return value if re.fullmatch('[0-9]{1,24}',value) else None


def _integer(value,minimum,maximum):
    if isinstance(value,bool) or not re.fullmatch('[0-9]{1,10}',str(value)):raise ValueError('invalid_cdr_integer_filter')
    value=int(value)
    if not minimum<=value<=maximum:raise ValueError('invalid_cdr_integer_filter')
    return value


def _seconds(value):
    if isinstance(value,bool):raise ValueError('invalid_cdr_duration_filter')
    value=float(value)
    if not math.isfinite(value) or not 0<=value<=315360000:raise ValueError('invalid_cdr_duration_filter')
    return value


def _where(archive,start,end,filters):
    start,end=float(start),float(end)
    if not all(math.isfinite(value) for value in (start,end)) or start<0 or end<=start or end-start>366*86400:
        raise ValueError('invalid_cdr_range')
    if filters is None:filters={}
    if not isinstance(filters,dict) or set(filters)-_KEYS:raise ValueError('invalid_cdr_filters')
    clean={key:value for key,value in filters.items() if value is not None and value!='' and value!=[]}
    mode=clean.get('match','exact')
    if mode not in ('exact','partial'):raise ValueError('invalid_cdr_match')
    clean['match']=mode
    clause='c.pbx=? AND c.ts>=? AND c.ts<?';args=[archive.pbx,start,end]
    for key in (*_NUMBER_FIELDS,'party'):
        if key not in clean:continue
        number=_phone(clean[key])
        if number is None or mode=='partial' and len(number)<3:raise ValueError('invalid_cdr_number_filter')
        clean[key]=number
        columns=[_NUMBER_FIELDS[key]] if key!='party' else ['c.src','c.dst','e.internal_caller_ext','e.outbound_cid']
        operator=' LIKE ?' if mode=='partial' else '=?'
        clause+=' AND ('+' OR '.join('cdr_phone('+column+')'+operator for column in columns)+')'
        args.extend([('%'+number+'%') if mode=='partial' else number]*len(columns))
    for key,column in (('src_length','c.src'),('dst_length','c.dst')):
        if key in clean:
            clean[key]=_integer(clean[key],1,24)
            clause+=' AND LENGTH(cdr_phone('+column+'))=?';args.append(clean[key])
    if 'direction' in clean:
        if clean['direction'] not in ('inbound','outbound','internal','unknown'):raise ValueError('invalid_cdr_direction')
        clause+=' AND '+_DIRECTION+'=?';args.append(clean['direction'])
    if 'disposition' in clean:
        if not isinstance(clean['disposition'],str) or not re.fullmatch('[A-Za-z _-]{1,32}',clean['disposition']):
            raise ValueError('invalid_cdr_disposition')
        clean['disposition']=clean['disposition'].strip().upper()
        if not clean['disposition']:raise ValueError('invalid_cdr_disposition')
        clause+=' AND ('+_DISPOSITION+')=?';args.append(clean['disposition'])
    if 'trunk' in clean:
        trunk=clean['trunk']
        if not isinstance(trunk,str) or not 1<=len(trunk)<=256 or not trunk.isprintable():raise ValueError('invalid_cdr_trunk')
        clause+=' AND e.trunk=?';args.append(trunk)
    if 'hour_from' in clean or 'hour_to' in clean:
        begin=_integer(clean.get('hour_from',0),0,23);finish=_integer(clean.get('hour_to',23),0,23)
        clean.update(hour_from=begin,hour_to=finish)
        clause+=' AND (cdr_hour(c.ts)>=? '+('AND' if begin<=finish else 'OR')+' cdr_hour(c.ts)<=?)'
        args.extend((begin,finish))
    if 'time_from' in clean or 'time_to' in clean:
        def seconds(key, default):
            value=clean.get(key,default)
            if not isinstance(value,str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?',value):
                raise ValueError('invalid_cdr_time_filter')
            parts=[int(x) for x in value.split(':')]
            return parts[0]*3600+parts[1]*60+(parts[2] if len(parts)==3 else (59 if key=='time_to' else 0))
        begin,finish=seconds('time_from','00:00:00'),seconds('time_to','23:59:59')
        clause+=' AND (cdr_second(c.ts)>=? '+('AND' if begin<=finish else 'OR')+' cdr_second(c.ts)<=?)'
        args.extend((begin,finish))
    if 'weekdays' in clean:
        days=clean['weekdays']
        if isinstance(days,str):days=days.split(',')
        if not isinstance(days,(list,tuple,set)) or not 1<=len(days)<=7:raise ValueError('invalid_cdr_weekdays')
        days=sorted({_integer(day,0,6) for day in days});clean['weekdays']=days
        clause+=' AND cdr_weekday(c.ts) IN ('+','.join('?' for _ in days)+')';args.extend(days)
    for field in ('duration','billsec'):
        minimum=clean.get(field+'_min');maximum=clean.get(field+'_max')
        if minimum is not None:
            minimum=_seconds(minimum);clean[field+'_min']=minimum
            clause+=' AND c.'+field+'>=?';args.append(minimum)
        if maximum is not None:
            maximum=_seconds(maximum);clean[field+'_max']=maximum
            clause+=' AND c.'+field+'<=?';args.append(maximum)
        if minimum is not None and maximum is not None and minimum>maximum:raise ValueError('invalid_cdr_duration_range')
    return clause,args,clean


def _functions(db):
    db.create_function('cdr_phone',1,_phone,deterministic=True)
    db.create_function('cdr_hour',1,lambda stamp:datetime.fromtimestamp(stamp,_ZONE).hour,deterministic=True)
    db.create_function('cdr_second',1,lambda stamp:(lambda d:d.hour*3600+d.minute*60+d.second)(datetime.fromtimestamp(stamp,_ZONE)),deterministic=True)
    db.create_function('cdr_weekday',1,lambda stamp:(datetime.fromtimestamp(stamp,_ZONE).weekday()+2)%7,deterministic=True)


def page(archive,start,end,filters=None,*,before=None,limit=100):
    clause,args,clean=_where(archive,start,end,filters)
    if isinstance(limit,bool):raise ValueError('invalid_cdr_page_limit')
    limit=_integer(limit,1,1000000);limit=min(100,limit)
    if before is not None:
        if not isinstance(before,(tuple,list)) or len(before)!=2 or not math.isfinite(float(before[0])) or not isinstance(before[1],str) or not 1<=len(before[1])<=512:
            raise ValueError('invalid_cdr_cursor')
        clause+=' AND (c.ts<? OR (c.ts=? AND c.source_key<?))';args.extend((float(before[0]),float(before[0]),before[1]))
    with archive.reader() as db:
        _functions(db)
        rows=[dict(row) for row in db.execute('''SELECT c.source_key id,c.ts,c.src,c.dst,c.duration,c.billsec,
          '''+_DISPOSITION+''' disposition,'''+_DIRECTION+''' direction,e.internal_caller_ext,e.outbound_cid,
          e.outbound_cid_source,e.did,e.trunk,e.trunk_provenance,e.inventory_observed,
          CASE WHEN c.recording<>'' THEN 1 ELSE 0 END has_recording '''+_JOIN+' WHERE '+clause+
          ' ORDER BY c.ts DESC,c.source_key DESC LIMIT ?',(*args,limit+1))]
    more=len(rows)>limit;rows=rows[:limit]
    return dict(rows=rows,next=[rows[-1]['ts'],rows[-1]['id']] if more and rows else None,
                start=float(start),end=float(end),filters=clean,unit='cdr_segment',scope='global_pbx',
                queue_scoped=False,audio_granted=False,complete_history=False)


def summary(archive,start,end,filters=None):
    clause,args,clean=_where(archive,start,end,filters)
    cte='''WITH matched AS (SELECT c.duration,c.billsec,'''+_DISPOSITION+' disposition,'+_DIRECTION+''' direction,
      e.internal_caller_ext,e.outbound_cid,e.did,e.trunk,NULLIF(p.agent,'') endpoint '''+_JOIN+' WHERE '+clause+') '
    with archive.reader() as db:
        _functions(db)
        totals=dict(db.execute(cte+'SELECT '+_METRICS+' FROM matched',args).fetchone())
        groups={};count=0
        for name,field in (('directions','direction'),('dispositions','disposition'),('trunks','trunk'),
                           ('trunk_traffic','trunk,did,direction'),('endpoints','endpoint')):
            rows=[dict(row) for row in db.execute(cte+'SELECT '+field+','+_METRICS+
                  ' FROM matched GROUP BY '+field+' ORDER BY '+field+' LIMIT ?',(*args,MAX_GROUPS+1))]
            count+=len(rows)
            if count>MAX_GROUPS:raise QueryDeadline('cdr_group_limit_narrow_filters')
            groups[name]=rows
    return dict(start=float(start),end=float(end),filters=clean,unit='cdr_segment',scope='global_pbx',
                queue_scoped=False,complete_history=False,totals=totals,**groups,
                definitions=dict(count='latest_cdr_segments_not_unique_conversations',
                  origin='known_origin_extension_not_src',outbound_cid='explicit_cdr_source_field_only',
                  unknown='null_metrics_and_known_sample_counts',timezone='Asia/Tehran',week_starts='Saturday'))


def unique_inbound(archive,start,end,filters=None):
    """Count observed inbound source numbers, never unique calls or people."""
    selected=dict(filters or {})
    if selected.get('direction') not in (None,'','inbound'):raise ValueError('invalid_unique_inbound_direction')
    selected['direction']='inbound'
    clause,args,clean=_where(archive,start,end,selected)
    with archive.reader() as db:
        _functions(db)
        rows=db.execute('SELECT c.ts,c.src '+_JOIN+' WHERE '+clause+' LIMIT ?',
                        (*args,MAX_UNIQUE_INBOUND_SEGMENTS+1)).fetchall()
    if len(rows)>MAX_UNIQUE_INBOUND_SEGMENTS:
        return dict(state='limited',reason='unique_inbound_segment_limit',maximum_segments=MAX_UNIQUE_INBOUND_SEGMENTS)
    numbers=Counter();days={};unknown=0
    for row in rows:
        number=_phone(row['src'])
        if number is None:unknown+=1;continue
        day=datetime.fromtimestamp(row['ts'],_ZONE).date().isoformat()
        numbers[number]+=1;item=days.setdefault(day,dict(numbers=Counter(),segments=0));item['numbers'][number]+=1;item['segments']+=1
    repeated=sum(count>1 for count in numbers.values())
    return dict(state='available',start=float(start),end=float(end),timezone='Asia/Tehran',
        total_unique=len(numbers),repeat_numbers=repeated,
        repeat_number_percent=(round(100*repeated/len(numbers),2) if numbers else None),
        known_number_segments=sum(item['segments'] for item in days.values()),unknown_number_segments=unknown,
        by_day=[dict(day=day,unique_numbers=len(item['numbers']),
                     repeat_numbers=sum(count>1 for count in item['numbers'].values()),
                     known_number_segments=item['segments']) for day,item in sorted(days.items())],
        contract=dict(unit='distinct_normalized_inbound_cdr_source_number',source='observed_inbound_cdr_segments',
            source_is_displayed_caller_id=True,unique_conversations_proven=False,customer_identity_proven=False,
            repeat='more_than_one_cdr_segment_with_same_source_not_proven_repeat_calls',
            repeat_percent_denominator='known_distinct_inbound_source_numbers',
            unknown_direction_excluded=True,daily_totals_additive=False,country_prefix_equivalence=False,
            maximum_segments=MAX_UNIQUE_INBOUND_SEGMENTS,complete_history=False))


def unique_inbound_csv(result,language):
    """Export bounded aggregates only; source phone numbers never leave memory."""
    if language not in ('fa','en') or result.get('state')!='available':
        raise ValueError('invalid_unique_inbound_export')
    from .exports import persian_date
    fa=language=='fa'
    def date(value):
        return persian_date(value) if fa else value.isoformat()
    start=datetime.fromtimestamp(result['start'],_ZONE)
    end=datetime.fromtimestamp(result['end'],_ZONE)
    stamp=lambda value:date(value.date())+value.strftime(' %H:%M:%S')
    output=io.StringIO(newline='');writer=csv.writer(output)
    writer.writerow((['شروع بازه','پایان انحصاری بازه','روز','شماره‌های یکتای روز','شماره‌های چندبخشی روز',
                      'بخش‌های دارای شماره معلوم روز','شماره‌های یکتای بازه','شماره‌های چندبخشی بازه',
                      'درصد شماره‌های چندبخشی بازه','بخش‌های دارای شماره نامعلوم بازه','تعریف'] if fa else
                     ['period_start','period_end_exclusive','day','daily_distinct_numbers','daily_multi_segment_numbers',
                      'daily_known_number_segments','period_distinct_numbers','period_multi_segment_numbers',
                      'period_multi_segment_percent','period_unknown_number_segments','definition']))
    definition=('چند بخش CDR با مبدأ یکسان؛ تکرار تماس یا هویت مشتری اثبات نمی‌شود' if fa else
                'multiple CDR segments with the same source; repeated calls and identity are not proven')
    for row in result['by_day'] or [None]:
        day=date(datetime.fromisoformat(row['day']).date()) if row else ''
        writer.writerow([stamp(start),stamp(end),day,row['unique_numbers'] if row else '',
                         row['repeat_numbers'] if row else '',row['known_number_segments'] if row else '',
                         result['total_unique'],result['repeat_numbers'],
                         result['repeat_number_percent'] if result['repeat_number_percent'] is not None else '',
                         result['unknown_number_segments'],definition])
    return output.getvalue().encode('utf-8-sig')


def unique_inbound_document(result,language,format):
    """Render the same aggregate as a bounded workbook or PDF."""
    if format not in ('xlsx','pdf'):raise ValueError('invalid_unique_inbound_export')
    from . import builder_exports,pdf_stream
    rows=list(csv.reader(io.StringIO(unique_inbound_csv(result,language).decode('utf-8-sig'))))
    headers,body=rows[0],rows[1:]
    if format=='pdf' and len(body)>100:raise pdf_stream.PdfFailure('pdf_row_limit')
    output=io.BytesIO()
    if format=='xlsx':
        for row in body:
            for index in range(3,10):
                if row[index]:row[index]=float(row[index])
        writer=builder_exports.Workbook(output,language,headers=headers,max_bytes=4*1024*1024,max_columns=20,
            title='شماره‌های یکتای ورودی' if language=='fa' else 'Distinct inbound numbers')
    else:
        writer=pdf_stream.CustomDocument(output,language,headers=headers,max_columns=20,grouped=True,global_cdr=True,
            start=result['start'],end=result['end'],queues=[],max_rows=100,max_pages=20,max_bytes=4*1024*1024,
            filter_items=['چند بخش CDR اثبات تماس تکراری نیست' if language=='fa' else 'Multiple CDR segments do not prove repeated calls'])
    try:
        for index in range(0,len(body),200):writer.append(body[index:index+200])
        writer.close()
    except BaseException:
        writer.abort();raise
    return output.getvalue()
