"""Current menu/queue grants on every survey request. No AMI calls."""
from datetime import datetime,timedelta
import hmac
import json
import os
from pathlib import Path
import sqlite3
import stat
from zoneinfo import ZoneInfo

from flask import abort,jsonify,request,session
from flask_login import current_user,login_required

from .adapter import configuration
from .store import SurveyStore


def read_json(path):
    path=Path(path)
    if path.is_symlink():raise ValueError('unsafe_survey_authorization')
    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0))
    with os.fdopen(fd,'rb') as stream:
        meta=os.fstat(stream.fileno())
        if not stat.S_ISREG(meta.st_mode) or meta.st_size>2*1024*1024:raise ValueError('invalid_survey_authorization')
        return json.loads(stream.read(2*1024*1024+1))


def access(accounts_path,policies_path,owner):
    from qpanel.local_accounts import validate_identity
    from qpanel.queue_policies import validate_config
    from sanequeue.security.permissions import sections_for,validate_sections
    try:
        accounts=read_json(accounts_path);account=accounts.get(owner)
        if not isinstance(account,dict):return None
        validate_identity(owner,account.get('role'),account.get('phone',''));validate_sections(account['role'],account.get('menus'))
        if not str(account.get('password_hash','')).startswith('pbkdf2:sha256:') or account['role'] not in ('admin','supervisor') or 'surveys' not in sections_for(account['role'],account):return None
        raw=read_json(policies_path)
        if not isinstance(raw,dict) or raw.get('version')!=1 or not all(k in raw for k in ('queues','supervisors')):return None
        policy=validate_config(raw);grant=policy['supervisors'].get(owner,{})
        def can(queue):return account['role']=='admin' or queue in grant.get('queues',[]) and all(c in grant.get('actions',[]) for c in ('view','survey_reports'))
        return dict(role=account['role'],can=can,queues=tuple(policy['queues']))
    except Exception:return None


def install(app,state):
    store=SurveyStore(state)
    def ctx():
        value=access(app.config.get('SANEQUEUE_SURVEY_ACCOUNTS',os.environ.get('SANEQUEUE_SURVEY_ACCOUNTS',Path(state)/'local_accounts.json')),app.config.get('SANEQUEUE_SURVEY_POLICIES',os.environ.get('SANEQUEUE_SURVEY_POLICIES',Path(state)/'local_queue_policies.json')),current_user.get_id())
        if value is None:abort(403)
        store.initialize()
        config=configuration(app.config.get('SANEQUEUE_SURVEY_CONFIG',os.environ.get('SANEQUEUE_SURVEY_CONFIG','/etc/sanequeue/survey-bindings.json')))
        known=set(value['queues'])|set(store.queues())|{b['queue'] for b in (config or {}).get('bindings',{}).values()}
        if len(known)>100:abort(422)
        value['allowed']=tuple(sorted(q for q in known if value['can'](q)));value['config']=config
        return value
    def csrf():
        token=session.get('csrf_token')
        if not token or not hmac.compare_digest(request.headers.get('X-CSRF-Token',''),token):abort(403)
    def respond(value,status=200):
        response=jsonify(value);response.status_code=status;response.headers['Cache-Control']='no-store';return response
    @app.route('/api/surveys/forms',methods=['GET','POST'])
    @login_required
    def survey_forms():
        try:
            context=ctx();bindings=(context['config'] or {}).get('bindings',{})
            if request.method=='POST':
                if context['role']!='admin':abort(403)
                csrf()
                if (request.content_length or 0)>32768:return respond(dict(error='survey_payload_too_large'),413)
                body=request.get_json(silent=True)
                if not isinstance(body,dict) or not isinstance(body.get('form'),dict) or not isinstance(body.get('binding'),str):raise ValueError('invalid_survey_request')
                binding=bindings.get(body.get('binding',''))
                if not binding:raise ValueError('survey_binding_required')
                form=dict(body['form']);form['id']=binding['form_id']
                store.save_form(form,current_user.get_id(),binding['prompts'])
            public={key:dict(row) for key,row in bindings.items() if row['queue'] in context['allowed']}
            forms=store.forms() if context['role']=='admin' else []
            return respond(dict(bindings=public,forms=forms,queues=context['allowed'],role=context['role'],integration='explicit_queue_c_hook_and_verified_queue_log_required'))
        except ValueError as error:return respond(dict(error=str(error)),400)
        except (OSError,sqlite3.Error):return respond(dict(error='survey_store_unavailable'),503)
    @app.route('/api/surveys/report')
    @login_required
    def survey_report():
        try:
            context=ctx();allowed=context['allowed'];queue=request.args.get('queue')
            if queue:
                if queue not in allowed:abort(403)
                allowed=(queue,)
            zone=ZoneInfo('Asia/Tehran');today=datetime.now(zone).date()
            start=datetime.fromisoformat(request.args.get('from',today.isoformat())).date();end=datetime.fromisoformat(request.args.get('to',today.isoformat())).date()+timedelta(days=1)
            result=store.report(allowed,datetime.combine(start,datetime.min.time(),zone).timestamp(),datetime.combine(end,datetime.min.time(),zone).timestamp(),before=request.args.get('before'))
            return respond(result)
        except ValueError as error:return respond(dict(error=str(error)),400)
        except (OSError,sqlite3.Error):return respond(dict(error='survey_query_unavailable'),503)
    @app.route('/api/surveys/sessions/<ident>')
    @login_required
    def survey_detail(ident):
        try:return respond(store.detail(ident,ctx()['allowed']))
        except PermissionError:abort(404)
        except ValueError:abort(404)
        except (OSError,sqlite3.Error):return respond(dict(error='survey_query_unavailable'),503)
