"""Private append-only quality reviews and immutable form versions.

HTTP adapters authorize supervisors, visit/recording ownership, note duration,
and CSRF. Queue lists are trusted grants, never caller-supplied role claims.
All labels, comments and notes are plain text: render them with textContent.
No audio paths, phone numbers or PBX operations belong in this store.
"""
import base64
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import struct
import time
import uuid

from .store import QueryDeadline

MAX_GROUPS=1000
_ID=re.compile(r'[0-9a-f]{32}\Z')
_CRITERION=re.compile(r'[A-Za-z0-9_-]{1,64}\Z')


class QualityConflict(RuntimeError):pass
class QualityUnavailable(RuntimeError):pass


def _text(value,maximum,label,empty=False):
    if not isinstance(value,str) or len(value)>maximum or not empty and not value.strip():
        raise ValueError('invalid_quality_'+label)
    if any(ord(char)<32 and char not in '\n\r\t' for char in value):raise ValueError('invalid_quality_'+label)
    return value


def _number(value,maximum,label):
    if isinstance(value,bool) or not isinstance(value,(float,int)):
        raise ValueError('invalid_quality_'+label)
    try:valid=math.isfinite(value) and 0<=value<=maximum
    except OverflowError:valid=False
    if not valid:raise ValueError('invalid_quality_'+label)
    return float(value)


def _id(value):
    if not isinstance(value,str) or not _ID.fullmatch(value):raise ValueError('invalid_quality_id')
    return value


def _version(value):
    if isinstance(value,bool) or not isinstance(value,int) or not 1<=value<=2147483647:raise ValueError('invalid_quality_version')
    return value


def _json(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)


def _criteria(values):
    if not isinstance(values,(list,tuple)) or not 1<=len(values)<=100:raise ValueError('invalid_quality_criteria')
    result=[];seen=set()
    for row in values:
        if not isinstance(row,dict) or set(row)!={'id','label','max_score','weight'}:raise ValueError('invalid_quality_criterion')
        ident=row['id']
        if not isinstance(ident,str) or not _CRITERION.fullmatch(ident) or ident in seen:raise ValueError('invalid_quality_criterion_id')
        seen.add(ident)
        maximum=_number(row['max_score'],10000,'max_score');weight=_number(row['weight'],100,'weight')
        if maximum<=0:raise ValueError('invalid_quality_max_score')
        result.append(dict(id=ident,label=_text(row['label'],160,'label'),max_score=maximum,weight=weight))
    if sum(row['weight'] for row in result)<=0:raise ValueError('invalid_quality_weights')
    return result


def _queues(values):
    if not isinstance(values,(list,tuple,set)) or len(values)>256:raise ValueError('invalid_quality_scope')
    return tuple(sorted({_text(queue,128,'queue') for queue in values}))


def _cursor(value):return base64.urlsafe_b64encode(struct.pack('>BQ',1,value)).decode()


def _sequence(value):
    if not isinstance(value,str) or not re.fullmatch('[A-Za-z0-9_-]{12}',value):raise ValueError('invalid_quality_cursor')
    try:version,sequence=struct.unpack('>BQ',base64.b64decode(value,altchars=b'-_',validate=True))
    except (ValueError,struct.error):raise ValueError('invalid_quality_cursor') from None
    if version!=1 or not 0<sequence<=9223372036854775807:raise ValueError('invalid_quality_cursor')
    return sequence


def _limit(value):
    if isinstance(value,bool) or not isinstance(value,int) or value<1:raise ValueError('invalid_quality_limit')
    return min(100,value)


class QualityStore:
    def __init__(self,path,pbx='primary'):
        self.path=Path(path).absolute();self.pbx=_text(pbx,128,'pbx')

    def initialize(self):
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            if self.path.is_symlink():raise OSError('quality_symlink')
            fd=os.open(self.path,os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0),0o600)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):raise OSError('quality_not_regular')
                if os.name!='nt':os.fchmod(fd,0o600)
            finally:os.close(fd)
            with self._db(write=True) as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'").fetchone():raise OSError('quality_is_archive')
                db.commit()
                if db.execute('PRAGMA journal_mode=WAL').fetchone()[0].lower()!='wal':raise OSError('quality_wal_unavailable')
                db.executescript('''CREATE TABLE IF NOT EXISTS quality_forms(
                    pbx TEXT,id TEXT,version INTEGER,name TEXT,criteria TEXT,owner TEXT,created REAL,
                    PRIMARY KEY(pbx,id,version));
                  CREATE TABLE IF NOT EXISTS quality_reviews(
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,pbx TEXT NOT NULL,
                    visit_id TEXT NOT NULL,queue TEXT NOT NULL,reviewer TEXT NOT NULL,form_id TEXT NOT NULL,
                    form_version INTEGER NOT NULL,form_snapshot TEXT NOT NULL,scores TEXT NOT NULL,
                    score REAL NOT NULL,comment TEXT NOT NULL,recording_id TEXT,notes TEXT NOT NULL,
                    recording_queues TEXT NOT NULL DEFAULT '[]',
                    created REAL NOT NULL,request_key TEXT NOT NULL,spec_hash TEXT NOT NULL,
                    UNIQUE(pbx,reviewer,request_key));
                  CREATE INDEX IF NOT EXISTS qr_visit ON quality_reviews(pbx,queue,visit_id,sequence);
                  CREATE INDEX IF NOT EXISTS qr_range ON quality_reviews(pbx,queue,created);
                  CREATE TRIGGER IF NOT EXISTS qf_no_update BEFORE UPDATE ON quality_forms BEGIN SELECT RAISE(ABORT,'immutable_quality_form'); END;
                  CREATE TRIGGER IF NOT EXISTS qf_no_delete BEFORE DELETE ON quality_forms BEGIN SELECT RAISE(ABORT,'immutable_quality_form'); END;
                  CREATE TRIGGER IF NOT EXISTS qr_no_update BEFORE UPDATE ON quality_reviews BEGIN SELECT RAISE(ABORT,'immutable_quality_review'); END;
                  CREATE TRIGGER IF NOT EXISTS qr_no_delete BEFORE DELETE ON quality_reviews BEGIN SELECT RAISE(ABORT,'immutable_quality_review'); END;''')
                # Constant-default ADD COLUMN does not rewrite historical rows
                # or fire the append-only UPDATE triggers. Empty means unproven.
                columns={row['name'] for row in db.execute('PRAGMA table_info(quality_reviews)')}
                if 'recording_queues' not in columns:
                    db.execute("ALTER TABLE quality_reviews ADD COLUMN recording_queues TEXT NOT NULL DEFAULT '[]'")
        except (OSError,sqlite3.Error):raise QualityUnavailable('quality_store_unavailable') from None

    @contextmanager
    def _db(self,write=False):
        db=None
        try:
            if self.path.is_symlink() or not self.path.is_file():raise OSError('quality_file_missing')
            if os.name!='nt' and self.path.stat().st_mode&0o077:raise OSError('quality_permissions')
            db=sqlite3.connect(self.path.as_uri()+('?mode=rw' if write else '?mode=ro'),uri=True,timeout=.25)
            db.row_factory=sqlite3.Row;db.execute('PRAGMA trusted_schema=OFF')
            if write:db.execute('PRAGMA synchronous=FULL');db.execute('BEGIN IMMEDIATE')
            else:
                deadline=time.monotonic()+.5
                db.set_progress_handler(lambda:int(time.monotonic()>=deadline),100)
                db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
            with db:yield db
        except sqlite3.OperationalError as error:
            if 'interrupt' in str(error).lower():raise QueryDeadline('quality_query_deadline') from None
            raise QualityUnavailable('quality_store_unavailable') from None
        except (OSError,sqlite3.Error):raise QualityUnavailable('quality_store_unavailable') from None
        finally:
            if db is not None:db.close()

    @staticmethod
    def _form(row):
        if row is None:return None
        return dict(id=row['id'],version=row['version'],name=row['name'],criteria=json.loads(row['criteria']),owner=row['owner'],created=row['created'])

    def save_form(self,name,criteria,owner):
        name=_text(name,160,'form_name');criteria=_criteria(criteria);owner=_text(owner,128,'owner')
        ident=uuid.uuid4().hex;now=time.time()
        with self._db(write=True) as db:
            db.execute('INSERT INTO quality_forms VALUES(?,?,?,?,?,?,?)',(self.pbx,ident,1,name,_json(criteria),owner,now))
            return self._form(db.execute('SELECT * FROM quality_forms WHERE pbx=? AND id=?',(self.pbx,ident)).fetchone())

    def revise_form(self,formid,criteria,owner,*,name=None):
        _id(formid);criteria=_criteria(criteria);owner=_text(owner,128,'owner')
        if name is not None:name=_text(name,160,'form_name')
        with self._db(write=True) as db:
            prior=db.execute('SELECT * FROM quality_forms WHERE pbx=? AND id=? ORDER BY version DESC LIMIT 1',(self.pbx,formid)).fetchone()
            if prior is None:return None
            version=_version(prior['version']+1)
            db.execute('INSERT INTO quality_forms VALUES(?,?,?,?,?,?,?)',
                (self.pbx,formid,version,name if name is not None else prior['name'],_json(criteria),owner,time.time()))
            return self._form(db.execute('SELECT * FROM quality_forms WHERE pbx=? AND id=? AND version=?',(self.pbx,formid,version)).fetchone())

    def get_form(self,formid,version=None):
        _id(formid)
        if version is not None:_version(version)
        with self._db() as db:
            return self._form(db.execute('SELECT * FROM quality_forms WHERE pbx=? AND id=?'+
                (' AND version=?' if version is not None else '')+' ORDER BY version DESC LIMIT 1',
                (self.pbx,formid,version) if version is not None else (self.pbx,formid)).fetchone())

    def forms(self,limit=100):
        limit=_limit(limit)
        with self._db() as db:
            rows=db.execute('''SELECT f.* FROM quality_forms f WHERE pbx=? AND version=(
              SELECT MAX(x.version) FROM quality_forms x WHERE x.pbx=f.pbx AND x.id=f.id)
              ORDER BY created DESC,id DESC LIMIT ?''',(self.pbx,limit)).fetchall()
            return [self._form(row) for row in rows]

    @staticmethod
    def _review(row):
        if row is None:return None
        result={key:row[key] for key in ('id','visit_id','queue','reviewer','form_id','form_version','score','comment','recording_id','created')}
        for key in ('form_snapshot','scores','notes','recording_queues'):result[key]=json.loads(row[key])
        return result

    def create_review(self,visit_id,queue,reviewer,formid,formversion,scores,comment,request_key,recording_id=None,notes=None,recording_queues=None):
        visit_id=_text(visit_id,512,'visit_id');queue=_text(queue,128,'queue');reviewer=_text(reviewer,128,'reviewer')
        _id(formid);_version(formversion);comment=_text(comment,4000,'comment',True);request_key=_text(request_key,128,'request_key')
        if recording_id is not None:
            recording_id=_text(recording_id,512,'recording_id')
            if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,512}',recording_id):raise ValueError('invalid_quality_recording_id')
        proof=[] if recording_queues is None else list(_queues(recording_queues))
        if recording_id is None and proof:raise ValueError('quality_recording_scope_without_recording')
        if recording_id is not None and recording_queues is not None and (not proof or queue not in proof):
            raise ValueError('invalid_quality_recording_scope')
        if notes is None:notes=[]
        if not isinstance(notes,(list,tuple)) or len(notes)>100:raise ValueError('invalid_quality_notes')
        clean_notes=[]
        for note in notes:
            if not isinstance(note,dict) or set(note)!={'offset_seconds','text'}:raise ValueError('invalid_quality_note')
            clean_notes.append(dict(offset_seconds=_number(note['offset_seconds'],14400,'note_offset'),text=_text(note['text'],1000,'note_text')))
        if not isinstance(scores,dict):raise ValueError('invalid_quality_scores')
        with self._db(write=True) as db:
            form=self._form(db.execute('SELECT * FROM quality_forms WHERE pbx=? AND id=? AND version=?',(self.pbx,formid,formversion)).fetchone())
            if form is None:raise ValueError('quality_form_not_found')
            if set(scores)!={row['id'] for row in form['criteria']}:raise ValueError('quality_score_criteria_mismatch')
            clean={row['id']:_number(scores[row['id']],row['max_score'],'score') for row in form['criteria']}
            weighted=100*sum(clean[row['id']]/row['max_score']*row['weight'] for row in form['criteria'])/sum(row['weight'] for row in form['criteria'])
            legacy_spec=_json([visit_id,queue,formid,formversion,clean,comment,recording_id,clean_notes])
            spec=_json([visit_id,queue,formid,formversion,clean,comment,recording_id,clean_notes,proof])
            fingerprint=hashlib.sha256(spec.encode()).hexdigest()
            prior=db.execute('SELECT * FROM quality_reviews WHERE pbx=? AND reviewer=? AND request_key=?',(self.pbx,reviewer,request_key)).fetchone()
            if prior:
                legacy_match=not proof and prior['recording_queues']=='[]' and prior['spec_hash']==hashlib.sha256(legacy_spec.encode()).hexdigest()
                if prior['spec_hash']!=fingerprint and not legacy_match:raise QualityConflict('quality_request_key_reused')
                return self._review(prior)
            ident=uuid.uuid4().hex
            db.execute('''INSERT INTO quality_reviews(id,pbx,visit_id,queue,reviewer,form_id,form_version,
              form_snapshot,scores,score,comment,recording_id,notes,recording_queues,created,request_key,spec_hash)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(ident,self.pbx,visit_id,queue,reviewer,formid,formversion,
              _json(form),_json(clean),weighted,comment,recording_id,_json(clean_notes),_json(proof),time.time(),request_key,fingerprint))
            return self._review(db.execute('SELECT * FROM quality_reviews WHERE id=?',(ident,)).fetchone())

    def _clause(self,queues):
        queues=_queues(queues)
        return ('pbx=? AND queue IN ('+','.join('?' for _ in queues)+')',[self.pbx,*queues]) if queues else ('pbx=? AND 0',[self.pbx])

    def page(self,scopequeues,visit_id=None,*,before=None,limit=50):
        clause,args=self._clause(scopequeues);limit=_limit(limit)
        if visit_id is not None:clause+=' AND visit_id=?';args.append(_text(visit_id,512,'visit_id'))
        if before is not None:clause+=' AND sequence<?';args.append(_sequence(before))
        with self._db() as db:
            rows=db.execute('SELECT * FROM quality_reviews WHERE '+clause+' ORDER BY sequence DESC LIMIT ?',(*args,limit+1)).fetchall()
            more=len(rows)>limit;rows=rows[:limit]
            return dict(rows=[self._review(row) for row in rows],next=_cursor(rows[-1]['sequence']) if more and rows else None)

    def get(self,ident,scopequeues):
        _id(ident);clause,args=self._clause(scopequeues)
        with self._db() as db:return self._review(db.execute('SELECT * FROM quality_reviews WHERE '+clause+' AND id=?',(*args,ident)).fetchone())

    def aggregate(self,scopequeues,start,end,*,reviewers=False):
        clause,args=self._clause(scopequeues)
        if not isinstance(reviewers,bool):raise ValueError('invalid_quality_reviewer_groups')
        start,end=float(start),float(end)
        if not all(math.isfinite(value) for value in (start,end)) or start<0 or not 0<end-start<=366*86400:raise ValueError('invalid_quality_range')
        clause+=' AND created>=? AND created<?';args.extend((start,end))
        metrics='COUNT(*) count,COUNT(score) known_score_count,AVG(score) average_score'
        with self._db() as db:
            totals=dict(db.execute('SELECT '+metrics+' FROM quality_reviews WHERE '+clause,args).fetchone())
            groups={};count=0
            for key in ('queue','reviewer') if reviewers else ('queue',):
                rows=[dict(row) for row in db.execute('SELECT '+key+','+metrics+' FROM quality_reviews WHERE '+clause+
                    ' GROUP BY '+key+' ORDER BY '+key+' LIMIT ?',(*args,MAX_GROUPS+1))]
                count+=len(rows)
                if count>MAX_GROUPS:raise QueryDeadline('quality_group_limit_narrow_range')
                groups['queues' if key=='queue' else 'reviewers']=rows
            return dict(start=start,end=end,unit='review',totals=totals,groups_nonadditive=False,**groups)
