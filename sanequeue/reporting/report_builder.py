"""Bounded queue-visit builder. Definitions are data, never caller-provided SQL."""
import base64
import csv
import hashlib
from contextlib import contextmanager
from datetime import datetime
import io
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
import uuid
from zoneinfo import ZoneInfo

from .queries import Scope,_where
from .privacy import display_number
from .store import Archive,QueryDeadline

COLUMNS=('queue','caller','agent','outcome','entered','answered','ended','wait_seconds','talk_seconds','segment_ended_by','coverage','id')
GROUPS=('queue','agent','outcome')
OUTCOMES=('answered','abandoned','waiting','connected','transferred','exitwithtimeout','exitempty','exitwithkey','unknown','reentered_without_end')
DEFAULT=dict(dataset='queue_visits',columns=['queue','caller','agent','outcome','entered','wait_seconds','talk_seconds'],group_by=[],filters={})
EXPORT_MAX_ROWS=500
EXPORT_MAX_BYTES=4*1024*1024
class BuilderConflict(RuntimeError):pass
class BuilderUnavailable(RuntimeError):pass


def _text(value,maximum):
    if not isinstance(value,str) or not 1<=len(value)<=maximum or not value.strip() or any(ord(c)<32 for c in value):raise ValueError('invalid_builder_text')
    return value


def definition(value):
    if not isinstance(value,dict) or set(value)-{'dataset','columns','group_by','filters','queues'}:raise ValueError('invalid_builder_definition')
    if value.get('dataset')!='queue_visits':raise ValueError('invalid_builder_dataset')
    result={'dataset':'queue_visits'}
    for name,allowed,minimum,maximum in [('columns',COLUMNS,1,12),('group_by',GROUPS,0,2)]:
        selected=value.get(name,[])
        if not isinstance(selected,list) or not minimum<=len(selected)<=maximum or any(not isinstance(x,str) or x not in allowed for x in selected) or len(set(selected))!=len(selected):raise ValueError('invalid_builder_'+name)
        result[name]=list(selected)
    queues=value.get('queues',[])
    if not isinstance(queues,list) or not 1<=len(queues)<=256:raise ValueError('invalid_builder_queues')
    result['queues']=sorted(set(_text(q,128) for q in queues))
    filters=value.get('filters',{})
    if not isinstance(filters,dict) or set(filters)-{'outcomes','wait_min','wait_max','talk_min','talk_max'}:raise ValueError('invalid_builder_filters')
    result['filters']={}
    for key,number in filters.items():
        if key=='outcomes':
            if not isinstance(number,list) or len(number)>len(OUTCOMES) or any(not isinstance(x,str) or x not in OUTCOMES for x in number):raise ValueError('invalid_builder_outcomes')
            result['filters'][key]=sorted(set(number))
        else:
            if isinstance(number,bool) or not isinstance(number,(int,float)) or not math.isfinite(number) or not 0<=number<=86400:raise ValueError('invalid_builder_threshold')
            result['filters'][key]=float(number)
    for field in ('wait','talk'):
        if result['filters'].get(field+'_min',0)>result['filters'].get(field+'_max',86400):raise ValueError('invalid_builder_threshold')
    return result


def _json(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def _bounded(column):
    return 'CASE WHEN length(CAST('+column+' AS BLOB))<=2048 THEN '+column+' END'


def _oversized(columns):
    return 'CASE WHEN '+' OR '.join('length(CAST('+c+' AS BLOB))>2048' for c in columns)+' THEN 1 ELSE 0 END'


class Templates:
    """Private versioned metadata only; startup initializes a separate database."""
    def __init__(self,path,pbx='primary'):self.path=Path(path).absolute();self.pbx=_text(pbx,128)
    def initialize(self):
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        if self.path.is_symlink():raise BuilderUnavailable('builder_storage_unavailable')
        fd=os.open(self.path,os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0),0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):raise BuilderUnavailable('builder_storage_unavailable')
            if os.name!='nt':os.fchmod(fd,0o600)
        finally:os.close(fd)
        with self._db(True) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='events'").fetchone():raise BuilderUnavailable('builder_storage_is_archive')
            db.commit()
            if db.execute('PRAGMA journal_mode=WAL').fetchone()[0].lower()!='wal':raise BuilderUnavailable('builder_storage_unavailable')
            db.executescript('''CREATE TABLE IF NOT EXISTS builder_templates(pbx TEXT,id TEXT,version INTEGER,owner TEXT,name TEXT,spec TEXT,created REAL,PRIMARY KEY(pbx,id,version));
            CREATE INDEX IF NOT EXISTS builder_owner ON builder_templates(pbx,owner,created);
            CREATE TRIGGER IF NOT EXISTS builder_immutable_update BEFORE UPDATE ON builder_templates BEGIN SELECT RAISE(ABORT,'immutable');END;
            CREATE TRIGGER IF NOT EXISTS builder_immutable_delete BEFORE DELETE ON builder_templates BEGIN SELECT RAISE(ABORT,'immutable');END;''')
    @contextmanager
    def _db(self,write=False):
        if self.path.is_symlink() or not self.path.is_file():raise BuilderUnavailable('builder_storage_unavailable')
        db=sqlite3.connect(self.path if write else self.path.as_uri()+'?mode=ro',uri=not write,timeout=.25)
        db.row_factory=sqlite3.Row;deadline=time.monotonic()+.5
        db.set_progress_handler(lambda:time.monotonic()>deadline,500)
        try:
            db.execute('PRAGMA trusted_schema=OFF')
            if write:db.execute('BEGIN IMMEDIATE')
            with db:yield db
        except sqlite3.Error:raise BuilderUnavailable('builder_storage_unavailable') from None
        finally:db.close()
    def _row(self,row):
        if row is None:return None
        return dict(id=row['id'],version=row['version'],name=row['name'],definition=json.loads(row['spec']),created=row['created'])
    def save(self,owner,name,spec,*,ident=None,expected_version=None):
        owner=_text(owner,128);name=_text(name,120);spec=definition(spec)
        if ident is not None and (not isinstance(ident,str) or not re.fullmatch('[0-9a-f]{32}',ident)):raise ValueError('invalid_builder_id')
        if ident is not None and (isinstance(expected_version,bool) or not isinstance(expected_version,int)):raise ValueError('invalid_builder_version')
        with self._db(True) as db:
            if ident:
                prior=db.execute('SELECT * FROM builder_templates WHERE pbx=? AND id=? AND owner=? ORDER BY version DESC LIMIT 1',(self.pbx,ident,owner)).fetchone()
                if prior is None:raise FileNotFoundError()
                if expected_version!=prior['version']:raise BuilderConflict('builder_version_conflict')
                if prior['version']>=50:raise BuilderConflict('builder_version_limit')
                version=prior['version']+1
            else:
                count=db.execute('SELECT COUNT(DISTINCT id),COUNT(DISTINCT CASE WHEN owner=? THEN id END) FROM builder_templates WHERE pbx=?',(owner,self.pbx)).fetchone()
                if count[0]>=1000 or count[1]>=100:raise BuilderConflict('builder_template_limit')
                ident=uuid.uuid4().hex;version=1
            db.execute('INSERT INTO builder_templates VALUES(?,?,?,?,?,?,?)',(self.pbx,ident,version,owner,name,_json(spec),time.time()))
        return self.get(ident,owner)
    def get(self,ident,owner):
        with self._db() as db:return self._row(db.execute('SELECT * FROM builder_templates WHERE pbx=? AND id=? AND owner=? ORDER BY version DESC LIMIT 1',(self.pbx,ident,_text(owner,128))).fetchone())
    def list(self,owner):
        with self._db() as db:return [self._row(row) for row in db.execute('''SELECT t.* FROM builder_templates t WHERE pbx=? AND owner=? AND version=(SELECT MAX(v.version) FROM builder_templates v WHERE v.pbx=t.pbx AND v.id=t.id) ORDER BY created DESC,id LIMIT 100''',(self.pbx,_text(owner,128)))]


def preview(archive,scope,start,end,spec,*,number_modes,number_key=None,before=None,limit=50,_export=False):
    spec=definition(spec)
    if end-start>31*86400:raise ValueError('builder_range_limit')
    if not set(spec['queues']).issubset(scope.queues):raise PermissionError('builder_scope_revoked')
    if set(number_modes)!=set(spec['queues']) or any(mode not in ('full','masked','pseudonymous') for mode in number_modes.values()):raise ValueError('invalid_builder_number_policy')
    scoped=Scope(tuple(spec['queues']),scope.agents,scope.self_only,scope.not_before)
    clause,args=_where(archive.pbx,scoped,start,end)
    filters=spec['filters'];outcomes=filters.get('outcomes',[])
    if outcomes:clause+=' AND outcome IN ('+','.join('?' for _ in outcomes)+')';args+=outcomes
    for key,column,operator in [('wait_min','wait_seconds','>='),('wait_max','wait_seconds','<='),('talk_min','talk_seconds','>='),('talk_max','talk_seconds','<=')]:
        if key in filters:clause+=' AND '+column+operator+'?';args.append(filters[key])
    bounded=Archive(archive.path,pbx=archive.pbx,read_seconds=min(2,archive.read_seconds))
    contract=dict(unit='queue_visit',conversation_unique=False,complete_source_coverage=False,
        answered_denominator='visits with a known answered timestamp',wait_denominator='visits with known wait_seconds',
        talk_denominator='visits with known queue-segment talk_seconds; not whole conversations',
        time_filter='entered in [max(start, assignment_cutoff), end)',threshold_unknown='NULL durations do not match numeric thresholds')
    if spec['group_by']:
        if before:raise ValueError('builder_aggregate_cursor_unsupported')
        group=','.join(_bounded(c) for c in spec['group_by'])
        selected=','.join(_bounded(c)+' AS '+c for c in spec['group_by'])
        with bounded.reader() as db:
            projection=db.execute('SELECT after_id,updated FROM report_projection WHERE pbx=?',(archive.pbx,)).fetchone() if _export else None
            rows=[dict(row) for row in db.execute('SELECT '+selected+',MAX('+_oversized(spec['group_by'])+''') _oversized,COUNT(*) visits,COUNT(answered) answered_known,
                SUM(outcome='abandoned') abandoned,COUNT(wait_seconds) wait_known,AVG(wait_seconds) average_wait_seconds,
                COUNT(talk_seconds) talk_known,AVG(talk_seconds) average_queue_talk_seconds,SUM(talk_seconds) queue_talk_seconds
                FROM report_visits WHERE '''+clause+' GROUP BY '+group+' ORDER BY '+group+' LIMIT 501',args)]
        if len(rows)>500:raise ValueError('builder_group_limit')
        if any(row.pop('_oversized') for row in rows):raise ValueError('builder_field_limit')
        result=dict(mode='aggregate',columns=spec['group_by']+['visits','answered_known','abandoned','wait_known','average_wait_seconds','talk_known','average_queue_talk_seconds','queue_talk_seconds'],rows=rows,next=None,contract=contract)
        if _export:result['projection']=dict(projection) if projection else None
        return result
    if isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=(EXPORT_MAX_ROWS if _export else 100):raise ValueError('invalid_builder_limit')
    if before:
        try:
            if not isinstance(before,str) or len(before)>256:raise ValueError()
            stamp,ident=json.loads(base64.b64decode(before,altchars=b'-_',validate=True))
            if isinstance(stamp,bool) or not isinstance(stamp,(int,float)) or not math.isfinite(stamp) or not isinstance(ident,str) or not re.fullmatch('[0-9a-f]{64}',ident):raise ValueError()
        except (ValueError,TypeError):raise ValueError('invalid_builder_cursor') from None
        clause+=' AND (entered<? OR (entered=? AND id<?))';args.extend((stamp,stamp,ident))
    selected=tuple(dict.fromkeys((*spec['columns'],'queue','entered','id')))
    text_columns=[c for c in selected if c not in ('entered','answered','ended','wait_seconds','talk_seconds')]
    expressions=[(_bounded(c)+' AS '+c) if c in text_columns else c for c in selected]
    with bounded.reader() as db:
        projection=db.execute('SELECT after_id,updated FROM report_projection WHERE pbx=?',(archive.pbx,)).fetchone() if _export else None
        rows=[dict(row) for row in db.execute('SELECT '+','.join(expressions)+','+_oversized(text_columns)+' AS _oversized FROM report_visits WHERE '+clause+' ORDER BY entered DESC,id DESC LIMIT ?',[*args,limit+1])]
    if any(row.pop('_oversized') for row in rows):raise ValueError('builder_field_limit')
    more=len(rows)>limit;rows=rows[:limit]
    cursor=base64.urlsafe_b64encode(_json([rows[-1]['entered'],rows[-1]['id']]).encode()).decode() if rows and more else None
    for row in rows:
        if 'caller' in row:row['caller']=display_number(row['caller'],mode=number_modes[row['queue']],secret=number_key,tenant='default',pbx=archive.pbx,version='1')
    result=dict(mode='table',columns=spec['columns'],rows=[{column:row[column] for column in spec['columns']} for row in rows],next=cursor,contract=contract)
    if _export:result['projection']=dict(projection) if projection else None
    return result


def export_csv(archive,scope,start,end,spec,*,number_modes,number_key=None,language='en'):
    """Complete bounded definition, not the visible page and never truncated.

    The exact preview query and projection watermark share one short SQLite
    read transaction. The transaction is closed before CSV encoding/download.
    Large definitions require a narrower period/filter, not a pinned WAL reader.
    """
    if language not in ('fa','en'):raise ValueError('invalid_builder_language')
    deadline=time.monotonic()+3
    result=preview(archive,scope,start,end,spec,number_modes=number_modes,number_key=number_key,
        limit=EXPORT_MAX_ROWS,_export=True)
    if result['next']:raise ValueError('builder_export_row_limit')
    fa=language=='fa'
    titles=dict(zip(COLUMNS,['صف','شماره تماس‌گیرنده','کارشناس','نتیجه','ورود (تهران)','پاسخ (تهران)','پایان بخش صف (تهران)','انتظار (ثانیه)','مکالمه صف (ثانیه)','قطع‌کننده بخش صف','پوشش شواهد','شناسه مراجعه']))
    titles.update(visits='تعداد مراجعه',answered_known='پاسخ دارای زمان معتبر',abandoned='رهاشده',wait_known='تعداد انتظار معلوم',talk_known='تعداد مکالمه معلوم',average_wait_seconds='میانگین انتظار معلوم (ثانیه)',average_queue_talk_seconds='میانگین مکالمه صف معلوم (ثانیه)',queue_talk_seconds='مجموع مکالمه صف معلوم (ثانیه)')
    values=dict(answered='پاسخ‌داده',abandoned='رهاشده',transferred='منتقل‌شده',waiting='منتظر',connected='متصل',exitwithtimeout='پایان مهلت',exitempty='صف خالی',exitwithkey='خروج با کلید',reentered_without_end='ورود دوباره با پایان نامعلوم',unknown='نامعلوم',caller='تماس‌گیرنده',agent='کارشناس',observed='ثبت‌شده',missing_entry='شروع گمشده',missing_end='پایان گمشده')
    def cell(key,value):
        if value is None:return ''
        if key in ('entered','answered','ended'):
            from .exports import persian_date
            local=datetime.fromtimestamp(value,ZoneInfo('Asia/Tehran'))
            value=(persian_date(local.date()) if fa else local.date().isoformat())+local.strftime(' %H:%M:%S')
        elif isinstance(value,(int,float)):
            if not math.isfinite(value):raise ValueError('builder_field_limit')
            return format(value,'.15g')
        elif fa and key in ('outcome','segment_ended_by','coverage'):value=values.get(value,value)
        value=str(value)
        # A leading apostrophe prevents formulas and preserves numeric identities
        # (leading zeroes, long IDs) when users open CSV directly in Excel.
        if key in ('queue','caller','agent','id') or value.lstrip().startswith(('=','+','-','@')) or value.startswith(('\t','\r','\n')):value="'"+value
        return value
    output=io.BytesIO();output.write(b'\xef\xbb\xbf')
    def write(row):
        if time.monotonic()>deadline:raise QueryDeadline('builder_export_deadline')
        text=io.StringIO(newline='');csv.writer(text).writerow(row);data=text.getvalue().encode('utf-8')
        if output.tell()+len(data)>EXPORT_MAX_BYTES:raise ValueError('builder_export_byte_limit')
        output.write(data)
    write([titles[column] if fa else column for column in result['columns']])
    for row in result['rows']:write([cell(column,row[column]) for column in result['columns']])
    return output.getvalue(),dict(rows=len(result['rows']),columns=result['columns'],projection=result['projection'],unit='queue_visit',start=float(start),end=float(end),definition_sha256=hashlib.sha256(_json(definition(spec)).encode()).hexdigest())
