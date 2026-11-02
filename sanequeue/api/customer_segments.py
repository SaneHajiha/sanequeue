"""Authenticated reporting metadata, never PBX block/routing configuration."""
from functools import wraps
import hashlib
import hmac
import json
import sqlite3
from flask import abort,jsonify,request,session
from flask_login import current_user,login_required
from sanequeue.reporting.customer_segments import CustomerSegments,SegmentConflict
from sanequeue.reporting.privacy import display_number
from sanequeue.reporting.store import QueryDeadline


def install(app,archive,*,context,role,sections,can_queue,pbx='primary'):
    store=CustomerSegments(archive.path.parent/'customer-segments.sqlite3',pbx=pbx)
    try:store.initialize();ready=True
    except (OSError,sqlite3.Error,ValueError):ready=False
    @app.after_request
    def segments_private(response):
        if request.endpoint and request.endpoint.startswith('segments_'):
            response.headers['Cache-Control']='private, no-store';response.headers['X-Content-Type-Options']='nosniff'
        return response
    def authorized():
        if role() not in ('admin','supervisor') or 'reports' not in sections():abort(403)
        if not ready:abort(503)
        return context()
    def safe(function):
        @wraps(function)
        def call(*args,**kwargs):
            try:return function(*args,**kwargs)
            except SegmentConflict as error:return jsonify(error=str(error)),409
            except QueryDeadline:return jsonify(error='segments_query_deadline'),422
            except (OSError,sqlite3.Error):return jsonify(error='segments_storage_unavailable'),503
            except (TypeError,ValueError,OverflowError):return jsonify(error='invalid_segments_request'),400
        return call
    @app.get('/api/history/customer-segments')
    @login_required
    @safe
    def segments_report():
        scope,start,end=authorized()
        data=store.report(archive,scope,start,end,sla_seconds=int(request.args.get('sla_seconds','20')))
        secret=hashlib.sha256(('sanequeue.reporting.numbers:'+str(app.secret_key)).encode()).digest()
        for rows in (data['observations'],data['labels']):
            for row in rows:
                row['number']=display_number(row['number'],mode='full' if can_queue(row['queue'],'caller_details') else 'masked',secret=secret,tenant='default',pbx=pbx,version='1')
        data['queues']=list(scope.queues);data['can_manage']=role()=='admin'
        return jsonify(data)
    @app.post('/api/history/customer-segments/vip')
    @login_required
    @safe
    def segments_vip():
        scope,start,_=authorized()
        if role()!='admin':abort(403)
        token=session.get('csrf_token');actual=request.headers.get('X-CSRF-Token')
        if not isinstance(token,str) or not token or not isinstance(actual,str) or not hmac.compare_digest(token,actual):abort(403)
        if not request.is_json:abort(415)
        if request.content_length is not None and request.content_length>4096:abort(413)
        raw=request.stream.read(4097)
        if len(raw)>4096:abort(413)
        body=json.loads(raw)
        if not isinstance(body,dict):raise ValueError()
        queue=body.get('queue')
        if not isinstance(queue,str) or queue not in scope.queues or not can_queue(queue,'caller_details'):abort(403)
        apply=body.get('apply_from_period_start',False)
        if type(apply) is not bool:raise ValueError()
        row=store.tag(str(current_user.get_id()),queue,body.get('number'),body.get('enabled'),effective=start if apply else None,request_key=body.get('request_key'))
        return jsonify(id=row['id'],queue=row['queue'],effective=row['effective'],enabled=bool(row['enabled'])),201
