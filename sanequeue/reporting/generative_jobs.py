"""Separate private text-analysis queue using the existing durable lease engine.

Never instantiate this over ai-jobs.sqlite3: ASR results stay immutable there.
Only source IDs and hashes, not a second transcript copy, enter immutable specs.
"""
import hashlib
import sqlite3
import time
import uuid
from .ai_jobs import AIJobs,AIConflict,AIUnavailable,_id,_text,_opaque,_json
from .text_generation import transcript,validate_result,PROMPT_VERSION


class GenerativeJobs(AIJobs):
    def initialize(self):
        if self.path.is_symlink():raise AIUnavailable('analysis_store_invalid')
        if self.path.exists() and self.path.stat().st_size:
            db=sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,timeout=.25)
            try:
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='generative_meta'").fetchone() is None or db.execute('SELECT version FROM generative_meta LIMIT 1').fetchone()!=(1,):raise AIUnavailable('analysis_store_invalid')
            finally:db.close()
        super().initialize()
        with self._db(write=True) as db:
            db.execute('CREATE TABLE IF NOT EXISTS generative_meta(version INTEGER PRIMARY KEY)')
            db.execute('INSERT OR IGNORE INTO generative_meta VALUES(1)')
    @staticmethod
    def _public(row,worker=False):
        job=AIJobs._public(row,worker)
        if job is not None and job['spec'].get('kind')!='generative_text_analysis':raise AIUnavailable('analysis_store_invalid')
        return job
    def create(self,owner,source,queues,language,request_key):
        owner=_text(owner,128,'owner');request_key=_text(request_key,128,'request_key');_id(source['id'])
        prepared=transcript(source);original=source['spec']
        if original['owner']!=owner or original['pbx']!=self.pbx or language not in ('fa','en'):raise ValueError('invalid_generative_source')
        if not isinstance(queues,(tuple,list)) or not 1<=len(queues)<=256:raise ValueError('invalid_generative_scope')
        queues=sorted(set(_text(q,128,'queue') for q in queues))
        if not set(original.get('queues',[original['queue']])).issubset(queues):raise ValueError('invalid_generative_scope')
        spec=dict(kind='generative_text_analysis',owner=owner,pbx=self.pbx,source_job_id=source['id'],
            source_spec_sha256=prepared['spec_sha256'],transcript_sha256=prepared['sha256'],
            visit_id=_opaque(original['visit_id'],'visit_id'),recording_id=_opaque(original['recording_id'],'recording_id'),
            queue=original['queue'],queues=queues,language=language,prompt_version=PROMPT_VERSION)
        payload=_json(spec);digest=hashlib.sha256(payload.encode()).hexdigest();now=time.time()
        with self._db(write=True) as db:
            prior=db.execute('SELECT * FROM ai_jobs WHERE pbx=? AND owner=? AND request_key=?',(self.pbx,owner,request_key)).fetchone()
            if prior:
                if prior['spec_hash']!=digest:raise AIConflict('ai_request_key_reused')
                return self._public(prior)
            counts=db.execute("SELECT COUNT(*),COALESCE(SUM(owner=?),0) FROM ai_jobs WHERE state IN ('queued','running')",(owner,)).fetchone()
            if counts[0]>=10 or counts[1]>=3:raise AIConflict('ai_job_quota')
            ident=uuid.uuid4().hex
            db.execute('''INSERT INTO ai_jobs(id,pbx,owner,state,spec,spec_hash,request_key,created,updated,available_at)
                VALUES(?,?,?,'queued',?,?,?,?,?,?)''',(ident,self.pbx,owner,payload,digest,request_key,now,now,now))
            return self._public(db.execute('SELECT * FROM ai_jobs WHERE id=?',(ident,)).fetchone())
    def complete(self,ident,worker,result):
        _id(ident);_text(worker,128,'worker');now=time.time()
        with self._db(write=True) as db:
            row=db.execute("SELECT * FROM ai_jobs WHERE pbx=? AND id=? AND state='running' AND worker=? AND lease_until>=?",(self.pbx,ident,worker,now)).fetchone()
            if row is None:return False
            job=self._public(row);validate_result(result,job['spec']);payload=_json(result)
            return db.execute("UPDATE ai_jobs SET state='completed',result=?,progress=100,error=NULL,worker=NULL,lease_until=NULL,updated=? WHERE id=?",(payload,now,ident)).rowcount==1
    def list(self,owner,limit=20,source_job_id=None):
        owner=_text(owner,128,'owner')
        if type(limit) is not int or not 1<=limit<=100:raise ValueError('invalid_analysis_limit')
        clause='pbx=? AND owner=?';args=[self.pbx,owner]
        if source_job_id is not None:
            _id(source_job_id);clause+=" AND json_extract(spec,'$.source_job_id')=?";args.append(source_job_id)
        with self._db() as db:
            rows=db.execute('SELECT id,state,created,updated,attempts,progress,error,spec,spec_hash,NULL result FROM ai_jobs WHERE '+clause+' ORDER BY sequence DESC LIMIT ?',[*args,limit])
            return [self._public(row) for row in rows]
