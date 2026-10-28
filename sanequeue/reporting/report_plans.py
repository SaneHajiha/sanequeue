"""Private saved reports and daily, Tehran-clock in-app occurrences.

Trusted scheduler methods due/reserve_due see other owners; HTTP access uses
owner-scoped methods. The scheduler must reauthorize all frozen queues and use
occurrence.id as the export callback idempotency key: two databases cannot
otherwise guarantee exactly-once dispatch after a crash. Never email/upload.
Quotas include archived plans. Old versions and occurrence history are kept.
Only today's due occurrences are created; downtime days are not backfilled.
"""
from contextlib import contextmanager
from datetime import datetime,timedelta
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

from .store import QueryDeadline

_ZONE=ZoneInfo('Asia/Tehran')
MAX_OWNER_PLANS=200
MAX_PLANS=1000
_PERIODS={'yesterday','last7days','previous_month','previous_persian_month'}
_OUTCOMES={'answered','abandoned','waiting','connected','transferred','exitwithtimeout',
           'exitempty','exitwithkey','unknown','reentered_without_end'}
_REASONS={'export_failed','export_unavailable','access_revoked','scope_invalid','system_busy',
          'disk_pressure','module_disabled','plan_disabled','lease_expired','cancelled'}


class PlanConflict(RuntimeError):pass
class PlanUnavailable(RuntimeError):pass


def _text(value,maximum,label):
    if not isinstance(value,str) or not 1<=len(value)<=maximum or not value.strip() or not value.isprintable():
        raise ValueError('invalid_report_plan_'+label)
    return value


def _id(value):
    if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{32}',value):raise ValueError('invalid_report_plan_id')
    return value


def _limit(value):
    if isinstance(value,bool) or not isinstance(value,int) or value<1:raise ValueError('invalid_report_plan_limit')
    return min(100,value)


def _stamp(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)):raise ValueError('invalid_report_plan_time')
    try:valid=math.isfinite(value) and 0<=value<=32503680000
    except OverflowError:valid=False
    if not valid:raise ValueError('invalid_report_plan_time')
    return float(value)


def _json(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def period_bounds(now,period):
    """Explicit calendar months, Tehran midnight, half-open complete days."""
    now=_stamp(now)
    if period not in _PERIODS:raise ValueError('invalid_report_plan_period')
    today=datetime.fromtimestamp(now,_ZONE).date()
    calendar='gregorian'
    if period=='previous_persian_month':
        from .exports import persian_date
        def jalali_day(day):
            value=persian_date(day)
            if not re.fullmatch(r'[0-9]{4}/[0-9]{2}/[0-9]{2}',value):
                raise ValueError('report_plan_persian_calendar_out_of_range')
            return int(value[-2:])
        last=today-timedelta(days=jalali_day(today)-1)
        previous=last-timedelta(days=1)
        first=previous-timedelta(days=jalali_day(previous)-1)
        calendar='persian'
    elif period=='previous_month':
        last=today.replace(day=1);first=(last-timedelta(days=1)).replace(day=1)
    else:last=today;first=today-timedelta(days=1 if period=='yesterday' else 7)
    midnight=lambda day:datetime.combine(day,datetime.min.time(),_ZONE).timestamp()
    return dict(start=midnight(first),end=midnight(last),period=period,timezone='Asia/Tehran',calendar=calendar)


class SavedReports:
    def __init__(self,path,pbx='primary'):
        self.path=Path(path).absolute();self.pbx=_text(pbx,128,'pbx')

    def initialize(self):
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            if self.path.is_symlink():raise OSError('plan_symlink')
            fd=os.open(self.path,os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0),0o600)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):raise OSError('plan_not_regular')
                if os.name!='nt':os.fchmod(fd,0o600)
            finally:os.close(fd)
            with self._db(write=True) as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'").fetchone():raise OSError('plan_is_archive')
                db.commit()
                if db.execute('PRAGMA journal_mode=WAL').fetchone()[0].lower()!='wal':raise OSError('plan_wal_unavailable')
                db.executescript('''CREATE TABLE IF NOT EXISTS report_plans(
                  id TEXT PRIMARY KEY,pbx TEXT,owner TEXT,version INTEGER,spec TEXT,
                  created REAL,updated REAL,enabled INTEGER,archived INTEGER DEFAULT 0);
                  CREATE INDEX IF NOT EXISTS rp_owner ON report_plans(pbx,owner,updated,id);
                  CREATE TABLE IF NOT EXISTS report_plan_versions(
                    plan_id TEXT,version INTEGER,spec TEXT,created REAL,PRIMARY KEY(plan_id,version));
                  CREATE TABLE IF NOT EXISTS report_occurrences(
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,
                    pbx TEXT,plan_id TEXT,owner TEXT,date_key TEXT,version INTEGER,spec TEXT,
                    state TEXT,created REAL,updated REAL,available_at REAL,worker TEXT,lease_until REAL,
                    attempts INTEGER DEFAULT 0,error TEXT,export_job_id TEXT,
                    UNIQUE(plan_id,date_key));
                  CREATE INDEX IF NOT EXISTS ro_queue ON report_occurrences(pbx,state,available_at,sequence);
                  CREATE INDEX IF NOT EXISTS ro_owner ON report_occurrences(pbx,owner,plan_id,sequence);
                  CREATE TRIGGER IF NOT EXISTS rpv_no_update BEFORE UPDATE ON report_plan_versions BEGIN SELECT RAISE(ABORT,'immutable_plan_version'); END;
                  CREATE TRIGGER IF NOT EXISTS rpv_no_delete BEFORE DELETE ON report_plan_versions BEGIN SELECT RAISE(ABORT,'immutable_plan_version'); END;
                  CREATE TRIGGER IF NOT EXISTS ro_spec_immutable BEFORE UPDATE OF id,pbx,plan_id,owner,date_key,version,spec,created ON report_occurrences
                    BEGIN SELECT RAISE(ABORT,'immutable_report_occurrence'); END;''')
        except (OSError,sqlite3.Error):raise PlanUnavailable('report_plan_store_unavailable') from None

    @contextmanager
    def _db(self,write=False):
        db=None
        try:
            if self.path.is_symlink() or not self.path.is_file():raise OSError('plan_file_missing')
            if os.name!='nt' and self.path.stat().st_mode&0o077:raise OSError('plan_permissions')
            db=sqlite3.connect(self.path.as_uri()+('?mode=rw' if write else '?mode=ro'),uri=True,timeout=.25)
            db.row_factory=sqlite3.Row;db.execute('PRAGMA trusted_schema=OFF')
            if write:db.execute('PRAGMA synchronous=FULL');db.execute('BEGIN IMMEDIATE')
            else:
                deadline=time.monotonic()+.5;db.set_progress_handler(lambda:int(time.monotonic()>=deadline),100)
                db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            with db:yield db
        except sqlite3.OperationalError as error:
            if 'interrupt' in str(error).lower():raise QueryDeadline('report_plan_query_deadline') from None
            raise PlanUnavailable('report_plan_store_unavailable') from None
        except (OSError,sqlite3.Error):raise PlanUnavailable('report_plan_store_unavailable') from None
        finally:
            if db is not None:db.close()

    @staticmethod
    def _plan(row):
        if row is None:return None
        return dict(json.loads(row['spec']),id=row['id'],owner=row['owner'],version=row['version'],
                    created=row['created'],updated=row['updated'],archived=bool(row['archived']),enabled=bool(row['enabled']))

    @staticmethod
    def _occurrence(row,worker=False):
        if row is None:return None
        value={key:row[key] for key in ('id','plan_id','owner','date_key','version','state','created','updated','attempts','error','export_job_id')}
        value['spec']=json.loads(row['spec'])
        if worker:value.update(worker=row['worker'],lease_until=row['lease_until'])
        return value

    def save(self,owner,name,queues,outcome=None,format='xlsx',language='fa',period='yesterday',at='08:00',weekdays=None,enabled=False,ident=None,*,builder_definition=None):
        owner=_text(owner,128,'owner');name=_text(name,120,'name')
        if not isinstance(queues,(list,tuple,set)) or not 1<=len(queues)<=256:raise ValueError('invalid_report_plan_queues')
        queues=sorted({_text(queue,128,'queue') for queue in queues})
        if outcome is not None and outcome not in _OUTCOMES:raise ValueError('invalid_report_plan_outcome')
        if format not in ('xlsx','csv','pdf') or language not in ('fa','en') or period not in _PERIODS:raise ValueError('invalid_report_plan_options')
        if not isinstance(at,str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',at):raise ValueError('invalid_report_plan_at')
        if not isinstance(enabled,bool):raise ValueError('invalid_report_plan_enabled')
        weekdays=list(range(7)) if weekdays is None else weekdays
        if not isinstance(weekdays,(list,tuple)) or not 1<=len(weekdays)<=7 or any(isinstance(day,bool) or not isinstance(day,int) or not 0<=day<=6 for day in weekdays):raise ValueError('invalid_report_plan_weekdays')
        spec=dict(name=name,queues=queues,outcome=outcome,format=format,language=language,period=period,
                  at=at,weekdays=sorted(set(weekdays)),destination='in_app',timezone='Asia/Tehran',
                  calendar='persian' if period=='previous_persian_month' else 'gregorian',enabled=enabled,archived=False)
        if builder_definition is not None:
            from .report_builder import definition
            frozen=definition(builder_definition)
            if frozen['queues']!=queues:raise ValueError('report_plan_builder_scope_mismatch')
            if outcome is not None:raise ValueError('report_plan_builder_outcome_in_definition')
            if format not in ('csv','xlsx'):raise ValueError('report_plan_builder_format_unsupported')
            # Store the complete canonical definition, never a pointer to a
            # mutable template's latest version. Occurrences freeze this JSON.
            spec['builder_definition']=frozen
        if ident is not None:_id(ident)
        now=time.time()
        with self._db(write=True) as db:
            prior=db.execute('SELECT * FROM report_plans WHERE pbx=? AND id=? AND owner=?',(self.pbx,ident,owner)).fetchone() if ident else None
            if ident and prior is None:return None
            if prior and prior['archived']:raise PlanConflict('report_plan_archived')
            if prior:version=prior['version']+1
            else:
                quotas=db.execute('SELECT COUNT(*),COALESCE(SUM(owner=?),0) FROM report_plans',(owner,)).fetchone()
                if quotas[0]>=MAX_PLANS or quotas[1]>=MAX_OWNER_PLANS:raise PlanConflict('report_plan_quota')
                ident=uuid.uuid4().hex;version=1
            payload=_json(spec)
            if prior:db.execute('UPDATE report_plans SET version=?,spec=?,updated=?,enabled=? WHERE id=?',(version,payload,now,int(enabled),ident))
            else:db.execute('INSERT INTO report_plans VALUES(?,?,?,?,?,?,?,?,0)',(ident,self.pbx,owner,version,payload,now,now,int(enabled)))
            db.execute('INSERT INTO report_plan_versions VALUES(?,?,?,?)',(ident,version,payload,now))
            if not enabled:db.execute("UPDATE report_occurrences SET state='cancelled',worker=NULL,lease_until=NULL,error='plan_disabled',updated=? WHERE plan_id=? AND state IN ('queued','running')",(now,ident))
            return self._plan(db.execute('SELECT * FROM report_plans WHERE id=?',(ident,)).fetchone())

    def get(self,ident,owner):
        _id(ident);owner=_text(owner,128,'owner')
        with self._db() as db:return self._plan(db.execute('SELECT * FROM report_plans WHERE pbx=? AND id=? AND owner=?',(self.pbx,ident,owner)).fetchone())

    def list(self,owner,limit=100):
        owner=_text(owner,128,'owner');limit=_limit(limit)
        with self._db() as db:return [self._plan(row) for row in db.execute('SELECT * FROM report_plans WHERE pbx=? AND owner=? ORDER BY updated DESC,id DESC LIMIT ?',(self.pbx,owner,limit))]

    def delete(self,ident,owner):
        _id(ident);owner=_text(owner,128,'owner');now=time.time()
        with self._db(write=True) as db:
            row=db.execute('SELECT * FROM report_plans WHERE pbx=? AND id=? AND owner=?',(self.pbx,ident,owner)).fetchone()
            if row is None:return False
            if row['archived']:return False
            spec=json.loads(row['spec']);spec.update(enabled=False,archived=True);version=row['version']+1;payload=_json(spec)
            db.execute('UPDATE report_plans SET version=?,spec=?,enabled=0,archived=1,updated=? WHERE id=?',(version,payload,now,ident))
            db.execute('INSERT INTO report_plan_versions VALUES(?,?,?,?)',(ident,version,payload,now))
            db.execute("UPDATE report_occurrences SET state='cancelled',worker=NULL,lease_until=NULL,error='plan_disabled',updated=? WHERE plan_id=? AND state IN ('queued','running')",(now,ident))
            return True

    def _due_rows(self,db,now,limit=20):
        local=datetime.fromtimestamp(now,_ZONE);date_key=local.date().isoformat();weekday=(local.weekday()+2)%7
        rows=db.execute('''SELECT p.id,p.owner,p.version FROM report_plans p WHERE p.pbx=? AND p.enabled=1 AND p.archived=0
          AND json_extract(p.spec,'$.at')<=? AND EXISTS(SELECT 1 FROM json_each(p.spec,'$.weekdays') WHERE value=?)
          AND NOT EXISTS(SELECT 1 FROM report_occurrences o WHERE o.plan_id=p.id AND o.date_key=?)
          ORDER BY p.id LIMIT ?''',(self.pbx,local.strftime('%H:%M'),weekday,date_key,min(20,limit))).fetchall()
        return [dict(row,date_key=date_key) for row in rows]

    def due(self,now):
        """Trusted scheduler preview only; owner-facing HTTP must not expose it."""
        now=_stamp(now)
        with self._db() as db:return self._due_rows(db,now)

    def reserve_due(self,worker,now=None):
        """Use a fresh random worker token per attempt, never a process name."""
        worker=_text(worker,128,'worker');now=_stamp(time.time() if now is None else now)
        with self._db(write=True) as db:
            db.execute("UPDATE report_occurrences SET state=CASE WHEN attempts>=3 THEN 'failed' ELSE 'queued' END,worker=NULL,lease_until=NULL,available_at=?,updated=?,error='lease_expired' WHERE pbx=? AND state='running' AND lease_until<?",(now,now,self.pbx,now))
            db.execute("UPDATE report_occurrences SET state='cancelled',worker=NULL,lease_until=NULL,updated=?,error='plan_disabled' WHERE pbx=? AND state IN ('queued','running') AND NOT EXISTS(SELECT 1 FROM report_plans p WHERE p.id=plan_id AND p.enabled=1 AND p.archived=0)",(now,self.pbx))
            row=db.execute("SELECT o.* FROM report_occurrences o JOIN report_plans p ON p.id=o.plan_id WHERE o.pbx=? AND o.state='queued' AND o.available_at<=? AND p.enabled=1 AND p.archived=0 ORDER BY o.sequence LIMIT 1",(self.pbx,now)).fetchone()
            if row is None:
                due=self._due_rows(db,now,1)
                if not due:return None
                plan=db.execute('SELECT * FROM report_plans WHERE id=?',(due[0]['id'],)).fetchone();spec=self._plan(plan)
                spec.update(period_bounds(now,spec['period']),pbx=self.pbx,plan_id=plan['id'],date_key=due[0]['date_key'])
                ident=uuid.uuid4().hex
                db.execute('''INSERT INTO report_occurrences(id,pbx,plan_id,owner,date_key,version,spec,state,created,updated,available_at)
                    VALUES(?,?,?,?,?,?,?,'queued',?,?,?)''',(ident,self.pbx,plan['id'],plan['owner'],due[0]['date_key'],plan['version'],_json(spec),now,now,now))
                row=db.execute('SELECT * FROM report_occurrences WHERE id=?',(ident,)).fetchone()
            db.execute("UPDATE report_occurrences SET state='running',worker=?,lease_until=?,attempts=attempts+1,error=NULL,updated=? WHERE id=?",(worker,now+60,now,row['id']))
            return self._occurrence(db.execute('SELECT * FROM report_occurrences WHERE id=?',(row['id'],)).fetchone(),worker=True)

    def _working(self,db,ident,worker,now):
        return db.execute("""SELECT o.id FROM report_occurrences o JOIN report_plans p ON p.id=o.plan_id
            WHERE o.pbx=? AND o.id=? AND o.state='running' AND o.worker=? AND o.lease_until>=?
            AND p.enabled=1 AND p.archived=0""",(self.pbx,ident,worker,now)).fetchone() is not None

    def renew(self,ident,worker):
        _id(ident);worker=_text(worker,128,'worker');now=time.time()
        with self._db(write=True) as db:
            if not self._working(db,ident,worker,now):return False
            db.execute('UPDATE report_occurrences SET lease_until=?,updated=? WHERE id=?',(now+60,now,ident));return True

    def finish(self,ident,worker,export_job_id):
        _id(ident);_id(export_job_id);worker=_text(worker,128,'worker');now=time.time()
        with self._db(write=True) as db:
            if not self._working(db,ident,worker,now):return False
            db.execute("UPDATE report_occurrences SET state='completed',export_job_id=?,worker=NULL,lease_until=NULL,error=NULL,updated=? WHERE id=?",(export_job_id,now,ident));return True

    def fail(self,ident,worker,reason):
        _id(ident);worker=_text(worker,128,'worker')
        if reason not in _REASONS:raise ValueError('invalid_report_plan_reason')
        now=time.time()
        with self._db(write=True) as db:
            if not self._working(db,ident,worker,now):return False
            db.execute("UPDATE report_occurrences SET state='failed',worker=NULL,lease_until=NULL,error=?,updated=? WHERE id=?",(reason,now,ident));return True

    def defer(self,ident,worker,reason='system_busy',delay=30):
        _id(ident);worker=_text(worker,128,'worker')
        if reason not in _REASONS:raise ValueError('invalid_report_plan_reason')
        delay=_stamp(delay)
        if not 1<=delay<=3600:raise ValueError('invalid_report_plan_delay')
        now=time.time()
        with self._db(write=True) as db:
            if not self._working(db,ident,worker,now):return False
            db.execute("UPDATE report_occurrences SET state='queued',worker=NULL,lease_until=NULL,attempts=MAX(0,attempts-1),available_at=?,error=?,updated=? WHERE id=?",(now+delay,reason,now,ident));return True

    def retry(self,ident,owner):
        _id(ident);owner=_text(owner,128,'owner');now=time.time()
        with self._db(write=True) as db:
            return db.execute("""UPDATE report_occurrences SET state='queued',available_at=?,error=NULL,updated=?
              WHERE pbx=? AND id=? AND owner=? AND state='failed' AND attempts<3 AND EXISTS(
                SELECT 1 FROM report_plans p WHERE p.id=plan_id AND p.enabled=1 AND p.archived=0)""",
                (now,now,self.pbx,ident,owner)).rowcount==1

    def occurrence(self,ident,owner):
        _id(ident);owner=_text(owner,128,'owner')
        with self._db() as db:return self._occurrence(db.execute('SELECT * FROM report_occurrences WHERE pbx=? AND id=? AND owner=?',(self.pbx,ident,owner)).fetchone())

    def occurrences(self,planid,owner,limit=100):
        _id(planid);owner=_text(owner,128,'owner');limit=_limit(limit)
        with self._db() as db:return [self._occurrence(row) for row in db.execute('SELECT * FROM report_occurrences WHERE pbx=? AND plan_id=? AND owner=? ORDER BY sequence DESC LIMIT ?',(self.pbx,planid,owner,limit))]
