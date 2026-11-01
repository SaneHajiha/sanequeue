"""Bounded outbound CDR analysis; technical answers are not human outcomes."""
from datetime import datetime
import csv
import io
from . import cdr_queries
from .exports import persian_date
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


def csv_bytes(data,table,language):
    """Export one current, permission-filtered aggregate; no raw CDR rows."""
    if table not in ('origins','days','dispositions') or language not in ('fa','en'):
        raise ValueError('invalid_outbound_export')
    fa=language=='fa'
    def date(value):
        if value is None:return ''
        local=datetime.fromtimestamp(value,cdr_queries._ZONE)
        return (persian_date(local.date()) if fa else local.date().isoformat())+local.strftime(' %H:%M:%S')
    start,end=date(data['start']),date(data['end'])
    fields=('segments','answered','unanswered','unknown','known_dispositions','technical_answer_rate',
            'answered_known_billsec','average_answered_billsec','short_answered','short_answered_rate',
            'known_setup','average_pre_answer')
    labels=('بخش خروجی','پاسخ فنی','بدون پاسخ فنی','نتیجه نامعلوم','مخرج نرخ پاسخ','نرخ پاسخ فنی درصد',
            'نمونه مکالمه معلوم','میانگین مکالمه ثانیه','پاسخ کوتاه زیر ۱۰ ثانیه','نرخ پاسخ کوتاه درصد',
            'نمونه پیش از پاسخ','میانگین پیش از پاسخ ثانیه')
    header=['شروع تهران','پایان انحصاری تهران'] if fa else ['period_start_tehran','period_end_exclusive_tehran']
    output=io.StringIO(newline='');writer=csv.writer(output)
    if table=='dispositions':
        writer.writerow(header+(['وضعیت فنی','تعداد بخش'] if fa else ['technical_status','segments']))
        for status,count in data['dispositions'].items():writer.writerow([start,end,status,count])
    else:
        group=('داخلی ثبت‌شده' if table=='origins' else 'روز تهران') if fa else ('origin' if table=='origins' else 'day_tehran')
        tail=(['آخرین شروع تهران','سهم از بخش‌های خروجی درصد'] if fa else ['last_start_tehran','share_of_segments_percent']) if table=='origins' else []
        writer.writerow(header+[group]+(list(labels) if fa else list(fields))+tail)
        for row in data[table]:
            group_value=row['origin'] if table=='origins' else row['day']
            if group_value is None:group_value=''
            elif table=='origins':group_value="'"+group_value
            elif fa:group_value=persian_date(datetime.fromisoformat(group_value).date())
            cells=[start,end,group_value]+['' if row[key] is None else row[key] for key in fields]
            if table=='origins':cells.extend([date(row['last_started']),100*row['segments']/data['totals']['segments'] if data['totals']['segments'] else ''])
            writer.writerow(cells)
    content=output.getvalue().encode('utf-8-sig')
    if len(content)>4*1024*1024:raise QueryDeadline('outbound_export_byte_limit')
    return content


def document_bytes(data,table,language,format):
    """Bounded exports of the same aggregate; never publish a partial file."""
    if format not in ('xlsx','pdf'):raise ValueError('invalid_outbound_export_format')
    from . import builder_exports,pdf_stream
    rows=list(csv.reader(io.StringIO(csv_bytes(data,table,language).decode('utf-8-sig'))))
    headers,body=rows[0],rows[1:]
    if format=='pdf' and len(body)>100:raise pdf_stream.PdfFailure('pdf_row_limit')
    # XLSX stores inline text, so no Excel formula escaping is necessary.
    if table=='origins':
        for row in body:
            if row[2].startswith("'"):row[2]=row[2][1:]
    for row in body:
        # Preserve dates and extension identifiers as text; aggregate metrics
        # are numeric and should remain usable for spreadsheet calculations.
        numeric=range(3,len(row)) if table!='dispositions' else (3,)
        for index in numeric:
            if table=='origins' and index==15:continue
            if not row[index]:continue
            try:row[index]=float(row[index])
            except ValueError:raise ValueError('invalid_outbound_export_value') from None
    target=io.BytesIO();writer=None
    if format=='xlsx':
        def label_date(stamp):
            local=datetime.fromtimestamp(stamp,cdr_queries._ZONE)
            return (persian_date(local.date()) if language=='fa' else local.date().isoformat())+local.strftime(' %H:%M:%S')
        period=label_date(data['start'])+' → '+label_date(data['end'])+' | '+('پایان شامل نیست؛ پاسخ فنی' if language=='fa' else 'end exclusive; technical answers')
        writer=builder_exports.Workbook(target,language,headers=headers,max_bytes=4*1024*1024,max_columns=20,
            title='گزارش تماس خروجی' if language=='fa' else 'Outbound CDR report',
            period=period)
    else:
        class OutboundDocument(pdf_stream.CustomDocument):
            def close(self):
                if self.closed:return
                self.check()
                if not self.rows:self._draw('داده‌ای در این بازه ثبت نشده است.' if self.fa else 'No recorded data in this period.',
                    self.width-self.margin if self.fa else self.margin,self.y-30,10,right=self.fa)
                self._footer();self.pdf.save();self.closed=True;self.visual.cache_clear()
        writer=OutboundDocument(target,language,headers=headers,max_columns=20,grouped=True,global_cdr=True,
            start=data['start'],end=data['end'],queues=[],max_rows=100,max_pages=20,max_bytes=4*1024*1024,
            filter_items=['پاسخ فنی اثبات تماس با انسان نیست' if language=='fa' else 'Technical answer does not prove human contact'])
        body=[[f'{value:.2f}'.rstrip('0').rstrip('.') if isinstance(value,float) else value for value in row] for row in body]
    try:
        for index in range(0,len(body),200):writer.append(body[index:index+200])
        writer.close()
    except BaseException:
        writer.abort();raise
    return target.getvalue()
