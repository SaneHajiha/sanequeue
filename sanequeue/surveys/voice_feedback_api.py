"""Manual, authorized intake and separately authorized voice playback/download."""
from functools import wraps
import hmac
import io
import os
from pathlib import Path
import sqlite3

from flask import abort,jsonify,request,session,send_file
from flask_login import current_user,login_required

from .api import read_json
from .store import SurveyStore
from .voice_feedback import VoiceFeedback,Conflict,Unavailable,MAX_BYTES,STATES

def authorization(accounts_path,policies_path,owner):
    from qpanel.local_accounts import validate_identity
    from qpanel.queue_policies import validate_config
    from sanequeue.security.permissions import sections_for,validate_sections,ROLE_ACTIONS
    try:
        accounts=read_json(accounts_path);raw=read_json(policies_path)
        if not isinstance(accounts,dict) or len(accounts)>100 or not isinstance(raw,dict) or raw.get('version')!=1:return None
        policy=validate_config(raw)
        def account(name):
            row=accounts.get(name)
            if not isinstance(row,dict):return None
            validate_identity(name,row.get('role'),row.get('phone',''));validate_sections(row['role'],row.get('menus'))
            if row['role'] not in ('admin','supervisor') or 'surveys' not in sections_for(row['role'],row) or not str(row.get('password_hash','')).startswith('pbkdf2:sha256:'):return None
            return row
        def can(name,queue,cap=None):
            row=account(name)
            if row is None or queue not in policy['queues']:return False
            actions=('view','survey_reports')+((cap,) if cap else ())
            if any(a not in ROLE_ACTIONS[row['role']] for a in actions):return False
            grant=policy['supervisors'].get(name,{})
            return row['role']=='admin' or queue in grant.get('queues',[]) and all(a in grant.get('actions',[]) for a in actions)
        if account(owner) is None:return None
        allowed=tuple(q for q in policy['queues'] if can(owner,q))
        return dict(queues=allowed,can=lambda q,cap=None:can(owner,q,cap),assignees=lambda q:[name for name in accounts if can(name,q)])
    except Exception:return None

def install(app,state):
    store=VoiceFeedback(state);ready=True
    try:store.initialize()
    except (OSError,sqlite3.Error,ValueError,Unavailable):ready=False
    def context():
        value=authorization(app.config.get('SANEQUEUE_VOICE_ACCOUNTS',os.environ.get('SANEQUEUE_VOICE_ACCOUNTS',Path(state)/'local_accounts.json')),app.config.get('SANEQUEUE_VOICE_POLICIES',os.environ.get('SANEQUEUE_VOICE_POLICIES',Path(state)/'local_queue_policies.json')),str(current_user.get_id()))
        if value is None:abort(403)
        if not ready:raise Unavailable('voice_feedback_storage_unavailable')
        if request.method=='POST':
            expected=session.get('csrf_token');actual=request.headers.get('X-CSRF-Token')
            if not isinstance(expected,str) or not expected or not isinstance(actual,str) or not hmac.compare_digest(expected,actual):abort(403)
        return value
    def safe(function):
        @wraps(function)
        def call(*args,**kwargs):
            try:response=app.make_response(function(*args,**kwargs))
            except Conflict as error:response=app.make_response((jsonify(error=str(error)),409))
            except FileNotFoundError:response=app.make_response((jsonify(error='voice_feedback_not_found'),404))
            except PermissionError:response=app.make_response((jsonify(error='voice_feedback_scope_denied'),403))
            except ValueError:response=app.make_response((jsonify(error='invalid_voice_feedback_request'),400))
            except (Unavailable,OSError,sqlite3.Error):response=app.make_response((jsonify(error='voice_feedback_unavailable'),503))
            response.headers['Cache-Control']='private, no-store';response.headers['X-Content-Type-Options']='nosniff'
            return response
        return call
    def row_context(ident,cap=None):
        ctx=context();row=store.detail(ident,ctx['queues'])
        if cap and not ctx['can'](row['queue'],cap):abort(403)
        return ctx,row
    @app.route('/api/voice-feedback',methods=['GET','POST'])
    @login_required
    @safe
    def voice_feedback_collection():
        ctx=context()
        if request.method=='GET':
            queue=request.args.get('queue');queues=ctx['queues']
            if queue:
                if queue not in queues:abort(403)
                queues=(queue,)
            return jsonify(**store.report(queues,status=request.args.get('status') or None,before=request.args.get('before')),queues=ctx['queues'],statuses=STATES)
        queue=request.args.get('queue')
        if queue not in ctx['queues']:abort(403)
        if request.mimetype not in ('audio/wav','audio/x-wav','application/octet-stream'):abort(415)
        if request.content_length is not None and request.content_length>MAX_BYTES:abort(413)
        data=request.stream.read(MAX_BYTES+1)
        if len(data)>MAX_BYTES:abort(413)
        survey_id=request.args.get('survey_session');survey=None
        if survey_id:
            survey_store=SurveyStore(state)
            if not survey_store.path.is_file():raise FileNotFoundError()
            try:survey=survey_store.detail(survey_id,(queue,))
            except (ValueError,PermissionError):raise FileNotFoundError() from None
        # This attaches an operator-selected file. It never proves who spoke.
        row,created=store.intake(data,queue,str(current_user.get_id()),request.headers.get('Idempotency-Key'),survey=survey)
        return jsonify(feedback=row,created=created),201 if created else 200
    @app.route('/api/voice-feedback/<ident>',methods=['GET','POST'])
    @login_required
    @safe
    def voice_feedback_detail(ident):
        ctx,row=row_context(ident)
        if request.method=='POST':
            if request.content_length is not None and request.content_length>4096:abort(413)
            import json
            raw=request.stream.read(4097)
            if len(raw)>4096:abort(413)
            body=json.loads(raw)
            if not isinstance(body,dict) or set(body)-{'version','status','assignee','note','followup_at'}:raise ValueError()
            if body.get('assignee','') not in ('',*ctx['assignees'](row['queue'])):raise ValueError()
            row=store.update(ident,ctx['queues'],str(current_user.get_id()),version=body.get('version'),status=body.get('status'),assignee=body.get('assignee',''),note=body.get('note',''),followup_at=body.get('followup_at'))
        return jsonify(feedback=row,assignees=ctx['assignees'](row['queue']),capabilities=dict(play=ctx['can'](row['queue'],'recording_play'),download=ctx['can'](row['queue'],'recording_download')))
    @app.get('/api/voice-feedback/<ident>/audio/<action>')
    @login_required
    @safe
    def voice_feedback_audio(ident,action):
        if action not in ('play','download'):raise FileNotFoundError()
        ctx,row=row_context(ident,'recording_'+action)
        data=store.audio(ident,ctx['queues'],str(current_user.get_id()),action+'_request')
        response=send_file(io.BytesIO(data),mimetype='audio/wav',as_attachment=action=='download',download_name='voice-feedback-'+ident+'.wav',conditional=False)
        response.headers['Accept-Ranges']='none';return response
    @app.get('/api/voice-feedback/<ident>/audit')
    @login_required
    @safe
    def voice_feedback_audit(ident):
        ctx,row=row_context(ident)
        return jsonify(events=store.history(ident,ctx['queues']),meaning='requests_and_review_changes_not_proof_of_listening')
    return store
