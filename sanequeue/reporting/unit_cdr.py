"""Fail-closed organizational CDR aggregates.

This service is not an HTTP endpoint. Callers must authenticate the user and
apply any role-level permission ceiling before invoking it. Scope is always
resolved from the registry and checked again before the result leaves the
service; clients cannot supply their own scope.
"""
from sanequeue.security.unit_scope import ScopeConflict
import hashlib
import json
import csv
import io
from datetime import datetime
from zoneinfo import ZoneInfo
from . import cdr_queries, cdr_trend
from .privacy import display_number


class UnitAccessDenied(PermissionError):
    pass


# Number, endpoint, DID, and trunk filters can act as an information oracle.
# They need their own scoped authorization before they may be exposed here.
_SAFE_FILTERS=frozenset(('direction','disposition','hour_from','hour_to',
    'time_from','time_to','weekdays','duration_min','duration_max',
    'billsec_min','billsec_max'))
_IDENTIFIER_FILTERS=frozenset(('src','dst','party','origin','endpoint','match','src_length','dst_length'))
_FILTERS=_SAFE_FILTERS|_IDENTIFIER_FILTERS


def _check_filters(store,username,start,end,filters,scope,allow_full):
    if not isinstance(filters,dict) or set(filters)-_FILTERS:raise ValueError('invalid_unit_report_filter')
    if not set(filters).intersection(_IDENTIFIER_FILTERS):return
    numbers=store.resolve(username,'full_numbers',start,end)
    if numbers['revision']!=scope['revision']:raise ScopeConflict('unit_scope_changed')
    if not allow_full or not set(scope['units']).issubset(numbers['units']):
        raise UnitAccessDenied('unit_number_search_not_granted')


def summary(archive,store,username,start,end,filters=None,*,allow_full=False):
    if archive.pbx!=store.pbx:
        raise UnitAccessDenied('unit_pbx_mismatch')
    if filters is None:filters={}
    scope=store.resolve(username,'summary',start,end)
    if not scope['units']:
        raise UnitAccessDenied('unit_summary_not_granted')
    _check_filters(store,username,start,end,filters,scope,allow_full)
    result=cdr_queries.summary(archive,start,end,filters,unit_scope=scope)
    # These groups may contain identifiers or expose organizational structure
    # beyond the caller's summary permission.
    for key in ('trunks','trunk_traffic','endpoints'):
        result.pop(key,None)
    if not store.still_current(scope):
        raise ScopeConflict('unit_scope_changed')
    return result


def trend(archive,store,username,start,end,filters=None,*,bucket='day',calendar='persian',allow_full=False):
    if archive.pbx!=store.pbx:raise UnitAccessDenied('unit_pbx_mismatch')
    if filters is None:filters={}
    scope=store.resolve(username,'summary',start,end)
    if not scope['units']:raise UnitAccessDenied('unit_summary_not_granted')
    _check_filters(store,username,start,end,filters,scope,allow_full)
    result=cdr_trend.report(archive,start,end,filters,bucket=bucket,calendar=calendar,unit_scope=scope)
    if not store.still_current(scope):raise ScopeConflict('unit_scope_changed')
    return result


def details(archive,store,username,start,end,filters=None,*,cursor=None,limit=50,secret,allow_full=False,allow_audio=False):
    """Return masked CDR rows with an opaque, owner-bound pagination token.

    Recording references are opaque and require a separate, fresh authorization
    and whole-file ownership proof before any bytes can be served.
    """
    if archive.pbx!=store.pbx:raise UnitAccessDenied('unit_pbx_mismatch')
    if filters is None:filters={}
    if type(limit) is not int or not 1<=limit<=100:raise ValueError('invalid_unit_page_limit')
    scope=store.resolve(username,'call_details',start,end)
    numbers=store.resolve(username,'full_numbers',start,end)
    if not scope['units']:raise UnitAccessDenied('unit_details_not_granted')
    _check_filters(store,username,start,end,filters,scope,allow_full)
    if scope['revision']!=numbers['revision']:raise ScopeConflict('unit_scope_changed')
    audio_scopes={cap:store.resolve(username,cap,start,end) for cap in ('recording_play','recording_download')} if allow_audio else {}
    if any(item['revision']!=scope['revision'] for item in audio_scopes.values()):raise ScopeConflict('unit_scope_changed')
    query_hash=hashlib.sha256(json.dumps([start,end,filters,limit],sort_keys=True,
        separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()).hexdigest()
    before=store.load_cursor(username,scope,query_hash,cursor) if cursor else None
    result=cdr_queries.page(archive,start,end,filters,unit_scope=scope,before=before,limit=limit)
    rows=[];references=[]
    for raw in result['rows']:
        endpoint=raw['_unit_endpoint'];stamp=raw['ts']
        full=allow_full and any(item['endpoint']==endpoint and item['starts']<=stamp and
                 (item['ends'] is None or stamp<item['ends']) for item in numbers['assignments'])
        row={key:raw[key] for key in ('ts','duration','billsec','disposition','direction')}
        for key in ('src','dst'):
            row[key]=display_number(raw[key],mode='full' if full else 'masked',secret=secret,
                                    tenant='default',pbx=archive.pbx,version='1')
        def permitted(cap):
            return bool(raw['has_recording']) and any(item['endpoint']==endpoint and item['starts']<=stamp and
                (item['ends'] is None or stamp<item['ends']) for item in audio_scopes.get(cap,{}).get('assignments',()))
        play,download=permitted('recording_play'),permitted('recording_download')
        if play or download:references.append((len(rows),raw['id'],stamp,play,download))
        rows.append(row)
    if references:
        tokens=store.issue_recording_refs(username,scope,[(key,stamp) for _,key,stamp,_,_ in references])
        for (index,_,_,play,download),token in zip(references,tokens):
            rows[index]['recording']=dict(ref=token,play=play,download=download,requires_verification=True)
    next_cursor=store.save_cursor(username,scope,query_hash,result['next']) if result['next'] else None
    if not store.still_current(scope):raise ScopeConflict('unit_scope_changed')
    return dict(rows=rows,next=next_cursor,start=float(start),end=float(end),
                unit='cdr_segment',scope='organization_unit',complete_history=False,
                audio_available=bool(references))


def export_csv(archive,store,username,start,end,filters=None,*,secret,allow_full=False):
    """Export a bounded complete result or fail, never a silent partial file."""
    if archive.pbx!=store.pbx:raise UnitAccessDenied('unit_pbx_mismatch')
    filters={} if filters is None else filters
    scope=store.resolve(username,'call_details',start,end)
    grant=store.resolve(username,'export',start,end)
    numbers=store.resolve(username,'full_numbers',start,end)
    if not scope['units'] or not set(scope['units']).issubset(grant['units']):raise UnitAccessDenied('unit_export_not_granted')
    _check_filters(store,username,start,end,filters,scope,allow_full)
    if len({scope['revision'],grant['revision'],numbers['revision']})!=1:raise ScopeConflict('unit_scope_changed')
    clause,args,_=cdr_queries._where(archive,start,end,filters,unit_scope=scope,unit_capability='call_details')
    with archive.reader() as db:
        cdr_queries._functions(db)
        rows=db.execute('SELECT c.ts,c.src,c.dst,c.duration,c.billsec,'+cdr_queries._DISPOSITION+' disposition,'+
            cdr_queries._DIRECTION+' direction,p.agent endpoint '+cdr_queries._JOIN+' WHERE '+clause+
            ' ORDER BY c.ts DESC,c.source_key DESC LIMIT 5001',args).fetchall()
    if len(rows)>5000:raise ValueError('unit_export_limit')
    stream=io.StringIO(newline='');writer=csv.writer(stream)
    writer.writerow(['timestamp','source','destination','direction','status','duration_seconds','talk_seconds'])
    for row in rows:
        full=allow_full and any(item['endpoint']==row['endpoint'] and item['starts']<=row['ts'] and
                 (item['ends'] is None or row['ts']<item['ends']) for item in numbers['assignments'])
        def number(value):
            value=display_number(value,mode='full' if full else 'masked',secret=secret,tenant='default',pbx=archive.pbx,version='1')
            return "'"+value if value else ''
        def safe(value):
            value=str(value or '')
            return "'"+value if value.lstrip().startswith(('=','+','-','@','\t','\r','\n')) else value
        writer.writerow([datetime.fromtimestamp(row['ts'],ZoneInfo('Asia/Tehran')).isoformat(),number(row['src']),number(row['dst']),
                         safe(row['direction']),safe(row['disposition']),row['duration'],row['billsec']])
    if not store.still_current(scope):raise ScopeConflict('unit_scope_changed')
    return stream.getvalue().encode('utf-8-sig')


def export_xlsx(archive,store,username,start,end,filters=None,*,secret,allow_full=False):
    from .builder_exports import Workbook
    scope=store.resolve(username,'export',start,end)
    raw=export_csv(archive,store,username,start,end,filters,secret=secret,allow_full=allow_full)
    records=list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))))
    output=io.BytesIO()
    writer=Workbook(output,'fa',headers=['زمان','مبدأ','مقصد','جهت','وضعیت','مدت تماس (ثانیه)','مدت مکالمه (ثانیه)'],
                    max_bytes=8*1024*1024,max_columns=7,title='گزارش تماس واحدهای مجاز')
    try:
        for i in range(1,len(records),200):
            rows=records[i:i+200]
            for row in rows:
                for column in (1,2):
                    if row[column].startswith("'"):row[column]=row[column][1:]
            writer.append(rows)
        writer.close()
    except BaseException:
        writer.abort();raise
    if not store.still_current(scope):raise ScopeConflict('unit_scope_changed')
    return output.getvalue()


def export_pdf(archive,store,username,start,end,filters=None,*,secret,allow_full=False):
    from .pdf_stream import CustomDocument, PdfFailure
    scope=store.resolve(username,'export',start,end)
    raw=export_csv(archive,store,username,start,end,filters,secret=secret,allow_full=allow_full)
    records=list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))))[1:]
    if len(records)>150:raise PdfFailure('pdf_row_limit')
    for row in records:
        for column in (1,2):
            if row[column].startswith("'"):row[column]=row[column][1:]
    def check():
        if not store.still_current(scope):raise ScopeConflict('unit_scope_changed')
    output=io.BytesIO()
    writer=CustomDocument(output,'fa',headers=['زمان','مبدأ','مقصد','جهت','وضعیت','مدت تماس (ثانیه)','مدت مکالمه (ثانیه)'],
        unit_scoped=True,start=start,end=end,queues=[],max_rows=150,max_pages=100,max_bytes=8*1024*1024,check=check)
    try:
        writer.append(records);writer.close()
    except BaseException:
        writer.abort();raise
    check()
    return output.getvalue()
