"""Bounded private incident storage, never a raw SIP/audio/log payload store.

The caller authenticates and derives scope from trusted current grants. Scope is
not an authorization token. Human descriptions/notes may contain personal data;
they stay private and must never be copied to operational logs. Source evidence
is a generation/event reference, not a copied channel, phone or packet payload.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import time
import uuid

KINDS=('one_way_audio','unexpected_disconnect','short_after_answer','short_after_transfer','media_quality','source_health')
SEVERITIES=('info','warning','critical')
CONFIDENCE=('suspected','observed','unknown')
STATES=('open','acknowledged','resolved','needs_review')
ACTIONS=('acknowledge','resolve','reopen','comment')
SOURCES=('cel','cdr','queue_log','rtcp','collector')
REASONS=('unknown','short_duration','hangup_evidence','sip_error','q850_cause','rtcp_threshold','collector_gap','source_unavailable','manual_report')
MAX_BATCH=100
STARTUP_SECONDS=5
WRITE_SECONDS=1
ID=re.compile(r'(?:[a-f0-9]{32}|[a-f0-9]{64})\Z')
TOKEN=re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,47}\Z')


class Unavailable(RuntimeError):pass
class Conflict(RuntimeError):pass


def _id(value):
    if not isinstance(value,str) or not ID.fullmatch(value):raise ValueError('invalid_diagnostic_id')
    return value


def _token(value):
    if not isinstance(value,str) or not TOKEN.fullmatch(value):raise ValueError('invalid_diagnostic_token')
    return value


def _generation(value):
    return value if isinstance(value,str) and ID.fullmatch(value) else _token(value)


def _binding(value,cursor):
    keys={'generation','archive_identity','anchor','projection_version'}
    if not isinstance(value,dict) or set(value)-keys-{'cursor'} or not keys.issubset(value):raise ValueError('invalid_diagnostic_binding')
    if 'cursor' in value and value['cursor']!=cursor:raise Conflict('diagnostic_checkpoint_conflict')
    identity=value['archive_identity'];anchor=value['anchor']
    if not isinstance(identity,str) or not re.fullmatch('[a-f0-9]{64}',identity):raise ValueError('invalid_diagnostic_binding')
    if anchor is not None and (not isinstance(anchor,str) or not re.fullmatch('[a-f0-9]{64}',anchor)):raise ValueError('invalid_diagnostic_binding')
    if cursor>0 and anchor is None:raise ValueError('diagnostic_anchor_required')
    return dict(generation=_generation(value['generation']),archive_identity=identity,anchor=anchor,projection_version=_integer(value['projection_version'],1,100000))


def _time(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=32503680000:raise ValueError('invalid_diagnostic_time')
    return float(value)


def _integer(value,minimum,maximum):
    if type(value) is not int or not minimum<=value<=maximum:raise ValueError('invalid_diagnostic_integer')
    return value


def _text(value,maximum):
    if not isinstance(value,str) or len(value)>maximum or any(ord(c)<32 and c not in '\n\t' for c in value):raise ValueError('invalid_diagnostic_text')
    return value


def _queues(value):
    # Archive queue IDs are exact values, not AMI/dialplan command fragments.
    # Preserve legitimate Unicode names without rewriting their identity.
    if not isinstance(value,(list,tuple)) or len(value)>256 or any(not isinstance(q,str) or not 1<=len(q)<=128 or not q.isprintable() for q in value):raise ValueError('invalid_diagnostic_queues')
    return tuple(sorted(set(value)))


def _rule_parameters(value):
    if value is None:return None
    if not isinstance(value,dict) or set(value)!={'threshold_seconds'}:raise ValueError('invalid_diagnostic_rule_parameters')
    threshold=value['threshold_seconds']
    if isinstance(threshold,bool) or not isinstance(threshold,(int,float)) or not math.isfinite(threshold) or not 0<threshold<=60:raise ValueError('invalid_diagnostic_rule_parameters')
    return dict(threshold_seconds=float(threshold))


def _enum(value,allowed):
    if not isinstance(value,str) or value not in allowed:raise ValueError('invalid_diagnostic_enum')
    return value


@dataclass(frozen=True)
class Scope:
    queues:tuple=()
    actor:str=None
    own_only:bool=False
    pbx_admin:bool=False


class Store:
    def __init__(self,path,*,pbx='primary',read_seconds=.5,min_free_bytes=64*1024*1024):
        self.path=Path(path).absolute();self.pbx=_token(pbx)
        if isinstance(read_seconds,bool) or not isinstance(read_seconds,(int,float)) or not math.isfinite(read_seconds) or not .001<=read_seconds<=2:raise ValueError('invalid_diagnostic_deadline')
        self.read_seconds=float(read_seconds);self.min_free_bytes=_integer(min_free_bytes,0,2**40)

    def initialize(self):
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        if self.path.is_symlink():raise Unavailable('diagnostics_storage_unavailable')
        if shutil.disk_usage(self.path.parent).free<self.min_free_bytes:raise Unavailable('diagnostics_disk_pressure')
        fd=os.open(self.path,os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0),0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):raise Unavailable('diagnostics_storage_unavailable')
            if os.name!='nt':os.fchmod(fd,0o600)
        finally:os.close(fd)
        with self._db(write=True,initialize=True) as db:
            names={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if names and 'diagnostic_meta' not in names:raise Unavailable('diagnostics_wrong_database')
            if 'diagnostic_meta' in names:
                versions=[row[0] for row in db.execute('SELECT version FROM diagnostic_meta')]
                if versions and versions!=[1]:raise Unavailable('diagnostics_schema_unsupported')
            db.commit()
            if db.execute('PRAGMA journal_mode=WAL').fetchone()[0].lower()!='wal':raise Unavailable('diagnostics_wal_unavailable')
            db.execute('PRAGMA wal_autocheckpoint=256');db.execute('PRAGMA journal_size_limit=8388608')
            db.executescript('''
              CREATE TABLE IF NOT EXISTS diagnostic_meta(version INTEGER PRIMARY KEY);
              CREATE TABLE IF NOT EXISTS diagnostic_incidents(
                pbx TEXT NOT NULL,id TEXT NOT NULL,kind TEXT NOT NULL,severity TEXT NOT NULL,
                confidence TEXT NOT NULL,status TEXT NOT NULL,reporter TEXT,visit_id TEXT,
                description TEXT NOT NULL,first_seen REAL NOT NULL,last_seen REAL NOT NULL,
                created REAL NOT NULL,updated REAL NOT NULL,version INTEGER NOT NULL,
                queue_count INTEGER NOT NULL,evidence_count INTEGER NOT NULL,PRIMARY KEY(pbx,id));
              CREATE INDEX IF NOT EXISTS di_page ON diagnostic_incidents(pbx,created DESC,id DESC);
              CREATE INDEX IF NOT EXISTS di_owner ON diagnostic_incidents(pbx,reporter,created DESC,id DESC);
              CREATE INDEX IF NOT EXISTS di_status ON diagnostic_incidents(pbx,status,created DESC,id DESC);
              CREATE TABLE IF NOT EXISTS diagnostic_queues(pbx TEXT NOT NULL,incident_id TEXT NOT NULL,queue TEXT NOT NULL,PRIMARY KEY(pbx,incident_id,queue));
              CREATE INDEX IF NOT EXISTS dq_queue ON diagnostic_queues(pbx,queue,incident_id);
              CREATE TABLE IF NOT EXISTS diagnostic_policy(pbx TEXT NOT NULL,incident_id TEXT NOT NULL,threshold_seconds REAL NOT NULL,PRIMARY KEY(pbx,incident_id));
              CREATE TRIGGER IF NOT EXISTS dp_immutable_update BEFORE UPDATE ON diagnostic_policy BEGIN SELECT RAISE(ABORT,'immutable');END;
              CREATE TRIGGER IF NOT EXISTS dp_immutable_delete BEFORE DELETE ON diagnostic_policy BEGIN SELECT RAISE(ABORT,'immutable');END;
              CREATE TABLE IF NOT EXISTS diagnostic_evidence(
                pbx TEXT NOT NULL,incident_id TEXT NOT NULL,generation TEXT NOT NULL,event_id INTEGER NOT NULL,
                source TEXT NOT NULL,rule TEXT NOT NULL,rule_version INTEGER NOT NULL,
                occurred_at REAL NOT NULL,reason TEXT NOT NULL,sip_status INTEGER,q850_cause INTEGER,
                fingerprint TEXT NOT NULL,PRIMARY KEY(pbx,generation,event_id,source,rule,rule_version));
              CREATE INDEX IF NOT EXISTS de_incident ON diagnostic_evidence(pbx,incident_id,occurred_at,event_id);
              CREATE TABLE IF NOT EXISTS diagnostic_actions(
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,pbx TEXT NOT NULL,incident_id TEXT NOT NULL,
                actor TEXT NOT NULL,action TEXT NOT NULL,note TEXT NOT NULL,created REAL NOT NULL,
                incident_version INTEGER NOT NULL);
              CREATE INDEX IF NOT EXISTS da_incident ON diagnostic_actions(pbx,incident_id,sequence);
              CREATE TRIGGER IF NOT EXISTS da_immutable_update BEFORE UPDATE ON diagnostic_actions BEGIN SELECT RAISE(ABORT,'immutable');END;
              CREATE TRIGGER IF NOT EXISTS da_immutable_delete BEFORE DELETE ON diagnostic_actions BEGIN SELECT RAISE(ABORT,'immutable');END;
              CREATE TRIGGER IF NOT EXISTS de_immutable_update BEFORE UPDATE ON diagnostic_evidence BEGIN SELECT RAISE(ABORT,'immutable');END;
              CREATE TRIGGER IF NOT EXISTS de_immutable_delete BEFORE DELETE ON diagnostic_evidence BEGIN SELECT RAISE(ABORT,'immutable');END;
              CREATE TABLE IF NOT EXISTS diagnostic_checkpoints(pbx TEXT NOT NULL,name TEXT NOT NULL,cursor INTEGER NOT NULL,updated REAL NOT NULL,PRIMARY KEY(pbx,name));
              CREATE TABLE IF NOT EXISTS diagnostic_worker_bindings(pbx TEXT NOT NULL,name TEXT NOT NULL,generation TEXT NOT NULL,archive_identity TEXT NOT NULL,anchor TEXT,projection_version INTEGER NOT NULL,PRIMARY KEY(pbx,name));
            ''')
            versions=[row[0] for row in db.execute('SELECT version FROM diagnostic_meta')]
            if not versions:db.execute('INSERT INTO diagnostic_meta VALUES(1)')
            elif versions!=[1]:raise Unavailable('diagnostics_schema_unsupported')

    @contextmanager
    def _db(self,*,write=False,initialize=False):
        db=None
        try:
            if self.path.is_symlink() or not self.path.is_file():raise Unavailable('diagnostics_storage_unavailable')
            if os.name!='nt' and self.path.stat().st_mode&0o077:raise Unavailable('diagnostics_storage_permissions')
            if write and shutil.disk_usage(self.path.parent).free<self.min_free_bytes:raise Unavailable('diagnostics_disk_pressure')
            db=sqlite3.connect(self.path.as_uri()+('?mode=rw' if write else '?mode=ro'),uri=True,timeout=.25)
            db.row_factory=sqlite3.Row;db.execute('PRAGMA trusted_schema=OFF');db.execute('PRAGMA cache_size=-1024')
            # Explicit startup may create multiple tables/indexes under cold
            # disk or concurrent CI load. Keep that separate from online writes
            # and short readers; schema setup is never performed by get/page.
            deadline=time.monotonic()+(STARTUP_SECONDS if initialize else WRITE_SECONDS if write else self.read_seconds)
            db.set_progress_handler(lambda:int(time.monotonic()>deadline),100)
            if not initialize:
                if write:db.execute('PRAGMA synchronous=FULL');db.execute('BEGIN IMMEDIATE')
                else:db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
                version=db.execute('SELECT version FROM diagnostic_meta').fetchone()
                if version is None or version[0]!=1:raise Unavailable('diagnostics_schema_unsupported')
            with db:yield db
        except sqlite3.Error as error:
            # sqlite_errorcode is available on newer Python versions. The exact
            # legacy SQLite message fallback keeps Python 3.10 compatible and
            # never includes SQL, user text or private paths in the public code.
            if getattr(error,'sqlite_errorcode',None)==getattr(sqlite3,'SQLITE_INTERRUPT',9) or str(error).lower()=='interrupted':
                raise Unavailable('diagnostics_query_deadline') from None
            raise Unavailable('diagnostics_storage_unavailable') from None
        except OSError:raise Unavailable('diagnostics_storage_unavailable') from None
        finally:
            if db is not None:db.close()

    def _visible(self,scope):
        if not isinstance(scope,Scope) or type(scope.own_only) is not bool or type(scope.pbx_admin) is not bool:raise ValueError('invalid_diagnostic_scope')
        queues=_queues(scope.queues)
        if scope.actor is not None:_id(scope.actor)
        if scope.own_only and scope.actor is None:raise ValueError('diagnostic_actor_required')
        clause='i.pbx=?';args=[self.pbx]
        if not scope.pbx_admin:
            if not queues:raise PermissionError('diagnostic_queue_scope_required')
            clause+=' AND i.queue_count>0 AND NOT EXISTS (SELECT 1 FROM diagnostic_queues q WHERE q.pbx=i.pbx AND q.incident_id=i.id AND q.queue NOT IN ('+','.join('?' for _ in queues)+'))'
            args+=list(queues)
        if scope.own_only:clause+=' AND i.reporter=?';args.append(scope.actor)
        return clause,args

    def _row(self,db,row,*,detail=False):
        if row is None:return None
        value=dict(row);value.pop('pbx');value['queues']=[r[0] for r in db.execute('SELECT queue FROM diagnostic_queues WHERE pbx=? AND incident_id=? ORDER BY queue',(self.pbx,row['id']))]
        policy=db.execute('SELECT threshold_seconds FROM diagnostic_policy WHERE pbx=? AND incident_id=?',(self.pbx,row['id'])).fetchone()
        value['rule_parameters']=dict(threshold_seconds=policy[0]) if policy else None
        if detail:
            evidence=[dict(r) for r in db.execute('SELECT generation,event_id,source,rule,rule_version,occurred_at,reason,sip_status,q850_cause FROM diagnostic_evidence WHERE pbx=? AND incident_id=? ORDER BY occurred_at DESC,event_id DESC LIMIT 101',(self.pbx,row['id']))]
            actions=[dict(r) for r in db.execute('SELECT sequence,actor,action,note,created,incident_version FROM diagnostic_actions WHERE pbx=? AND incident_id=? ORDER BY sequence DESC LIMIT 101',(self.pbx,row['id']))]
            value.update(evidence=evidence[:100],evidence_limited=len(evidence)>100,actions=actions[:100],actions_limited=len(actions)>100)
        return value

    def get(self,ident,scope):
        ident=_id(ident);clause,args=self._visible(scope)
        with self._db() as db:return self._row(db,db.execute('SELECT i.* FROM diagnostic_incidents i WHERE '+clause+' AND i.id=?',(*args,ident)).fetchone(),detail=True)

    def page(self,scope,*,before=None,limit=50,kind=None,status=None,start=None,end=None):
        limit=_integer(limit,1,100);clause,args=self._visible(scope)
        for key,value,allowed in [('kind',kind,KINDS),('status',status,STATES)]:
            if value is not None:clause+=' AND i.'+key+'=?';args.append(_enum(value,allowed))
        if start is not None:clause+=' AND i.created>=?';args.append(_time(start))
        if end is not None:clause+=' AND i.created<?';args.append(_time(end))
        if start is not None and end is not None and end<=start:raise ValueError('invalid_diagnostic_range')
        if before is not None:
            if not isinstance(before,(list,tuple)) or len(before)!=2:raise ValueError('invalid_diagnostic_cursor')
            stamp,ident=_time(before[0]),_id(before[1]);clause+=' AND (i.created<? OR (i.created=? AND i.id<?))';args+=[stamp,stamp,ident]
        with self._db() as db:
            rows=db.execute('SELECT i.* FROM diagnostic_incidents i WHERE '+clause+' ORDER BY i.created DESC,i.id DESC LIMIT ?',(*args,limit+1)).fetchall()
            more=len(rows)>limit;rows=rows[:limit];values=[self._row(db,row) for row in rows]
        return dict(rows=values,next=[rows[-1]['created'],rows[-1]['id']] if more else None)

    def create_manual(self,kind,queues,reporter,occurred_at,*,description='',visit_id=None,now=None):
        kind=_enum(kind,KINDS);queues=_queues(queues);reporter=_id(reporter);occurred_at=_time(occurred_at);description=_text(description,1000)
        if visit_id is not None and (not isinstance(visit_id,str) or not re.fullmatch('[a-f0-9]{64}',visit_id)):raise ValueError('invalid_diagnostic_visit')
        if kind=='source_health' and queues:raise ValueError('diagnostic_source_health_is_global')
        now=_time(time.time() if now is None else now);ident=uuid.uuid4().hex
        with self._db(write=True) as db:
            db.execute('INSERT INTO diagnostic_incidents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(self.pbx,ident,kind,'warning','suspected','open',reporter,visit_id,description,occurred_at,occurred_at,now,now,1,len(queues),0))
            db.executemany('INSERT INTO diagnostic_queues VALUES(?,?,?)',[(self.pbx,ident,q) for q in queues])
            db.execute('INSERT INTO diagnostic_actions(pbx,incident_id,actor,action,note,created,incident_version) VALUES(?,?,?,?,?,?,?)',(self.pbx,ident,reporter,'created','',now,1))
            return self._row(db,db.execute('SELECT * FROM diagnostic_incidents WHERE pbx=? AND id=?',(self.pbx,ident)).fetchone(),detail=True)

    def add_action(self,ident,scope,actor,action,*,note='',expected_version=None,now=None):
        ident=_id(ident);actor=_id(actor);action=_enum(action,ACTIONS);note=_text(note,2000);clause,args=self._visible(scope)
        if scope.own_only and scope.actor!=actor:raise PermissionError('diagnostic_actor_mismatch')
        if scope.own_only and action!='comment':raise PermissionError('diagnostic_case_manager_required')
        if expected_version is not None:_integer(expected_version,1,2**53)
        now=_time(time.time() if now is None else now)
        with self._db(write=True) as db:
            row=db.execute('SELECT i.* FROM diagnostic_incidents i WHERE '+clause+' AND i.id=?',(*args,ident)).fetchone()
            if row is None:return None
            if expected_version is not None and row['version']!=expected_version:raise Conflict('diagnostic_version_conflict')
            status={'acknowledge':'acknowledged','resolve':'resolved','reopen':'open'}.get(action,row['status']);version=row['version']+1
            db.execute('INSERT INTO diagnostic_actions(pbx,incident_id,actor,action,note,created,incident_version) VALUES(?,?,?,?,?,?,?)',(self.pbx,ident,actor,action,note,now,version))
            db.execute('UPDATE diagnostic_incidents SET status=?,updated=?,version=? WHERE pbx=? AND id=?',(status,now,version,self.pbx,ident))
            return self._row(db,db.execute('SELECT * FROM diagnostic_incidents WHERE pbx=? AND id=?',(self.pbx,ident)).fetchone(),detail=True)

    def checkpoint(self,name):
        name=_token(name)
        with self._db() as db:
            row=db.execute('SELECT cursor FROM diagnostic_checkpoints WHERE pbx=? AND name=?',(self.pbx,name)).fetchone()
            return row[0] if row else 0

    def worker_checkpoint(self,name):
        name=_token(name)
        with self._db() as db:
            row=db.execute('SELECT c.cursor,b.generation,b.archive_identity,b.anchor,b.projection_version FROM diagnostic_checkpoints c LEFT JOIN diagnostic_worker_bindings b ON b.pbx=c.pbx AND b.name=c.name WHERE c.pbx=? AND c.name=?',(self.pbx,name)).fetchone()
            return dict(row) if row else dict(cursor=0,generation=None,archive_identity=None,anchor=None,projection_version=None)

    def ingest_batch(self,name,expected_cursor,next_cursor,observations,*,binding=None,expected_binding=None,review_incidents=None,now=None):
        """CAS cursor and append evidence/incident updates in one transaction.

        Each observation is a strict dict; unknown fields, raw payloads and
        changing an incident's type/scope are rejected before commit.
        """
        name=_token(name);_integer(expected_cursor,0,2**53);_integer(next_cursor,expected_cursor,2**53)
        if not isinstance(observations,list) or len(observations)>MAX_BATCH:raise ValueError('diagnostic_batch_limit')
        if review_incidents is None:review_incidents=[]
        if not isinstance(review_incidents,list) or len(review_incidents)>MAX_BATCH:raise ValueError('diagnostic_batch_limit')
        review_incidents=tuple(dict.fromkeys(_id(ident) for ident in review_incidents))
        if binding is not None:binding=_binding(binding,next_cursor)
        if expected_binding is not None:expected_binding=_binding(expected_binding,expected_cursor)
        now=_time(time.time() if now is None else now);prepared=[]
        keys={'incident_id','kind','queues','generation','event_id','source','rule','rule_version','occurred_at','reason','severity','confidence','sip_status','q850_cause','visit_id','rule_parameters'}
        for value in observations:
            if not isinstance(value,dict) or set(value)-keys:raise ValueError('invalid_diagnostic_observation')
            row=dict(incident_id=_id(value.get('incident_id')),kind=_enum(value.get('kind'),KINDS),queues=_queues(value.get('queues')),generation=_generation(value.get('generation')),
                event_id=_integer(value.get('event_id'),1,2**53),source=_enum(value.get('source'),SOURCES),rule=_token(value.get('rule')),rule_version=_integer(value.get('rule_version'),1,100000),
                occurred_at=_time(value.get('occurred_at')),reason=_enum(value.get('reason','unknown'),REASONS),severity=_enum(value.get('severity','warning'),SEVERITIES),confidence=_enum(value.get('confidence','suspected'),CONFIDENCE))
            row['visit_id']=value.get('visit_id')
            row['rule_parameters']=_rule_parameters(value.get('rule_parameters'))
            if row['visit_id'] is not None and (not isinstance(row['visit_id'],str) or not re.fullmatch('[a-f0-9]{64}',row['visit_id'])):raise ValueError('invalid_diagnostic_visit')
            for key,maximum in [('sip_status',699),('q850_cause',127)]:row[key]=None if value.get(key) is None else _integer(value[key],100 if key=='sip_status' else 1,maximum)
            if row['kind']=='source_health' and row['queues']:raise ValueError('diagnostic_source_health_is_global')
            if row['event_id']>next_cursor:raise ValueError('diagnostic_evidence_after_cursor')
            if row['confidence']!='suspected':raise ValueError('diagnostic_machine_findings_are_suspected')
            row['fingerprint']=hashlib.sha256(json.dumps(row,sort_keys=True,separators=(',',':')).encode()).hexdigest();prepared.append(row)
        inserted=0
        with self._db(write=True) as db:
            prior=db.execute('SELECT cursor FROM diagnostic_checkpoints WHERE pbx=? AND name=?',(self.pbx,name)).fetchone();cursor=prior[0] if prior else 0
            if cursor!=expected_cursor:raise Conflict('diagnostic_checkpoint_conflict')
            current=db.execute('SELECT generation,archive_identity,anchor,projection_version FROM diagnostic_worker_bindings WHERE pbx=? AND name=?',(self.pbx,name)).fetchone()
            if current is not None:
                if binding is None or expected_binding!=dict(current):raise Conflict('diagnostic_binding_conflict')
                if any(binding[key]!=current[key] for key in ('generation','archive_identity','projection_version')):raise Conflict('diagnostic_source_changed')
            elif expected_binding is not None:raise Conflict('diagnostic_binding_conflict')
            elif cursor and binding is not None:raise Conflict('diagnostic_unbound_checkpoint_requires_review')
            if binding is not None and any(row['generation']!=binding['generation'] for row in prepared):raise ValueError('diagnostic_generation_mismatch')
            for row in prepared:
                evidence_key=(self.pbx,row['generation'],row['event_id'],row['source'],row['rule'],row['rule_version'])
                old=db.execute('SELECT fingerprint FROM diagnostic_evidence WHERE pbx=? AND generation=? AND event_id=? AND source=? AND rule=? AND rule_version=?',evidence_key).fetchone()
                if old:
                    if old[0]!=row['fingerprint']:raise Conflict('diagnostic_evidence_conflict')
                    continue
                if row['event_id']<=expected_cursor:raise Conflict('diagnostic_cursor_evidence_conflict')
                incident=db.execute('SELECT * FROM diagnostic_incidents WHERE pbx=? AND id=?',(self.pbx,row['incident_id'])).fetchone()
                if incident:
                    scope=tuple(r[0] for r in db.execute('SELECT queue FROM diagnostic_queues WHERE pbx=? AND incident_id=? ORDER BY queue',(self.pbx,row['incident_id'])))
                    if incident['reporter'] is not None or scope!=row['queues'] or incident['kind']!=row['kind'] or incident['visit_id']!=row['visit_id']:raise Conflict('diagnostic_incident_scope_conflict')
                    policy=db.execute('SELECT threshold_seconds FROM diagnostic_policy WHERE pbx=? AND incident_id=?',(self.pbx,row['incident_id'])).fetchone()
                    old_parameters=dict(threshold_seconds=policy[0]) if policy else None
                    if old_parameters!=row['rule_parameters']:raise Conflict('diagnostic_rule_policy_conflict')
                else:
                    db.execute('INSERT INTO diagnostic_incidents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(self.pbx,row['incident_id'],row['kind'],row['severity'],row['confidence'],'needs_review',None,row['visit_id'],'',row['occurred_at'],row['occurred_at'],now,now,1,len(row['queues']),0))
                    db.executemany('INSERT INTO diagnostic_queues VALUES(?,?,?)',[(self.pbx,row['incident_id'],q) for q in row['queues']])
                    if row['rule_parameters'] is not None:db.execute('INSERT INTO diagnostic_policy VALUES(?,?,?)',(self.pbx,row['incident_id'],row['rule_parameters']['threshold_seconds']))
                db.execute('INSERT INTO diagnostic_evidence VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(self.pbx,row['incident_id'],row['generation'],row['event_id'],row['source'],row['rule'],row['rule_version'],row['occurred_at'],row['reason'],row['sip_status'],row['q850_cause'],row['fingerprint']))
                db.execute('UPDATE diagnostic_incidents SET first_seen=MIN(first_seen,?),last_seen=MAX(last_seen,?),updated=?,evidence_count=evidence_count+1,version=version+? WHERE pbx=? AND id=?',(row['occurred_at'],row['occurred_at'],now,1 if incident else 0,self.pbx,row['incident_id']));inserted+=1
            worker_actor=hashlib.sha256(('diagnostic-worker:'+self.pbx+':'+name).encode()).hexdigest()
            for ident in review_incidents:
                incident=db.execute('SELECT version,status,reporter FROM diagnostic_incidents WHERE pbx=? AND id=?',(self.pbx,ident)).fetchone()
                if incident is None or incident['reporter'] is not None:raise Conflict('diagnostic_review_target_unavailable')
                if incident['status']=='needs_review':continue
                version=incident['version']+1
                db.execute('UPDATE diagnostic_incidents SET status=?,version=?,updated=? WHERE pbx=? AND id=?',('needs_review',version,now,self.pbx,ident))
                db.execute('INSERT INTO diagnostic_actions(pbx,incident_id,actor,action,note,created,incident_version) VALUES(?,?,?,?,?,?,?)',(self.pbx,ident,worker_actor,'source_review','',now,version))
            db.execute('INSERT INTO diagnostic_checkpoints VALUES(?,?,?,?) ON CONFLICT(pbx,name) DO UPDATE SET cursor=excluded.cursor,updated=excluded.updated',(self.pbx,name,next_cursor,now))
            if binding is not None:db.execute('INSERT INTO diagnostic_worker_bindings VALUES(?,?,?,?,?,?) ON CONFLICT(pbx,name) DO UPDATE SET anchor=excluded.anchor',(self.pbx,name,binding['generation'],binding['archive_identity'],binding['anchor'],binding['projection_version']))
        return dict(inserted=inserted,cursor=next_cursor)
