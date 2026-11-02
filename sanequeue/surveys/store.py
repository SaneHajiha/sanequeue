"""Immutable survey versions and replay-safe, bounded DTMF sessions."""
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import time
import uuid

KEY=re.compile(r'[a-z][a-z0-9_]{0,31}\Z')
ID=re.compile(r'[a-f0-9]{32}\Z')
TERMINAL={'completed','no_response','partial','abandoned','declined','expired'}


def _text(value,maximum):
    if not isinstance(value,str) or not 1<=len(value.strip())<=maximum or not value.isprintable():raise ValueError('invalid_survey_text')
    return value.strip()


def validate_form(value, prompts):
    if not isinstance(value,dict):raise ValueError('invalid_survey_form')
    title=_text(value.get('title'),100);questions=value.get('questions')
    if not isinstance(questions,list) or not 1<=len(questions)<=5:raise ValueError('survey_requires_1_to_5_questions')
    keys=[q.get('id') if isinstance(q,dict) else None for q in questions]
    if any(not isinstance(k,str) or not KEY.fullmatch(k) for k in keys) or len(set(keys))!=len(keys):raise ValueError('invalid_survey_question_id')
    cleaned=[]
    for index,question in enumerate(questions):
        prompt=question.get('prompt');options=question.get('options');timeout=question.get('timeout_seconds',5);attempts=question.get('attempts',1)
        if not isinstance(prompt,str) or prompt not in prompts:raise ValueError('unapproved_survey_prompt')
        if type(timeout) is not int or not 3<=timeout<=10 or type(attempts) is not int or not 1<=attempts<=2:raise ValueError('invalid_survey_wait_budget')
        if not isinstance(options,dict) or not 2<=len(options)<=10:raise ValueError('invalid_survey_options')
        output={}
        for digit,option in options.items():
            if not isinstance(digit,str) or not re.fullmatch('[0-9]',digit) or not isinstance(option,dict):raise ValueError('invalid_survey_digit')
            target=option.get('next',keys[index+1] if index+1<len(keys) else 'end')
            if target!='end' and target not in keys[index+1:]:raise ValueError('survey_branch_must_move_forward')
            output[digit]=dict(label=_text(option.get('label'),80),next=target)
        cleaned.append(dict(id=keys[index],label=_text(question.get('label'),160),prompt=prompt,options=output,timeout_seconds=timeout,attempts=attempts))
    score=value.get('csat_question');positive=value.get('csat_satisfied')
    if score not in keys or not isinstance(positive,list) or not 1<=len(positive)<=10 or any(not isinstance(d,str) for d in positive) or len(set(positive))!=len(positive) or any(d not in cleaned[keys.index(score)]['options'] for d in positive):raise ValueError('invalid_csat_definition')
    reached={keys[0]}
    for question in cleaned:
        if question['id'] not in reached:raise ValueError('unreachable_survey_question')
        reached.update(o['next'] for o in question['options'].values())
    return dict(title=title,questions=cleaned,csat_question=score,csat_satisfied=positive)


class SurveyStore:
    def __init__(self,state):self.state=Path(state);self.path=self.state/'surveys.sqlite3'
    @contextmanager
    def db(self,*,write=False):
        if self.state.is_symlink() or self.path.is_symlink():raise ValueError('unsafe_survey_store')
        self.state.mkdir(parents=True,exist_ok=True)
        if write and shutil.disk_usage(self.state).free<256*1024*1024:raise ValueError('survey_low_disk')
        db=sqlite3.connect(self.path,timeout=.25);db.row_factory=sqlite3.Row
        deadline=time.monotonic()+.5;db.set_progress_handler(lambda:int(time.monotonic()>deadline),1000)
        try:
            db.execute('PRAGMA trusted_schema=OFF')
            with db:
                if write:db.execute('BEGIN IMMEDIATE')
                yield db
        finally:db.close()
    def initialize(self):
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS forms(id TEXT NOT NULL,version INTEGER NOT NULL,payload TEXT NOT NULL,actor TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(id,version));
CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,proof TEXT NOT NULL UNIQUE,form_id TEXT NOT NULL,version INTEGER NOT NULL,queue TEXT NOT NULL,agent TEXT NOT NULL,evidence TEXT NOT NULL,form TEXT NOT NULL,started REAL NOT NULL,expires REAL NOT NULL,state TEXT NOT NULL,question TEXT,attempt INTEGER NOT NULL DEFAULT 0,sequence INTEGER NOT NULL DEFAULT 0,score INTEGER,ended REAL);
CREATE INDEX IF NOT EXISTS survey_scope_time ON sessions(queue,started,id);
CREATE TABLE IF NOT EXISTS answers(session TEXT NOT NULL,sequence INTEGER NOT NULL,payload TEXT NOT NULL,response TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(session,sequence));
CREATE TABLE IF NOT EXISTS survey_meta(id INTEGER PRIMARY KEY CHECK(id=1),sessions INTEGER NOT NULL);
INSERT OR IGNORE INTO survey_meta VALUES(1,0);''')
        if os.name!='nt':os.chmod(self.path,0o600)
    def save_form(self,value,actor,prompts):
        form=validate_form(value,prompts);ident=value.get('id') or uuid.uuid4().hex;expected=value.get('expected_version',0)
        if not isinstance(ident,str) or not ID.fullmatch(ident) or type(expected) is not int or expected<0:raise ValueError('invalid_survey_version')
        with self.db(write=True) as db:
            current=db.execute('SELECT MAX(version) FROM forms WHERE id=?',(ident,)).fetchone()[0] or 0
            if expected!=current:raise ValueError('survey_form_changed_reload')
            if db.execute('SELECT COUNT(*) FROM forms').fetchone()[0]>=1000:raise ValueError('survey_form_capacity')
            db.execute('INSERT INTO forms VALUES(?,?,?,?,?)',(ident,current+1,json.dumps(form,ensure_ascii=False),str(actor)[:100],time.time()))
        return dict(form,id=ident,version=current+1)
    def forms(self):
        with self.db() as db:rows=db.execute('SELECT f.* FROM forms f JOIN (SELECT id,MAX(version) version FROM forms GROUP BY id) v ON f.id=v.id AND f.version=v.version ORDER BY f.created DESC LIMIT 100').fetchall()
        return [dict(json.loads(r['payload']),id=r['id'],version=r['version'],actor=r['actor'],created=r['created']) for r in rows]
    def get_form(self,ident,version):
        with self.db() as db:row=db.execute('SELECT payload FROM forms WHERE id=? AND version=?',(ident,version)).fetchone()
        if row is None:raise ValueError('survey_form_not_found')
        return json.loads(row[0])
    def start(self,binding,evidence,*,now=None):
        now=time.time() if now is None else now
        if (self.state/'module.disabled').exists():raise ValueError('module_disabled')
        required={'queue','agent','caller_uniqueid','visit_proof','source','binding','prompt_map','checked_prompt_hashes'}
        if not isinstance(evidence,dict) or not required.issubset(evidence) or evidence['source']!='queue_log_completeagent' or evidence['queue']!=binding['queue']:raise ValueError('survey_connection_evidence_required')
        if not re.fullmatch('[a-f0-9]{64}',evidence['visit_proof'] or ''):raise ValueError('invalid_survey_proof')
        if any(not isinstance(evidence[k],str) or not 1<=len(evidence[k])<=200 or not evidence[k].isprintable() for k in ('queue','agent','caller_uniqueid')):raise ValueError('invalid_survey_identity')
        if not isinstance(evidence['binding'],str) or not re.fullmatch('[A-Za-z0-9_-]{1,32}',evidence['binding']) or evidence['prompt_map']!=binding['prompts'] or not isinstance(evidence['checked_prompt_hashes'],dict) or set(evidence['checked_prompt_hashes'])!=set(binding['prompts']) or any(not isinstance(v,str) or not re.fullmatch('[a-f0-9]{64}',v) for v in evidence['checked_prompt_hashes'].values()) or len(json.dumps(evidence))>8192:raise ValueError('invalid_survey_prompt_evidence')
        form=self.get_form(binding['form_id'],binding['form_version']);validate_form(form,binding['prompts'])
        with self.db(write=True) as db:
            prior=db.execute('SELECT * FROM sessions WHERE proof=?',(evidence['visit_proof'],)).fetchone()
            if prior:
                if json.loads(prior['evidence'])!=evidence:raise ValueError('survey_evidence_conflict')
                return self._response(prior)
            if db.execute('SELECT sessions FROM survey_meta WHERE id=1').fetchone()[0]>=1000000:raise ValueError('survey_archive_capacity')
            ident=uuid.uuid4().hex
            db.execute('INSERT INTO sessions(id,proof,form_id,version,queue,agent,evidence,form,started,expires,state,question) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(ident,evidence['visit_proof'],binding['form_id'],binding['form_version'],binding['queue'],evidence['agent'],json.dumps(evidence,sort_keys=True),json.dumps(form),now,now+300,'active',form['questions'][0]['id']))
            db.execute('UPDATE survey_meta SET sessions=sessions+1 WHERE id=1')
            return self._response(db.execute('SELECT * FROM sessions WHERE id=?',(ident,)).fetchone())
    @staticmethod
    def _response(row):
        form=json.loads(row['form']);evidence=json.loads(row['evidence']);question=next((q for q in form['questions'] if q['id']==row['question']),None)
        return dict(id=row['id'],state=row['state'],sequence=row['sequence'],question=question,queue=row['queue'],form_id=row['form_id'],version=row['version'],binding=evidence['binding'],prompt_map=evidence['prompt_map'],checked_prompt_hashes=evidence['checked_prompt_hashes'])

    def queues(self):
        with self.db() as db:return [r[0] for r in db.execute('SELECT DISTINCT queue FROM sessions ORDER BY queue LIMIT 101')]

    def detail(self,ident,queues):
        if not isinstance(ident,str) or not ID.fullmatch(ident):raise ValueError('invalid_survey_session')
        with self.db() as db:
            row=db.execute('SELECT * FROM sessions WHERE id=?',(ident,)).fetchone()
            if row is None or row['queue'] not in queues:raise PermissionError('survey_not_in_scope')
            answers=[dict(r) for r in db.execute('SELECT sequence,payload,created,response FROM answers WHERE session=? ORDER BY sequence LIMIT 11',(ident,))]
        return dict(id=ident,queue=row['queue'],agent=row['agent'],evidence=json.loads(row['evidence']),form=json.loads(row['form']),state=row['state'],answers=[dict(sequence=r['sequence'],value=r['payload'],created=r['created'],accepted=json.loads(r['response']).get('accepted',False)) for r in answers])
    def answer(self,ident,sequence,value,*,caller_uniqueid,now=None):
        now=time.time() if now is None else now
        if not isinstance(ident,str) or not ID.fullmatch(ident) or type(sequence) is not int or not 0<=sequence<=10 or not isinstance(value,str) or value not in ('timeout','hangup','*') and not re.fullmatch('[0-9]',value):raise ValueError('invalid_survey_answer')
        with self.db(write=True) as db:
            row=db.execute('SELECT * FROM sessions WHERE id=?',(ident,)).fetchone()
            if row is None or json.loads(row['evidence'])['caller_uniqueid']!=caller_uniqueid:raise PermissionError('survey_session_not_owned')
            previous=db.execute('SELECT * FROM answers WHERE session=? AND sequence=?',(ident,sequence)).fetchone()
            if previous:
                if previous['payload']!=value:raise ValueError('survey_answer_replay_conflict')
                return json.loads(previous['response'])
            if sequence!=row['sequence']:raise ValueError('survey_answer_out_of_order')
            if row['state']!='active':return self._response(row)
            form=json.loads(row['form']);question=next(q for q in form['questions'] if q['id']==row['question'])
            # Only validated option answers count toward partial completion.
            valid_count=sum(bool(json.loads(r[0]).get('accepted')) for r in db.execute('SELECT response FROM answers WHERE session=? ORDER BY sequence LIMIT 11',(ident,)))
            state='active';target=row['question'];attempt=row['attempt'];score=row['score'];accepted=False
            if now>=row['expires']:state='expired'
            elif value=='hangup':state='partial' if valid_count else 'abandoned'
            elif value=='*':state='declined'
            elif value in question['options']:
                accepted=True;attempt=0;next_question=question['options'][value]['next']
                if question['id']==form['csat_question']:score=int(value in form['csat_satisfied'])
                if next_question=='end':state='completed';target=None
                else:target=next_question
            else:
                attempt+=1
                if attempt>=question['attempts']:state='partial' if valid_count else 'no_response'
            db.execute('UPDATE sessions SET state=?,question=?,attempt=?,sequence=sequence+1,score=?,ended=? WHERE id=?',(state,target,attempt,score,now if state!='active' else None,ident))
            response=self._response(db.execute('SELECT * FROM sessions WHERE id=?',(ident,)).fetchone());response['accepted']=accepted
            db.execute('INSERT INTO answers VALUES(?,?,?,?,?)',(ident,sequence,value,json.dumps(response),now))
            return response
    def report(self,queues,start,end,*,limit=100,before=None):
        if not queues:return dict(rows=[],summary=dict(offered=0,csat_numerator=0,csat_denominator=0,csat_percent=None))
        if len(queues)>100 or not all(isinstance(q,str) and re.fullmatch('[A-Za-z0-9_-]{1,32}',q) for q in queues):raise ValueError('invalid_survey_scope')
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in (start,end)) or not 0<end-start<=31*86400:raise ValueError('survey_range_max_31_days')
        if type(limit) is not int or not 1<=limit<=100:raise ValueError('invalid_survey_limit')
        where='queue IN ('+','.join('?' for _ in queues)+') AND started>=? AND started<?';params=(*queues,start,end)
        with self.db() as db:
            totals=db.execute('SELECT COUNT(*) offered,COUNT(score) denominator,COALESCE(SUM(score),0) numerator FROM sessions WHERE '+where,params).fetchone()
            # Refuse an unbounded analytics response; query has a hard deadline.
            if totals['offered']>50000:raise ValueError('survey_range_too_large')
            page_where=where;page_params=params
            if before:
                if not isinstance(before,str) or not ID.fullmatch(before):raise ValueError('invalid_survey_cursor')
                cursor=db.execute('SELECT started FROM sessions WHERE id=? AND '+where,(before,*params)).fetchone()
                if cursor is None:raise ValueError('invalid_survey_cursor')
                page_where+=' AND (started<? OR (started=? AND id<?))';page_params+= (cursor['started'],cursor['started'],before)
            rows=db.execute('SELECT id,queue,agent,form_id,version,started,expires,state,score,sequence,ended FROM sessions WHERE '+page_where+' ORDER BY started DESC,id DESC LIMIT ?',(*page_params,limit)).fetchall()
        output=[dict(row) for row in rows]
        for row in output:
            if row['state']=='active' and row['expires']<=time.time():row['state']='expired'
        return dict(rows=output,next_before=output[-1]['id'] if len(output)==limit else None,summary=dict(offered=totals['offered'],csat_numerator=totals['numerator'],csat_denominator=totals['denominator'],csat_percent=100*totals['numerator']/totals['denominator'] if totals['denominator'] else None))
