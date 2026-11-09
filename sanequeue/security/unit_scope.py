"""Private organizational scope registry, independent of PBX configuration.

This is a storage and policy primitive. It does not grant access to existing
routes: consumers must apply a freshly resolved scope to every query and
recheck the revision before returning data or publishing a background result.
"""
from contextlib import contextmanager, nullcontext
import math
import hashlib
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import time
import uuid

CAPABILITIES=frozenset(('summary','call_details','full_numbers','recording_play',
                        'recording_download','export','report_builder','schedule','api','ai_report'))
KINDS=('organization','department','unit','subunit')
MAX_SCOPE_UNITS=256
MAX_SCOPE_ASSIGNMENTS=128
_ID=re.compile(r'[0-9a-f]{32}\Z')
_USER=re.compile(r'[A-Za-z0-9_.@-]{2,64}\Z')
_ENDPOINT=re.compile(r'(?:SIP|PJSIP)/[A-Za-z0-9_.-]{1,48}\Z')
_QUEUE=re.compile(r'[A-Za-z0-9_.-]{1,80}\Z')


class ScopeUnavailable(RuntimeError):pass
class ScopeConflict(RuntimeError):pass


def _id(value):
    if not isinstance(value,str) or not _ID.fullmatch(value):raise ValueError('invalid_unit_id')
    return value


def _user(value):
    if not isinstance(value,str) or not _USER.fullmatch(value):raise ValueError('invalid_unit_user')
    return value


def _endpoint(value):
    if not isinstance(value,str) or not _ENDPOINT.fullmatch(value):raise ValueError('invalid_unit_endpoint')
    return value


def _time(value):
    if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=253402300799:
        raise ValueError('invalid_unit_time')
    return float(value)


def _name(value):
    if not isinstance(value,str) or not 1<=len(value.strip())<=120 or not value.isprintable():
        raise ValueError('invalid_unit_name')
    return value.strip()


class UnitScopeStore:
    def __init__(self,path,pbx='primary'):
        self.path=Path(path).absolute();self.pbx=_name(pbx)

    @contextmanager
    def _db(self,write=False):
        if not self.path.exists() or self.path.is_symlink():raise ScopeUnavailable('unit_scope_unavailable')
        db=None
        try:
            db=sqlite3.connect(self.path.as_uri()+'?mode=rw',uri=True,timeout=2,isolation_level=None)
            db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON')
            if write:db.execute('BEGIN IMMEDIATE')
            yield db
            if write:db.commit()
        except sqlite3.IntegrityError as error:
            if db and write:db.rollback()
            raise ScopeConflict('unit_scope_conflict') from error
        except (sqlite3.Error,OSError) as error:
            if db and write:db.rollback()
            raise ScopeUnavailable('unit_scope_unavailable') from error
        except BaseException:
            if db and write:db.rollback()
            raise
        finally:
            if db:db.close()

    def initialize(self):
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            if self.path.is_symlink():raise OSError('unit_scope_symlink')
            fd=os.open(self.path,os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0),0o600)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):raise OSError('unit_scope_not_regular')
                if os.name!='nt':os.fchmod(fd,0o600)
            finally:os.close(fd)
            with self._db() as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'").fetchone():
                    raise ScopeUnavailable('unit_scope_is_archive')
                if db.execute('PRAGMA journal_mode=WAL').fetchone()[0].lower()!='wal':raise ScopeUnavailable('unit_scope_wal_unavailable')
                db.executescript('''
                CREATE TABLE IF NOT EXISTS unit_meta(pbx TEXT PRIMARY KEY,revision INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS units(pbx TEXT NOT NULL,id TEXT NOT NULL,parent TEXT,kind TEXT NOT NULL,name TEXT NOT NULL,
                  PRIMARY KEY(pbx,id),FOREIGN KEY(pbx,parent) REFERENCES units(pbx,id));
                CREATE TABLE IF NOT EXISTS unit_assignments(pbx TEXT NOT NULL,id TEXT NOT NULL,unit_id TEXT NOT NULL,
                  endpoint TEXT NOT NULL,starts REAL NOT NULL,ends REAL,PRIMARY KEY(pbx,id),
                  FOREIGN KEY(pbx,unit_id) REFERENCES units(pbx,id));
                CREATE INDEX IF NOT EXISTS ua_endpoint ON unit_assignments(pbx,endpoint,starts,ends);
                CREATE TABLE IF NOT EXISTS unit_queue_assignments(pbx TEXT NOT NULL,id TEXT NOT NULL,unit_id TEXT NOT NULL,
                  queue TEXT NOT NULL,starts REAL NOT NULL,ends REAL,PRIMARY KEY(pbx,id),
                  FOREIGN KEY(pbx,unit_id) REFERENCES units(pbx,id));
                CREATE INDEX IF NOT EXISTS uqa_queue ON unit_queue_assignments(pbx,queue,starts,ends);
                CREATE TABLE IF NOT EXISTS unit_members(pbx TEXT NOT NULL,id TEXT NOT NULL,unit_id TEXT NOT NULL,
                  username TEXT NOT NULL,starts REAL NOT NULL,ends REAL,PRIMARY KEY(pbx,id),
                  FOREIGN KEY(pbx,unit_id) REFERENCES units(pbx,id));
                CREATE TABLE IF NOT EXISTS unit_grants(pbx TEXT NOT NULL,id TEXT NOT NULL,unit_id TEXT NOT NULL,
                  username TEXT NOT NULL,capability TEXT NOT NULL,descendants INTEGER NOT NULL,active INTEGER NOT NULL,
                  PRIMARY KEY(pbx,id),FOREIGN KEY(pbx,unit_id) REFERENCES units(pbx,id));
                CREATE INDEX IF NOT EXISTS ug_user ON unit_grants(pbx,username,active,capability);
                CREATE TABLE IF NOT EXISTS unit_cursors(pbx TEXT NOT NULL,token TEXT NOT NULL,username TEXT NOT NULL,
                  revision INTEGER NOT NULL,query_hash TEXT NOT NULL,stamp REAL NOT NULL,source_key TEXT NOT NULL,
                  expires REAL NOT NULL,PRIMARY KEY(pbx,token));
                CREATE INDEX IF NOT EXISTS uc_expiry ON unit_cursors(pbx,expires);
                CREATE TABLE IF NOT EXISTS unit_recording_refs(pbx TEXT NOT NULL,token TEXT NOT NULL,username TEXT NOT NULL,
                  revision INTEGER NOT NULL,source_key TEXT NOT NULL,stamp REAL NOT NULL,expires REAL NOT NULL,PRIMARY KEY(pbx,token));
                CREATE INDEX IF NOT EXISTS urr_expiry ON unit_recording_refs(pbx,expires);
                CREATE INDEX IF NOT EXISTS urr_owner ON unit_recording_refs(pbx,username,revision,source_key,stamp);
                CREATE TABLE IF NOT EXISTS unit_ai_usage(pbx TEXT NOT NULL,username TEXT NOT NULL,at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS uai_recent ON unit_ai_usage(pbx,at,username);
                CREATE TABLE IF NOT EXISTS unit_api_tokens(pbx TEXT NOT NULL,id TEXT NOT NULL,username TEXT NOT NULL,
                  digest TEXT NOT NULL,created REAL NOT NULL,expires REAL NOT NULL,active INTEGER NOT NULL,
                  PRIMARY KEY(pbx,id),UNIQUE(pbx,digest));
                CREATE INDEX IF NOT EXISTS uat_user ON unit_api_tokens(pbx,username,active);
                CREATE TABLE IF NOT EXISTS unit_api_usage(pbx TEXT NOT NULL,token_id TEXT NOT NULL,at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS uau_recent ON unit_api_usage(pbx,at,token_id);
                CREATE TABLE IF NOT EXISTS unit_api_audit(pbx TEXT NOT NULL,id TEXT NOT NULL,at REAL NOT NULL,
                  username TEXT NOT NULL,token_id TEXT NOT NULL,dataset TEXT NOT NULL,status INTEGER NOT NULL,
                  PRIMARY KEY(pbx,id));
                CREATE INDEX IF NOT EXISTS uaa_time ON unit_api_audit(pbx,at DESC,id DESC);
                CREATE TABLE IF NOT EXISTS unit_change_audit(pbx TEXT NOT NULL,id TEXT NOT NULL,at REAL NOT NULL,
                  actor TEXT NOT NULL,operation TEXT NOT NULL,target TEXT NOT NULL,PRIMARY KEY(pbx,id));
                CREATE INDEX IF NOT EXISTS uca_time ON unit_change_audit(pbx,at DESC,id DESC);
                ''')
                db.execute('INSERT OR IGNORE INTO unit_meta VALUES(?,0)',(self.pbx,))
        except (sqlite3.Error,OSError) as error:raise ScopeUnavailable('unit_scope_unavailable') from error

    def _bump(self,db):db.execute('UPDATE unit_meta SET revision=revision+1 WHERE pbx=?',(self.pbx,))

    def _audit_change(self,db,actor,operation,target):
        if actor is None:return
        _user(actor);_id(target)
        if operation not in ('create','assign','assign_queue','member','grant','revoke','close','close_queue'):raise ValueError('invalid_unit_audit')
        if db.execute('SELECT COUNT(*) FROM unit_change_audit WHERE pbx=?',(self.pbx,)).fetchone()[0]>=100000:
            raise ScopeUnavailable('unit_change_audit_limit')
        db.execute('INSERT INTO unit_change_audit VALUES(?,?,?,?,?,?)',(self.pbx,uuid.uuid4().hex,time.time(),actor,operation,target))

    def list_change_audit(self,limit=100):
        if type(limit) is not int or not 1<=limit<=500:raise ValueError('invalid_unit_audit_limit')
        with self._db() as db:
            rows=db.execute('''SELECT c.id,c.at,c.actor,c.operation,c.target,
              COALESCE(u.name,owner.name) unit_name,COALESCE(g.username,m.username) subject,
              g.capability,a.endpoint,qa.queue
              FROM unit_change_audit c
              LEFT JOIN units u ON u.pbx=c.pbx AND u.id=c.target
              LEFT JOIN unit_grants g ON g.pbx=c.pbx AND g.id=c.target
              LEFT JOIN unit_members m ON m.pbx=c.pbx AND m.id=c.target
              LEFT JOIN unit_assignments a ON a.pbx=c.pbx AND a.id=c.target
              LEFT JOIN unit_queue_assignments qa ON qa.pbx=c.pbx AND qa.id=c.target
              LEFT JOIN units owner ON owner.pbx=c.pbx AND owner.id=COALESCE(g.unit_id,m.unit_id,a.unit_id,qa.unit_id)
              WHERE c.pbx=? ORDER BY c.at DESC,c.id DESC LIMIT ?''',
                            (self.pbx,limit)).fetchall()
        return [dict(row) for row in rows]

    def revision(self):
        with self._db() as db:
            row=db.execute('SELECT revision FROM unit_meta WHERE pbx=?',(self.pbx,)).fetchone()
            if row is None:raise ScopeUnavailable('unit_scope_uninitialized')
            return row[0]

    def inventory(self):
        """Administrative view; never pass directly to an unprivileged user."""
        with self._db() as db:
            db.execute('BEGIN')
            revision=db.execute('SELECT revision FROM unit_meta WHERE pbx=?',(self.pbx,)).fetchone()
            if revision is None:raise ScopeUnavailable('unit_scope_uninitialized')
            result={'revision':revision[0]}
            for name,table in (('units','units'),('assignments','unit_assignments'),
                               ('queue_assignments','unit_queue_assignments'),('members','unit_members'),('grants','unit_grants')):
                rows=db.execute('SELECT * FROM '+table+' WHERE pbx=? LIMIT 1001',(self.pbx,)).fetchall()
                if len(rows)>1000:raise ScopeUnavailable('unit_scope_limit')
                result[name]=[{k:r[k] for k in r.keys() if k!='pbx'} for r in rows]
            db.commit()
        return result

    def create_unit(self,name,kind,parent=None,*,actor=None,_transaction=None):
        name=_name(name)
        if kind not in KINDS:raise ValueError('invalid_unit_kind')
        if parent is not None:_id(parent)
        ident=uuid.uuid4().hex
        with (self._db(write=True) if _transaction is None else nullcontext(_transaction)) as db:
            previous=db.execute('SELECT kind FROM units WHERE pbx=? AND id=?',(self.pbx,parent)).fetchone() if parent else None
            if kind=='organization':
                if parent is not None:raise ValueError('invalid_unit_parent')
            elif not previous or KINDS.index(previous['kind'])!=KINDS.index(kind)-1:raise ValueError('invalid_unit_parent')
            db.execute('INSERT INTO units VALUES(?,?,?,?,?)',(self.pbx,ident,parent,kind,name));self._audit_change(db,actor,'create',ident);self._bump(db)
        return ident

    def _interval(self,table,unit_id,value,start,end,actor,*,_transaction=None):
        _id(unit_id);start=_time(start);end=None if end is None else _time(end)
        if end is not None and end<=start:raise ValueError('invalid_unit_interval')
        column='endpoint' if table=='unit_assignments' else 'username'
        value=_endpoint(value) if column=='endpoint' else _user(value)
        ident=uuid.uuid4().hex
        with (self._db(write=True) if _transaction is None else nullcontext(_transaction)) as db:
            if not db.execute('SELECT 1 FROM units WHERE pbx=? AND id=?',(self.pbx,unit_id)).fetchone():raise ValueError('unknown_unit')
            # An endpoint has exactly one owner at any instant. Memberships
            # may overlap across units, but not duplicate in the same unit.
            unit_clause='' if column=='endpoint' else ' AND unit_id=?'
            args=[self.pbx,value]+([] if column=='endpoint' else [unit_id])+[end,start]
            overlap=db.execute('SELECT 1 FROM '+table+' WHERE pbx=? AND '+column+'=?'+unit_clause+
                               ' AND (? IS NULL OR starts<?) AND (ends IS NULL OR ends>?)',
                               (*args[:-2],end,end,start)).fetchone()
            if overlap:raise ScopeConflict('unit_interval_overlap')
            db.execute('INSERT INTO '+table+' VALUES(?,?,?,?,?,?)',(self.pbx,ident,unit_id,value,start,end));self._audit_change(db,actor,'assign' if column=='endpoint' else 'member',ident);self._bump(db)
        return ident

    def assign_endpoint(self,unit_id,endpoint,start,end=None,*,actor=None):return self._interval('unit_assignments',unit_id,endpoint,start,end,actor)
    def add_member(self,unit_id,username,start,end=None,*,actor=None):return self._interval('unit_members',unit_id,username,start,end,actor)

    def assign_queue(self,unit_id,queue,start,end=None,*,actor=None,_transaction=None):
        _id(unit_id);start=_time(start);end=None if end is None else _time(end)
        if not isinstance(queue,str) or not _QUEUE.fullmatch(queue) or end is not None and end<=start:raise ValueError('invalid_unit_queue')
        ident=uuid.uuid4().hex
        with (self._db(write=True) if _transaction is None else nullcontext(_transaction)) as db:
            if not db.execute('SELECT 1 FROM units WHERE pbx=? AND id=?',(self.pbx,unit_id)).fetchone():raise ValueError('unknown_unit')
            if db.execute('SELECT 1 FROM unit_queue_assignments WHERE pbx=? AND queue=? AND (? IS NULL OR starts<?) AND (ends IS NULL OR ends>?)',
                          (self.pbx,queue,end,end,start)).fetchone():raise ScopeConflict('unit_queue_overlap')
            db.execute('INSERT INTO unit_queue_assignments VALUES(?,?,?,?,?,?)',(self.pbx,ident,unit_id,queue,start,end))
            self._audit_change(db,actor,'assign_queue',ident);self._bump(db)
        return ident

    def close_queue(self,ident,end,*,actor=None):
        _id(ident);end=_time(end)
        with self._db(write=True) as db:
            row=db.execute('SELECT starts,ends FROM unit_queue_assignments WHERE pbx=? AND id=?',(self.pbx,ident)).fetchone()
            if not row or row['ends'] is not None or end<=row['starts']:raise ScopeConflict('unit_interval_cannot_close')
            db.execute('UPDATE unit_queue_assignments SET ends=? WHERE pbx=? AND id=?',(end,self.pbx,ident))
            self._audit_change(db,actor,'close_queue',ident);self._bump(db)

    def resolve_queues(self,username,capability,start,end):
        scope=self.resolve(username,capability,start,end);units=scope['units'];rows=[]
        with self._db() as db:
            db.execute('BEGIN')
            revision=db.execute('SELECT revision FROM unit_meta WHERE pbx=?',(self.pbx,)).fetchone()
            if not revision or revision[0]!=scope['revision']:raise ScopeConflict('unit_scope_changed')
            if units:
                rows=[dict(row) for row in db.execute('SELECT unit_id,queue,starts,ends FROM unit_queue_assignments WHERE pbx=? AND unit_id IN ('+','.join('?' for _ in units)+') AND starts<? AND (ends IS NULL OR ends>?) ORDER BY queue,starts LIMIT ?',
                        (self.pbx,*units,end,start,MAX_SCOPE_ASSIGNMENTS+1))]
                if len(rows)>MAX_SCOPE_ASSIGNMENTS:raise ScopeUnavailable('unit_scope_limit')
            db.commit()
        return dict(scope,queue_assignments=rows)

    def close_interval(self,ident,end,*,membership=False,actor=None):
        _id(ident);end=_time(end);table='unit_members' if membership else 'unit_assignments'
        with self._db(write=True) as db:
            row=db.execute('SELECT starts,ends FROM '+table+' WHERE pbx=? AND id=?',(self.pbx,ident)).fetchone()
            if not row or row['ends'] is not None or end<=row['starts']:raise ScopeConflict('unit_interval_cannot_close')
            db.execute('UPDATE '+table+' SET ends=? WHERE pbx=? AND id=?',(end,self.pbx,ident));self._audit_change(db,actor,'close',ident);self._bump(db)

    def grant(self,username,unit_id,capability,*,descendants=False,actor=None,_transaction=None):
        _user(username);_id(unit_id)
        if capability not in CAPABILITIES or type(descendants) is not bool:raise ValueError('invalid_unit_capability')
        ident=uuid.uuid4().hex
        with (self._db(write=True) if _transaction is None else nullcontext(_transaction)) as db:
            if not db.execute('SELECT 1 FROM units WHERE pbx=? AND id=?',(self.pbx,unit_id)).fetchone():raise ValueError('unknown_unit')
            db.execute('INSERT INTO unit_grants VALUES(?,?,?,?,?,?,1)',(self.pbx,ident,unit_id,username,capability,int(descendants)));self._audit_change(db,actor,'grant',ident);self._bump(db)
        return ident

    def configure_access(self, *, username, unit_id, new_unit, endpoint, queue,
                         start, end, capabilities, descendants=False, actor=None):
        """Create or select a unit, attach scope and grant access in one transaction."""
        _user(username)
        if (not isinstance(capabilities,list) or not 1<=len(capabilities)<=len(CAPABILITIES)
                or any(not isinstance(capability,str) or capability not in CAPABILITIES
                       for capability in capabilities) or type(descendants) is not bool):
            raise ValueError('invalid_unit_capability')
        if (unit_id is None)==(new_unit is None):
            raise ValueError('select_one_unit')
        if new_unit is not None and (not isinstance(new_unit,dict) or
                                     set(new_unit)!={'name','kind','parent'}):
            raise ValueError('invalid_unit_request')
        if new_unit is not None:
            if new_unit['kind'] not in KINDS:raise ValueError('invalid_unit_kind')
            if new_unit['parent'] is not None:_id(new_unit['parent'])
        with self._db(write=True) as db:
            if new_unit is not None:
                if db.execute('SELECT 1 FROM units WHERE pbx=? AND parent IS ? AND kind=? AND name=?',
                              (self.pbx,new_unit['parent'],new_unit['kind'],_name(new_unit['name']))).fetchone():
                    raise ScopeConflict('unit_already_exists')
                unit_id=self.create_unit(**new_unit,actor=actor,_transaction=db)
            _id(unit_id)
            start=_time(start)
            end=None if end is None else _time(end)
            if end is not None and end<=start:
                raise ValueError('invalid_unit_interval')
            if endpoint is not None and not db.execute('''SELECT 1 FROM unit_assignments
                WHERE pbx=? AND unit_id=? AND endpoint=? AND starts=? AND ends IS ?''',
                (self.pbx,unit_id,_endpoint(endpoint),start,end)).fetchone():
                self._interval('unit_assignments',unit_id,endpoint,start,end,actor,_transaction=db)
            if queue is not None and not db.execute('''SELECT 1 FROM unit_queue_assignments
                WHERE pbx=? AND unit_id=? AND queue=? AND starts=? AND ends IS ?''',
                (self.pbx,unit_id,queue,start,end)).fetchone():
                self.assign_queue(unit_id,queue,start,end,actor=actor,_transaction=db)
            covered=db.execute('''SELECT 1 FROM unit_members WHERE pbx=? AND unit_id=? AND username=?
                AND starts<=? AND (ends IS NULL OR (? IS NOT NULL AND ends>=?))''',
                (self.pbx,unit_id,username,start,end,end)).fetchone()
            if not covered:
                self._interval('unit_members',unit_id,username,start,end,actor,_transaction=db)
            for capability in dict.fromkeys(capabilities):
                existing=db.execute('''SELECT 1 FROM unit_grants WHERE pbx=? AND unit_id=? AND username=?
                    AND capability=? AND descendants=? AND active=1''',
                    (self.pbx,unit_id,username,capability,int(descendants))).fetchone()
                if not existing:
                    self.grant(username,unit_id,capability,descendants=descendants,actor=actor,_transaction=db)
        return unit_id

    def revoke(self,ident,*,actor=None):
        _id(ident)
        with self._db(write=True) as db:
            if db.execute('UPDATE unit_grants SET active=0 WHERE pbx=? AND id=? AND active=1',(self.pbx,ident)).rowcount!=1:raise ScopeConflict('unit_grant_not_active')
            self._audit_change(db,actor,'revoke',ident);self._bump(db)

    def revoke_subject(self,username):
        """Invalidate organizational grants before a local identity is deleted."""
        _user(username)
        with self._db(write=True) as db:
            db.execute('UPDATE unit_grants SET active=0 WHERE pbx=? AND username=? AND active=1',(self.pbx,username))
            db.execute('DELETE FROM unit_members WHERE pbx=? AND username=?',(self.pbx,username))
            db.execute('DELETE FROM unit_cursors WHERE pbx=? AND username=?',(self.pbx,username))
            db.execute('DELETE FROM unit_recording_refs WHERE pbx=? AND username=?',(self.pbx,username))
            db.execute('UPDATE unit_api_tokens SET active=0 WHERE pbx=? AND username=?',(self.pbx,username))
            self._bump(db)

    def issue_token(self,username,days):
        _user(username)
        if type(days) is not int or not 1<=days<=90:raise ValueError('invalid_token_lifetime')
        now=time.time();secret=secrets.token_urlsafe(32);ident=uuid.uuid4().hex
        digest=hashlib.sha256(secret.encode('ascii')).hexdigest()
        with self._db(write=True) as db:
            if db.execute('SELECT COUNT(*) FROM unit_api_tokens WHERE pbx=? AND username=? AND active=1 AND expires>?',
                          (self.pbx,username,now)).fetchone()[0]>=10:raise ScopeConflict('unit_token_limit')
            db.execute('INSERT INTO unit_api_tokens VALUES(?,?,?,?,?,?,1)',(self.pbx,ident,username,digest,now,now+days*86400))
        return dict(id=ident,token=secret,expires=now+days*86400)

    def list_tokens(self,username):
        _user(username)
        with self._db() as db:
            rows=db.execute('SELECT id,created,expires FROM unit_api_tokens WHERE pbx=? AND username=? AND active=1 AND expires>? ORDER BY created DESC LIMIT 10',
                            (self.pbx,username,time.time())).fetchall()
        return [dict(row) for row in rows]

    def revoke_token(self,username,ident):
        _user(username);_id(ident)
        with self._db(write=True) as db:
            if db.execute('UPDATE unit_api_tokens SET active=0 WHERE pbx=? AND username=? AND id=? AND active=1',
                          (self.pbx,username,ident)).rowcount!=1:raise ScopeConflict('unit_token_not_active')
            self._bump(db)

    def authenticate_token(self,token,*,consume=False):
        if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):return None
        digest=hashlib.sha256(token.encode('ascii')).hexdigest();now=time.time()
        with self._db(write=consume) as db:
            row=db.execute('SELECT id,username,expires FROM unit_api_tokens WHERE pbx=? AND digest=? AND active=1 AND expires>?',
                           (self.pbx,digest,now)).fetchone()
            if not row:return None
            if consume:
                db.execute('DELETE FROM unit_api_usage WHERE pbx=? AND at<=?',(self.pbx,now-60))
                counts=db.execute('SELECT COUNT(*),SUM(token_id=?) FROM unit_api_usage WHERE pbx=?',(row['id'],self.pbx)).fetchone()
                if counts[0]>=5000 or (counts[1] or 0)>=120:
                    raise ScopeConflict('unit_token_rate_limit')
                db.execute('INSERT INTO unit_api_usage VALUES(?,?,?)',(self.pbx,row['id'],now))
            return dict(row)

    def audit_api(self,username,token_id,dataset,status):
        """Record bounded access metadata, never credentials, filters or data."""
        _user(username);_id(token_id)
        if dataset not in ('summary','queues','queue-visits','cdr','trend','export.csv','export.xlsx','export.pdf','recording_play','recording_download') or type(status) is not int or not 100<=status<=599:
            raise ValueError('invalid_unit_audit')
        with self._db(write=True) as db:
            if db.execute('SELECT COUNT(*) FROM unit_api_audit WHERE pbx=?',(self.pbx,)).fetchone()[0]>=100000:
                raise ScopeUnavailable('unit_audit_limit')
            db.execute('INSERT INTO unit_api_audit VALUES(?,?,?,?,?,?,?)',
                       (self.pbx,uuid.uuid4().hex,time.time(),username,token_id,dataset,status))

    def list_api_audit(self,limit=100):
        if type(limit) is not int or not 1<=limit<=500:raise ValueError('invalid_unit_audit_limit')
        with self._db() as db:
            rows=db.execute('SELECT id,at,username,token_id,dataset,status FROM unit_api_audit WHERE pbx=? ORDER BY at DESC,id DESC LIMIT ?',
                            (self.pbx,limit)).fetchall()
        return [dict(row) for row in rows]

    def resolve(self,username,capability,start,end):
        """Return explicit permitted unit/endpoint intervals and revision.

        Endpoint and timestamp matching is left to a fail-closed consumer;
        a membership alone does not grant access. Half-open intervals prevent
        attribution to two units at the exact handover instant.
        """
        _user(username);start=_time(start);end=_time(end)
        if capability not in CAPABILITIES or end<=start:raise ValueError('invalid_unit_scope')
        with self._db() as db:
            db.execute('BEGIN')
            revision=db.execute('SELECT revision FROM unit_meta WHERE pbx=?',(self.pbx,)).fetchone()
            if not revision:raise ScopeUnavailable('unit_scope_uninitialized')
            units=db.execute('''WITH RECURSIVE allowed(id,expand) AS (
              SELECT unit_id,descendants FROM unit_grants WHERE pbx=? AND username=? AND capability=? AND active=1
              UNION SELECT u.id,a.expand FROM units u JOIN allowed a ON u.parent=a.id WHERE u.pbx=? AND a.expand=1)
              SELECT DISTINCT id FROM allowed ORDER BY id LIMIT ?''',(self.pbx,username,capability,self.pbx,MAX_SCOPE_UNITS+1)).fetchall()
            identifiers=tuple(row['id'] for row in units)
            if len(identifiers)>MAX_SCOPE_UNITS:raise ScopeUnavailable('unit_scope_limit')
            rows=[]
            if identifiers:
                sql='SELECT unit_id,endpoint,starts,ends FROM unit_assignments WHERE pbx=? AND unit_id IN ('+','.join('?'*len(identifiers))+') AND starts<? AND (ends IS NULL OR ends>?) ORDER BY endpoint,starts LIMIT ?'
                rows=[dict(row) for row in db.execute(sql,(self.pbx,*identifiers,end,start,MAX_SCOPE_ASSIGNMENTS+1))]
                if len(rows)>MAX_SCOPE_ASSIGNMENTS:raise ScopeUnavailable('unit_scope_limit')
            db.commit()
        return dict(revision=revision[0],units=identifiers,assignments=rows,capability=capability,start=start,end=end)

    def still_current(self,scope):
        return isinstance(scope,dict) and type(scope.get('revision')) is int and self.revision()==scope['revision']

    def save_cursor(self,username,scope,query_hash,cursor):
        _user(username)
        if (not isinstance(query_hash,str) or not re.fullmatch('[0-9a-f]{64}',query_hash) or
            not isinstance(cursor,(tuple,list)) or len(cursor)!=2 or not isinstance(cursor[1],str) or
            not 1<=len(cursor[1])<=512):raise ValueError('invalid_unit_cursor')
        stamp=_time(cursor[0]);now=time.time();token=secrets.token_urlsafe(32)
        with self._db(write=True) as db:
            revision=db.execute('SELECT revision FROM unit_meta WHERE pbx=?',(self.pbx,)).fetchone()
            if not revision or revision[0]!=scope.get('revision'):raise ScopeConflict('unit_scope_changed')
            db.execute('DELETE FROM unit_cursors WHERE pbx=? AND expires<=?',(self.pbx,now))
            if db.execute('SELECT COUNT(*) FROM unit_cursors WHERE pbx=?',(self.pbx,)).fetchone()[0]>=5000:
                raise ScopeUnavailable('unit_cursor_limit')
            db.execute('INSERT INTO unit_cursors VALUES(?,?,?,?,?,?,?,?)',
                (self.pbx,token,username,revision[0],query_hash,stamp,cursor[1],now+900))
        return token

    def load_cursor(self,username,scope,query_hash,token):
        _user(username)
        if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):raise ValueError('invalid_unit_cursor')
        with self._db() as db:
            row=db.execute('SELECT stamp,source_key FROM unit_cursors WHERE pbx=? AND token=? AND username=? '
                'AND revision=? AND query_hash=? AND expires>?',
                (self.pbx,token,username,scope.get('revision'),query_hash,time.time())).fetchone()
        if not row:raise ScopeConflict('unit_cursor_invalid_or_expired')
        return (row['stamp'],row['source_key'])

    def issue_recording_refs(self,username,scope,rows):
        _user(username)
        if not isinstance(rows,list) or len(rows)>100:raise ValueError('invalid_unit_recording_refs')
        now=time.time();issued=[]
        with self._db(write=True) as db:
            revision=db.execute('SELECT revision FROM unit_meta WHERE pbx=?',(self.pbx,)).fetchone()
            if not revision or revision[0]!=scope.get('revision'):raise ScopeConflict('unit_scope_changed')
            db.execute('DELETE FROM unit_recording_refs WHERE pbx=? AND expires<=?',(self.pbx,now))
            for key,stamp in rows:
                if not isinstance(key,str) or not 1<=len(key)<=512:raise ValueError('invalid_unit_recording_ref')
                stamp=_time(stamp)
                existing=db.execute('SELECT token FROM unit_recording_refs WHERE pbx=? AND username=? AND revision=? AND source_key=? AND stamp=? AND expires>? LIMIT 1',
                                    (self.pbx,username,revision[0],key,stamp,now)).fetchone()
                if existing:issued.append(existing['token']);continue
                total,owned=db.execute('SELECT COUNT(*),SUM(username=?) FROM unit_recording_refs WHERE pbx=?',(username,self.pbx)).fetchone()
                if total>=5000 or (owned or 0)>=500:raise ScopeUnavailable('unit_recording_refs_limit')
                token=secrets.token_urlsafe(32)
                db.execute('INSERT INTO unit_recording_refs VALUES(?,?,?,?,?,?,?)',(self.pbx,token,username,revision[0],key,stamp,now+900))
                issued.append(token)
        return issued

    def load_recording_ref(self,username,token):
        _user(username)
        if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):raise ValueError('invalid_unit_recording_ref')
        with self._db() as db:
            row=db.execute('''SELECT r.source_key,r.stamp,r.revision FROM unit_recording_refs r JOIN unit_meta m ON m.pbx=r.pbx AND m.revision=r.revision
              WHERE r.pbx=? AND r.username=? AND r.token=? AND r.expires>?''',(self.pbx,username,token,time.time())).fetchone()
        if not row:raise ScopeConflict('unit_recording_ref_invalid_or_expired')
        return dict(row)

    def consume_ai_budget(self,username,scope):
        """Shared hourly bounds count attempts, including provider failures."""
        _user(username);now=time.time()
        with self._db(write=True) as db:
            revision=db.execute('SELECT revision FROM unit_meta WHERE pbx=?',(self.pbx,)).fetchone()
            if not revision or revision[0]!=scope.get('revision'):raise ScopeConflict('unit_scope_changed')
            db.execute('DELETE FROM unit_ai_usage WHERE pbx=? AND at<=?',(self.pbx,now-3600))
            counts=db.execute('SELECT COUNT(*),SUM(username=?) FROM unit_ai_usage WHERE pbx=?',
                              (username,self.pbx)).fetchone()
            if counts[0]>=200 or (counts[1] or 0)>=20:raise ScopeConflict('unit_ai_hourly_limit')
            db.execute('INSERT INTO unit_ai_usage VALUES(?,?,?)',(self.pbx,username,now))
