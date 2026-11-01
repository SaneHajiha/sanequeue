"""Bounded custom global CDR reports over the local projection only.

Each row is a CDR segment, not a unique conversation. A single short SQLite
read transaction supplies both grouped and detailed results. No raw SQL from a
request is accepted; over-limit reports fail without returning a partial result.
"""
import csv
from datetime import datetime
import io
import math
from zoneinfo import ZoneInfo

from . import cdr_queries
from .exports import persian_date
from .privacy import display_number
from .store import QueryDeadline

FIELDS={'ts':'c.ts','src':'c.src','dst':'c.dst','origin':'e.internal_caller_ext',
        'outbound_cid':'e.outbound_cid','did':'e.did','trunk':'e.trunk',
        'direction':cdr_queries._DIRECTION,'disposition':cdr_queries._DISPOSITION,
        'duration':'c.duration','billsec':'c.billsec'}
NUMBERS={'src','dst','origin','outbound_cid','did'}
GROUPS={'trunk','direction','disposition'}
METRICS=('segments','answered','unanswered','unknown_disposition','known_duration',
         'average_duration_seconds','known_billsec','average_billsec_seconds')
MAX_SEGMENTS=50000
MAX_GROUPS=500
MAX_CSV_ROWS=5000
MAX_CSV_BYTES=4*1024*1024
MAX_SOURCE_BYTES=8*1024*1024
_ZONE=ZoneInfo('Asia/Tehran')


def definition(value):
    if not isinstance(value,dict) or set(value)!={'columns','group_by'}:raise ValueError('invalid_cdr_builder_definition')
    columns=value['columns'];groups=value['group_by']
    if not isinstance(columns,list) or not 1<=len(columns)<=len(FIELDS) or len(set(columns))!=len(columns) or any(c not in FIELDS for c in columns):
        raise ValueError('invalid_cdr_builder_columns')
    if not isinstance(groups,list) or len(groups)>2 or len(set(groups))!=len(groups) or any(g not in GROUPS for g in groups):
        raise ValueError('invalid_cdr_builder_groups')
    return dict(columns=list(columns),group_by=list(groups))


def report(archive,start,end,filters,spec,*,numbers,secret):
    spec=definition(spec);clause,args,clean=cdr_queries._where(archive,start,end,filters)
    selected=list(dict.fromkeys(spec['group_by']+['disposition','duration','billsec'] if spec['group_by'] else spec['columns']))
    text_fields=[key for key in selected if key not in ('ts','duration','billsec')]
    expressions=','.join(('CASE WHEN length(CAST('+FIELDS[key]+' AS BLOB))<=2048 THEN '+FIELDS[key]+' END' if key in text_fields else FIELDS[key])+' AS "'+key+'"' for key in selected)
    oversized=('CASE WHEN '+' OR '.join('length(CAST('+FIELDS[key]+' AS BLOB))>2048' for key in text_fields)+' THEN 1 ELSE 0 END') if text_fields else '0'
    with archive.reader() as db:
        cdr_queries._functions(db)
        cursor=db.execute('SELECT '+expressions+','+oversized+' AS _oversized '+cdr_queries._JOIN+' WHERE '+clause+
            ' ORDER BY c.ts DESC,c.source_key DESC LIMIT ?',(*args,MAX_SEGMENTS+1))
        rows=[];source_bytes=0
        while True:
            batch=cursor.fetchmany(200)
            if not batch:break
            for raw in batch:
                row=dict(raw)
                if row.pop('_oversized'):raise ValueError('cdr_builder_field_limit')
                source_bytes+=sum(len(value.encode('utf-8')) if isinstance(value,str) else 16 for value in row.values())
                if source_bytes>MAX_SOURCE_BYTES:raise QueryDeadline('cdr_builder_source_byte_limit')
                rows.append(row)
    if len(rows)>MAX_SEGMENTS:raise QueryDeadline('cdr_builder_segment_limit')
    for row in rows:
        for key,value in row.items():
            if isinstance(value,str) and len(value)>512:raise ValueError('cdr_builder_field_limit')
            if isinstance(value,(int,float)) and (not math.isfinite(value) or abs(value)>1e12):raise ValueError('cdr_builder_field_limit')
            if key in NUMBERS and value is not None:
                row[key]=display_number(value,'full' if numbers else 'masked',secret=secret,tenant='default',pbx=archive.pbx,version='1')
    if spec['group_by']:
        groups={}
        for row in rows:
            key=tuple(row[field] for field in spec['group_by'])
            if key not in groups:
                if len(groups)>=MAX_GROUPS:raise QueryDeadline('cdr_builder_group_limit')
                groups[key]=dict(segments=0,answered=0,unanswered=0,unknown_disposition=0,known_duration=0,duration_sum=0,known_billsec=0,billsec_sum=0)
            item=groups[key];item['segments']+=1;disposition=row['disposition']
            if disposition=='ANSWERED':item['answered']+=1
            elif disposition in ('BUSY','NO ANSWER','FAILED','CONGESTION','CANCEL','CHANUNAVAIL'):item['unanswered']+=1
            else:item['unknown_disposition']+=1
            for name in ('duration','billsec'):
                value=row[name]
                if value is not None:
                    if type(value) not in (int,float) or value<0:raise ValueError('cdr_builder_field_limit')
                    item['known_'+name]+=1;item[name+'_sum']+=value
        result=[]
        for key in sorted(groups,key=lambda parts:tuple((v is not None,str(v or '')) for v in parts)):
            item=groups[key];row=dict(zip(spec['group_by'],key))
            row.update({name:item[name] for name in ('segments','answered','unanswered','unknown_disposition','known_duration','known_billsec')})
            row['average_duration_seconds']=item['duration_sum']/item['known_duration'] if item['known_duration'] else None
            row['average_billsec_seconds']=item['billsec_sum']/item['known_billsec'] if item['known_billsec'] else None
            result.append(row)
        columns=spec['group_by']+list(METRICS)
    else:columns=spec['columns'];result=[{key:row[key] for key in columns} for row in rows]
    return dict(columns=columns,rows=result,source_segments=len(rows),unit='cdr_segment',scope='global_pbx',
        complete_history=False,grouped=bool(spec['group_by']),start=float(start),end=float(end),timezone='Asia/Tehran',
        number_policy='full' if numbers else 'masked',maximum_segments=MAX_SEGMENTS,filters=clean if numbers else {})


def csv_bytes(data,language):
    if language not in ('fa','en'):raise ValueError('invalid_cdr_builder_language')
    if len(data['rows'])>MAX_CSV_ROWS:raise ValueError('cdr_builder_csv_row_limit')
    labels=dict(ts='شروع (تهران)',src='مبدأ نمایشی',dst='مقصد',origin='داخلی واقعی',outbound_cid='CID خروجی',did='سرشماره',
        trunk='ترانک',direction='جهت',disposition='نتیجه',duration='مدت (ثانیه)',billsec='مکالمه (ثانیه)',
        segments='بخش CDR',answered='پاسخ داده',unanswered='بدون پاسخ',unknown_disposition='نتیجه نامعلوم',
        known_duration='نمونه مدت معلوم',average_duration_seconds='میانگین مدت معلوم',known_billsec='نمونه مکالمه معلوم',average_billsec_seconds='میانگین مکالمه معلوم')
    output=io.StringIO(newline='');writer=csv.writer(output);columns=data['columns']
    writer.writerow([labels[key] if language=='fa' else key for key in columns])
    for row in data['rows']:
        cells=[]
        for key in columns:
            value=row.get(key)
            if key=='ts' and value is not None:
                local=datetime.fromtimestamp(value,_ZONE);value=(persian_date(local.date()) if language=='fa' else local.date().isoformat())+local.strftime(' %H:%M:%S')
            if isinstance(value,str) and (key in NUMBERS or value.lstrip().startswith(('=','+','-','@','\t','\r','\n'))):value="'"+value
            cells.append('' if value is None else value)
        writer.writerow(cells)
        if output.tell()>MAX_CSV_BYTES:raise ValueError('cdr_builder_csv_byte_limit')
    result=output.getvalue().encode('utf-8-sig')
    if len(result)>MAX_CSV_BYTES:raise ValueError('cdr_builder_csv_byte_limit')
    return result
