"""Exact whitelisted builder exports over immutable queue-visit versions.

No HTTP, PBX SQL, dynamic SQL identifiers, caller-supplied expressions or CDR
dataset. Each page releases its read transaction before formatting or writing.
"""
from datetime import datetime
import io
import math
import re
from zipfile import ZipFile,ZIP_DEFLATED
from zoneinfo import ZoneInfo

from .report_builder import definition,COLUMNS,_bounded,_oversized
from .queries import Scope,_where
from .exports import persian_date,xlsx_bytes
from .privacy import display_number
from . import visit_snapshots,xlsx_stream

METRICS=('visits','answered_known','abandoned','wait_known','average_wait_seconds','talk_known','average_queue_talk_seconds','queue_talk_seconds')
MAX_GROUPS=500


class BuilderFailure(ValueError):pass


def capture(archive):
    """Capture fact versions and their projection watermark in one snapshot."""
    with archive.reader() as db:
        state=db.execute('SELECT generation,ready FROM report_snapshot_meta WHERE pbx=?',(archive.pbx,)).fetchone()
        watermark=db.execute('SELECT after_id FROM report_projection WHERE pbx=?',(archive.pbx,)).fetchone()
        if state is None or not state['ready'] or watermark is None:raise visit_snapshots.SnapshotUnavailable('report_snapshot_initializing')
        sequence=db.execute('SELECT MAX(seq) FROM report_visit_versions').fetchone()[0] or 0
        return dict(snapshot=dict(generation=state['generation'],sequence=sequence),watermark=int(watermark['after_id']))


def validate(spec):
    value=definition(spec['builder_definition'])
    if value!=spec['builder_definition']:raise BuilderFailure('builder_definition_not_canonical')
    if set(value['queues'])!=set(spec['scope']['queues']):raise BuilderFailure('builder_scope_mismatch')
    if spec.get('snapshot') is None:raise BuilderFailure('builder_snapshot_required')
    if spec['format'] not in ('csv','xlsx') or spec.get('outcome') is not None:raise BuilderFailure('builder_export_format_or_filter')
    if spec['end']-spec['start']>31*86400:raise BuilderFailure('builder_range_limit')
    return value


def columns(value):return list(value['group_by'])+list(METRICS) if value['group_by'] else list(value['columns'])


def headers(value,language):
    names=dict(zip(COLUMNS,['صف','شماره تماس‌گیرنده','کارشناس','نتیجه','ورود (تهران)','پاسخ (تهران)','پایان بخش صف (تهران)','انتظار (ثانیه)','مکالمه صف (ثانیه)','قطع‌کننده بخش صف','پوشش شواهد','شناسه مراجعه']))
    names.update(visits='تعداد مراجعه',answered_known='پاسخ دارای زمان معتبر',abandoned='رهاشده',wait_known='تعداد انتظار معلوم',talk_known='تعداد مکالمه معلوم',average_wait_seconds='میانگین انتظار معلوم (ثانیه)',average_queue_talk_seconds='میانگین مکالمه صف معلوم (ثانیه)',queue_talk_seconds='مجموع مکالمه صف معلوم (ثانیه)')
    return [names[key] if language=='fa' else key for key in columns(value)]


def page(archive,spec,before,*,limit=200):
    value=validate(spec)
    if type(limit) is not int or not 1<=limit<=200:raise BuilderFailure('builder_page_limit')
    scope=Scope(tuple(value['queues']),tuple(spec['scope']['agents']),spec['scope']['self_only'],spec['scope']['not_before'])
    clause,args=_where(archive.pbx,scope,spec['start'],spec['end'])
    filters=value['filters'];outcomes=filters.get('outcomes',[])
    if outcomes:clause+=' AND outcome IN ('+','.join('?' for _ in outcomes)+')';args+=outcomes
    for key,column,operator in [('wait_min','wait_seconds','>='),('wait_max','wait_seconds','<='),('talk_min','talk_seconds','>='),('talk_max','talk_seconds','<=')]:
        if key in filters:clause+=' AND '+column+operator+'?';args.append(filters[key])
    if before:
        if not isinstance(before,(tuple,list)) or len(before)!=2 or isinstance(before[0],bool) or not isinstance(before[0],(int,float)) or not math.isfinite(before[0]) or not isinstance(before[1],str) or not re.fullmatch('[a-f0-9]{64}',before[1]):raise BuilderFailure('invalid_builder_cursor')
        clause+=' AND (entered<? OR (entered=? AND id<?))';args.extend((before[0],before[0],before[1]))
    required=list(value['group_by'])+['answered','outcome','wait_seconds','talk_seconds'] if value['group_by'] else list(value['columns'])
    selected=tuple(dict.fromkeys([*required,'queue','entered','id']))
    text_columns=[key for key in selected if key not in ('entered','answered','ended','wait_seconds','talk_seconds')]
    expressions=[_bounded(key)+' AS '+key if key in text_columns else key for key in selected]
    with archive.reader() as db:
        visit_snapshots.validate(db,archive.pbx,spec['snapshot'])
        rows=[dict(row) for row in db.execute('SELECT '+','.join(expressions)+','+_oversized(text_columns)+''' AS _oversized
          FROM report_visit_versions v WHERE '''+clause+''' AND v.seq<=? AND v.deleted=0
          AND NOT EXISTS (SELECT 1 FROM report_visit_versions newer WHERE newer.pbx=v.pbx
            AND newer.id=v.id AND newer.seq>v.seq AND newer.seq<=?)
          ORDER BY v.entered DESC,v.id DESC LIMIT ?''',(*args,spec['snapshot']['sequence'],spec['snapshot']['sequence'],limit))]
    if any(row.pop('_oversized') for row in rows):raise BuilderFailure('builder_field_limit')
    return rows


class Groups:
    """Combine sufficient statistics over all pages, never page averages."""
    def __init__(self,value):self.keys=value['group_by'];self.values={}
    def add(self,rows):
        for row in rows:
            key=tuple(row[column] for column in self.keys)
            if key not in self.values:
                if len(self.values)>=MAX_GROUPS:raise BuilderFailure('builder_group_limit')
                self.values[key]=dict(visits=0,answered_known=0,abandoned=0,wait_known=0,talk_known=0,wait_sum=0.0,talk_sum=0.0)
            item=self.values[key];item['visits']+=1;item['answered_known']+=int(row['answered'] is not None);item['abandoned']+=int(row['outcome']=='abandoned')
            for field,prefix in [('wait_seconds','wait'),('talk_seconds','talk')]:
                number=row[field]
                if number is not None:
                    if type(number) not in (int,float) or not math.isfinite(number):raise BuilderFailure('builder_field_limit')
                    item[prefix+'_known']+=1;item[prefix+'_sum']+=number
                    if not math.isfinite(item[prefix+'_sum']):raise BuilderFailure('builder_field_limit')
    def rows(self):
        result=[]
        # Match SQLite BINARY ascending order, with NULL before text.
        for key in sorted(self.values,key=lambda parts:tuple((value is not None,value or '') for value in parts)):
            item=self.values[key];row=dict(zip(self.keys,key))
            row.update({name:item[name] for name in ('visits','answered_known','abandoned','wait_known','talk_known')})
            row.update(average_wait_seconds=item['wait_sum']/item['wait_known'] if item['wait_known'] else None,
                average_queue_talk_seconds=item['talk_sum']/item['talk_known'] if item['talk_known'] else None,
                queue_talk_seconds=item['talk_sum'] if item['talk_known'] else None)
            result.append(row)
        return result


def body(rows,value,spec,number_key):
    result=[];fa=spec['language']=='fa'
    labels=dict(answered='پاسخ‌داده',abandoned='رهاشده',transferred='منتقل‌شده',waiting='منتظر',connected='متصل',exitwithtimeout='پایان مهلت',exitempty='صف خالی',exitwithkey='خروج با کلید',reentered_without_end='ورود دوباره با پایان نامعلوم',unknown='نامعلوم',caller='تماس‌گیرنده',agent='کارشناس',observed='ثبت‌شده',missing_entry='شروع گمشده',missing_end='پایان گمشده')
    for row in rows:
        cells=[]
        for key in columns(value):
            cell=row[key]
            if key=='caller':cell=display_number(cell,spec['number_modes'][row['queue']],secret=number_key,tenant='default',pbx=spec['pbx'],version=spec['number_policy_version'])
            if cell is not None:
                if key in ('entered','answered','ended'):
                    local=datetime.fromtimestamp(cell,ZoneInfo('Asia/Tehran'));cell=(persian_date(local.date()) if fa else local.date().isoformat())+local.strftime(' %H:%M:%S')
                elif type(cell) in (int,float):
                    if not math.isfinite(cell):raise BuilderFailure('builder_field_limit')
                else:
                    cell=str(cell)
                    if fa and key in ('outcome','segment_ended_by','coverage'):cell=labels.get(cell,cell)
                    if spec['format']=='csv' and (key in ('queue','caller','agent','id') or cell.lstrip().startswith(('=','+','-','@')) or cell.startswith(('\t','\r','\n'))):cell="'"+cell
            cells.append(cell)
        result.append(cells)
    return result


class Workbook(xlsx_stream.Workbook):
    """Reuse bounded OOXML append/abort with exact custom header geometry."""
    def __init__(self,output,language,*,headers,period='',max_bytes=32*1024*1024):
        if not 1<=len(headers)<=12:raise BuilderFailure('builder_column_limit')
        self.language=language;self.row=0;self.xml_size=0;self.max_xml_bytes=64*1024*1024;self.closed=False;self.last_column=chr(64+len(headers))
        self.archive=ZipFile(xlsx_stream._BoundedFile(output,max_bytes),'w',ZIP_DEFLATED,compresslevel=1)
        try:
            with ZipFile(io.BytesIO(xlsx_bytes([],language,period=period))) as template:
                for name in template.namelist():
                    if name!='xl/worksheets/sheet1.xml':self.archive.writestr(name,template.read(name))
                prefix=template.read('xl/worksheets/sheet1.xml').split(b'<sheetData',1)[0]
            width=b'<cols>'+b''.join(('<col min="'+str(n)+'" max="'+str(n)+'" width="26" customWidth="1"/>').encode() for n in range(1,len(headers)+1))+b'</cols>'
            prefix=re.sub(rb'<cols>.*?</cols>',lambda match:width,prefix)
            self.sheet=self.archive.open('xl/worksheets/sheet1.xml','w');self._write(prefix+b'<sheetData>')
            title='گزارش سفارشی مراجعه صف' if language=='fa' else 'Custom queue-visit report'
            self.append([[title],['Asia/Tehran · '+period],[],headers])
        except Exception:
            try:
                if hasattr(self,'sheet'):self.sheet.close()
            except Exception:pass
            try:self.archive.close()
            except Exception:pass
            self.closed=True
            raise
    def close(self):
        if self.closed:return
        try:
            last=self.last_column
            merges='' if last=='A' else '<mergeCells count="2"><mergeCell ref="A1:'+last+'1"/><mergeCell ref="A2:'+last+'2"/></mergeCells>'
            self._write(('</sheetData><autoFilter ref="A4:'+last+str(self.row)+'"/>'+merges+'</worksheet>').encode())
        finally:
            self.closed=True
            try:self.sheet.close()
            finally:self.archive.close()
