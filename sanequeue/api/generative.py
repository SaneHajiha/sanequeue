"""Owner-private generative assistance routes. No inference in HTTP."""
import hashlib
import hmac
import json
import os
import sqlite3
import time
from flask import abort,jsonify,request,session
from flask_login import current_user,login_required
from werkzeug.exceptions import Forbidden,NotFound
from sanequeue.reporting.ai_jobs import AIConflict,AIUnavailable
from sanequeue.reporting.generative_jobs import GenerativeJobs
from sanequeue.reporting.text_generation import transcript,GenerationFailure
from sanequeue.reporting.store import QueryDeadline


def install(app,sources,archive,*,role,sections,can_queue,authorize_source,enabled=None):
    store=GenerativeJobs(archive.path.parent/'generative-jobs.sqlite3',pbx=archive.pbx)
    try:store.initialize();ready=True
    except (OSError,ValueError,sqlite3.Error,AIUnavailable):ready=False
    enabled=enabled or (lambda:os.getenv('SANEQUEUE_TEXT_ANALYSIS_ENABLED')=='1')
    @app.after_request
    def generative_private_headers(response):
        if request.endpoint and request.endpoint.startswith('generative_'):
            response.headers['Cache-Control']='private, no-store';response.headers['X-Content-Type-Options']='nosniff'
        return response
    def owner():
        if not ready:abort(503)
        if role() not in ('admin','supervisor') or not {'reports','audit'}.issubset(sections()):abort(403)
        if request.method=='POST':
            a=session.get('csrf_token');b=request.headers.get('X-CSRF-Token')
            if not isinstance(a,str) or not a or not isinstance(b,str) or not hmac.compare_digest(a,b):abort(403)
        return str(current_user.get_id())
    def body():
        if not request.is_json:abort(415)
        raw=request.stream.read(4097)
        if len(raw)>4096:abort(413)
        value=json.loads(raw)
        if not isinstance(value,dict):raise ValueError()
        return value
    def source_for(ident,actor,*,frozen=None,deadline=None):
        source=sources.get(ident,actor)
        if source is None or source['spec']['pbx']!=archive.pbx:abort(404)
        prepared=transcript(source);spec=source['spec'];proof=authorize_source(spec,deadline=deadline)
        if not isinstance(proof,(tuple,list,set)) or not 1<=len(proof)<=256 or any(not isinstance(q,str) or not 1<=len(q)<=128 or not q.isprintable() for q in proof):abort(403)
        queues=sorted(set(proof)|set(spec.get('queues',[spec['queue']])))
        if frozen is not None:
            if prepared['sha256']!=frozen['transcript_sha256'] or prepared['spec_sha256']!=frozen['source_spec_sha256'] or not set(queues).issubset(frozen['queues']):abort(403)
            queues=sorted(set(queues)|set(frozen['queues']))
        if not all(can_queue(q,cap) for q in queues for cap in ('view','recording_play','caller_details')):abort(403)
        return source,queues
    def public(job):
        return {key:job[key] for key in ('id','state','created','updated','progress','error','result')}|{'source_job_id':job['spec']['source_job_id'],'language':job['spec']['language']}
    def safe(function):
        from functools import wraps
        @wraps(function)
        def call(*args,**kwargs):
            try:return function(*args,**kwargs)
            except AIConflict:return jsonify(error='analysis_request_conflict'),409
            except AIUnavailable:return jsonify(error='analysis_storage_unavailable'),503
            except QueryDeadline:return jsonify(error='analysis_query_deadline'),422
            except GenerationFailure:return jsonify(error='analysis_source_unavailable_or_limit'),422
            except (ValueError,TypeError,KeyError,OverflowError):return jsonify(error='invalid_analysis_request'),400
        return call
    @app.route('/api/history/generative-jobs',methods=['GET','POST'])
    @login_required
    @safe
    def generative_jobs():
        actor=owner()
        if request.method=='POST':
            if not enabled():abort(503)
            value=body()
            if set(value)-{'source_job_id','language','request_key'}:raise ValueError()
            source,queues=source_for(value.get('source_job_id'),actor)
            return jsonify(job=public(store.create(actor,source,queues,value.get('language','fa'),value.get('request_key')))),202
        rows=[];deadline=time.monotonic()+2;source_id=request.args.get('source_job_id')
        if source_id:source_for(source_id,actor,deadline=deadline)
        for job in store.list(actor,limit=20,source_job_id=source_id):
            if time.monotonic()>=deadline:break
            try:source_for(job['spec']['source_job_id'],actor,frozen=job['spec'],deadline=deadline)
            except (Forbidden,NotFound,GenerationFailure,QueryDeadline):continue
            rows.append(public(job))
        return jsonify(jobs=rows,enabled=bool(enabled()),machine_generated=True,automated_decision=False)
    @app.route('/api/history/generative-jobs/<ident>',methods=['GET','POST'])
    @login_required
    @safe
    def generative_job(ident):
        actor=owner();job=store.get(ident,actor)
        if job is None:abort(404)
        source_for(job['spec']['source_job_id'],actor,frozen=job['spec'])
        if request.method=='POST':
            if body():raise ValueError()
            return jsonify(cancelled=store.cancel(ident,actor))
        return jsonify(job=public(job))
