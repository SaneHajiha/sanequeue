"""Private manual voice feedback. No PBX intake, path handling or transcoding."""
from contextlib import contextmanager
import hashlib
import io
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
import wave

MAX_BYTES=1024*1024
STATES=('new','reviewing','followup','resolved','discarded')
ID=re.compile(r'[a-f0-9]{32}\Z')

class Conflict(RuntimeError):pass
class Unavailable(RuntimeError):pass

def text(value,limit):
    if not isinstance(value,str) or not 1<=len(value)<=limit or not value.strip() or not value.isprintable():raise ValueError('invalid_voice_feedback_text')
    return value

def pcm(data):
    if not isinstance(data,bytes) or not 44<=len(data)<=MAX_BYTES:raise ValueError('voice_feedback_size_limit')
    if data[:4]!=b'RIFF' or data[8:12]!=b'WAVE' or int.from_bytes(data[4:8],'little')!=len(data)-8:raise ValueError('invalid_voice_feedback_wav')
    try:
        with wave.open(io.BytesIO(data),'rb') as sound:
            frames=sound.getnframes()
            if sound.getcomptype()!='NONE' or sound.getnchannels()!=1 or sound.getsampwidth()!=2 or sound.getframerate()!=8000 or not 1<=frames<=480000:raise ValueError('voice_feedback_requires_pcm_8khz_mono_60s')
            if len(sound.readframes(frames))!=frames*2:raise ValueError('truncated_voice_feedback_wav')
            return frames/8000
    except (wave.Error,EOFError):raise ValueError('invalid_voice_feedback_wav') from None

class VoiceFeedback:
    def __init__(self,state):
        self.directory=Path(state).absolute()/'voice-feedback';self.path=self.directory/'feedback.sqlite3'
    def initialize(self):
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        if self.directory.is_symlink() or self.path.is_symlink():raise Unavailable('voice_feedback_storage_unavailable')
        meta=self.directory.stat()
        if os.name!='nt' and (meta.st_mode&0o077 or meta.st_uid!=os.geteuid()):raise Unavailable('voice_feedback_storage_permissions')
        fd=os.open(self.path,os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0),0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):raise Unavailable('voice_feedback_storage_unavailable')
            if os.name!='nt':os.fchmod(fd,0o600)
        finally:os.close(fd)
        with self.db(True) as db:
            db.commit();db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''CREATE TABLE IF NOT EXISTS feedback(
              id TEXT PRIMARY KEY,queue TEXT NOT NULL,uploader TEXT NOT NULL,request_key TEXT NOT NULL,
              fingerprint TEXT NOT NULL,evidence TEXT NOT NULL,created REAL NOT NULL,
              duration REAL NOT NULL,size INTEGER NOT NULL,sha256 TEXT NOT NULL,audio BLOB NOT NULL,
              status TEXT NOT NULL,assignee TEXT NOT NULL,note TEXT NOT NULL,followup_at REAL,
              version INTEGER NOT NULL,updated REAL NOT NULL,UNIQUE(uploader,request_key));
              CREATE INDEX IF NOT EXISTS vf_queue ON feedback(queue,created DESC,id DESC);
              CREATE TABLE IF NOT EXISTS voice_audit(sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                feedback TEXT NOT NULL,actor TEXT NOT NULL,action TEXT NOT NULL,created REAL NOT NULL,detail TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS va_feedback ON voice_audit(feedback,sequence DESC);
              CREATE TRIGGER IF NOT EXISTS vf_evidence_immutable BEFORE UPDATE OF id,queue,uploader,request_key,fingerprint,evidence,created,duration,size,sha256,audio ON feedback BEGIN SELECT RAISE(ABORT,'immutable');END;''')
    @contextmanager
    def db(self,write=False):
        if self.directory.is_symlink() or self.path.is_symlink() or not self.path.is_file():raise Unavailable('voice_feedback_storage_unavailable')
        if os.name!='nt' and (self.directory.stat().st_mode&0o077 or self.path.stat().st_mode&0o077):raise Unavailable('voice_feedback_storage_permissions')
        if write and shutil.disk_usage(self.directory).free<256*1024*1024:raise Unavailable('voice_feedback_low_disk')
        db=sqlite3.connect(self.path.as_uri()+('?mode=rw' if write else '?mode=ro'),uri=True,timeout=.1);db.row_factory=sqlite3.Row
        deadline=time.monotonic()+.5;db.set_progress_handler(lambda:int(time.monotonic()>=deadline),100)
        try:
            db.execute('PRAGMA trusted_schema=OFF');db.execute('PRAGMA cache_size=-2048')
            if write:db.execute('PRAGMA synchronous=FULL');db.execute('BEGIN IMMEDIATE')
            with db:yield db
        finally:db.close()
    @staticmethod
    def public(row):
        if row is None:raise FileNotFoundError()
        result=dict(row);result['evidence']=json.loads(result['evidence']);return result
    @staticmethod
    def columns():return 'id,queue,uploader,evidence,created,duration,size,status,assignee,note,followup_at,version,updated'
    @staticmethod
    def audit(db,ident,actor,action,detail=None):
        if db.execute('SELECT COUNT(*) FROM voice_audit').fetchone()[0]>=1000000:raise Unavailable('voice_feedback_audit_limit')
        db.execute('INSERT INTO voice_audit(feedback,actor,action,created,detail) VALUES(?,?,?,?,?)',(ident,text(actor,128),action,time.time(),json.dumps(detail or {},ensure_ascii=False)))
    def intake(self,data,queue,owner,key,*,survey=None):
        duration=pcm(data);queue=text(queue,128);owner=text(owner,128)
        if not isinstance(key,str) or not re.fullmatch('[A-Za-z0-9_.:-]{1,100}',key):raise ValueError('invalid_voice_feedback_request_key')
        evidence={'source':'manual_authorized_upload','uploader':owner,'queue':queue,'caller_ownership_verified':False}
        if survey is not None:
            if survey['queue']!=queue:raise PermissionError('voice_feedback_survey_queue_mismatch')
            evidence.update(survey_session=survey['id'],agent=survey['agent'],association='manual_attachment_to_existing_survey')
        digest=hashlib.sha256(data).hexdigest();encoded=json.dumps(evidence,sort_keys=True,ensure_ascii=False)
        fingerprint=hashlib.sha256((digest+encoded).encode()).hexdigest();ident=uuid.uuid4().hex;now=time.time()
        with self.db(True) as db:
            prior=db.execute('SELECT id,fingerprint FROM feedback WHERE uploader=? AND request_key=?',(owner,key)).fetchone()
            if prior:
                if prior['fingerprint']!=fingerprint:raise Conflict('voice_feedback_request_conflict')
                return self.public(db.execute('SELECT '+self.columns()+' FROM feedback WHERE id=?',(prior['id'],)).fetchone()),False
            count,size=db.execute('SELECT COUNT(*),COALESCE(SUM(size),0) FROM feedback').fetchone()
            if count>=1000 or size+len(data)>256*1024*1024:raise Unavailable('voice_feedback_storage_quota')
            db.execute('INSERT INTO feedback VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(ident,queue,owner,key,fingerprint,encoded,now,duration,len(data),digest,data,'new','','',None,1,now))
            self.audit(db,ident,owner,'intake',{'source':evidence['source']})
            return self.public(db.execute('SELECT '+self.columns()+' FROM feedback WHERE id=?',(ident,)).fetchone()),True
    def detail(self,ident,queues):
        if not isinstance(ident,str) or not ID.fullmatch(ident):raise FileNotFoundError()
        with self.db() as db:row=self.public(db.execute('SELECT '+self.columns()+' FROM feedback WHERE id=?',(ident,)).fetchone())
        if row['queue'] not in queues:raise FileNotFoundError()
        return row
    def report(self,queues,*,status=None,before=None):
        if len(queues)>100 or status is not None and status not in STATES:raise ValueError('invalid_voice_feedback_filter')
        if before is not None and (not isinstance(before,str) or not ID.fullmatch(before)):raise ValueError('invalid_voice_feedback_cursor')
        if not queues:return {'rows':[],'next':None,'counts':{}}
        where='queue IN ('+','.join('?' for _ in queues)+')';args=list(queues)
        with self.db() as db:
            counts={row[0]:row[1] for row in db.execute('SELECT status,COUNT(*) FROM feedback WHERE '+where+' GROUP BY status',args)}
            if status:where+=' AND status=?';args.append(status)
            if before:
                prior=db.execute('SELECT created,id,queue FROM feedback WHERE id=?',(before,)).fetchone()
                if prior is None or prior['queue'] not in queues:raise ValueError('invalid_voice_feedback_cursor')
                where+=' AND (created<? OR (created=? AND id<?))';args.extend((prior['created'],prior['created'],prior['id']))
            rows=[self.public(row) for row in db.execute('SELECT '+self.columns()+' FROM feedback WHERE '+where+' ORDER BY created DESC,id DESC LIMIT 51',args)]
        return dict(rows=rows[:50],next=rows[49]['id'] if len(rows)>50 else None,counts=counts,unit='manually_uploaded_voice_feedback',source_coverage='manual_intake_only')
    def update(self,ident,queues,actor,*,version,status,assignee='',note='',followup_at=None):
        if type(version) is not int or version<1 or status not in STATES:raise ValueError('invalid_voice_feedback_update')
        if not isinstance(assignee,str):raise ValueError('invalid_voice_feedback_assignee')
        if assignee:text(assignee,128)
        if not isinstance(note,str) or len(note)>1000 or any(ord(c)<32 and c not in '\n\t' for c in note):raise ValueError('invalid_voice_feedback_note')
        if followup_at is not None and (isinstance(followup_at,bool) or not isinstance(followup_at,(float,int)) or not math.isfinite(followup_at) or not 0<followup_at<=time.time()+366*86400):raise ValueError('invalid_voice_feedback_followup')
        self.detail(ident,queues)
        with self.db(True) as db:
            changed=db.execute('UPDATE feedback SET status=?,assignee=?,note=?,followup_at=?,version=version+1,updated=? WHERE id=? AND version=?',(status,assignee,note,followup_at,time.time(),ident,version)).rowcount
            if not changed:raise Conflict('voice_feedback_version_conflict')
            self.audit(db,ident,actor,'review_update',dict(version=version+1,status=status,assignee=assignee,note=note,followup_at=followup_at))
        return self.detail(ident,queues)
    def audio(self,ident,queues,actor,action):
        if action not in ('play_request','download_request'):raise ValueError('invalid_voice_feedback_action')
        self.detail(ident,queues)
        with self.db(True) as db:
            row=db.execute('SELECT CASE WHEN length(audio)<=? THEN audio END audio,sha256 FROM feedback WHERE id=?',(MAX_BYTES,ident)).fetchone()
            if row is None or row['audio'] is None:raise Unavailable('voice_feedback_audio_integrity')
            data=bytes(row['audio'])
            if hashlib.sha256(data).hexdigest()!=row['sha256']:raise Unavailable('voice_feedback_audio_integrity')
            pcm(data);self.audit(db,ident,actor,action)
        return data
    def history(self,ident,queues):
        self.detail(ident,queues)
        with self.db() as db:return [dict(row) for row in db.execute('SELECT sequence,actor,action,created,detail FROM voice_audit WHERE feedback=? ORDER BY sequence DESC LIMIT 100',(ident,))]
