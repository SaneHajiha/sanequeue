"""Local organization identity and reversible monitoring maintenance mode."""
import hmac
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import math

from flask import abort,jsonify,request,session,send_file
from flask_login import current_user,login_required
from .profile import clean_avatar


def disabled():
    return Path(os.getenv('SANEQUEUE_DISABLE_FILE','/var/lib/sanequeue/module.disabled')).exists()


class Organization:
    def __init__(self,path):
        self.path=Path(path);self.lock=threading.RLock()
        self.logo=self.path.with_name('organization-logo.png')

    def public(self):
        try:
            value=json.loads(self.path.read_text(encoding='utf-8')) if self.path.stat().st_size<=16384 else {}
        except (OSError,ValueError):value={}
        if not isinstance(value,dict):value={}
        name=value.get('name');subtitle=value.get('subtitle')
        if not isinstance(name,str) or not 1<=len(name)<=65 or not name.isprintable():name='SaneQueue'
        if not isinstance(subtitle,str) or len(subtitle)>90 or any(not c.isprintable() for c in subtitle):subtitle='CONTACT CENTER'
        updated=value.get('updated_at',0)
        if not isinstance(updated,(int,float)) or not math.isfinite(updated):updated=0
        return dict(name=name,subtitle=subtitle,updated_at=updated,logo_url='/organization/logo' if self.logo.is_file() else None)

    def replace(self,name,subtitle,logo=None,remove=False):
        if not isinstance(name,str) or not 1<=len(name.strip())<=65 or any(not c.isprintable() for c in name):raise ValueError('invalid_organization_name')
        if not isinstance(subtitle,str) or len(subtitle)>90 or any(not c.isprintable() for c in subtitle):raise ValueError('invalid_organization_subtitle')
        try:image=clean_avatar(logo) if logo is not None else None
        except ImportError:raise
        except Exception:raise ValueError('invalid_logo') from None
        def atomic(path,content):
            path.parent.mkdir(parents=True,exist_ok=True)
            descriptor,temporary=tempfile.mkstemp(prefix='.organization-',dir=path.parent)
            try:
                with os.fdopen(descriptor,'wb') as stream:stream.write(content);stream.flush();os.fsync(stream.fileno())
                os.replace(temporary,path)
            finally:
                if os.path.exists(temporary):os.unlink(temporary)
        with self.lock:
            if image is not None:atomic(self.logo,image)
            elif remove and self.logo.exists():self.logo.unlink()
            atomic(self.path,json.dumps(dict(name=name.strip(),subtitle=subtitle.strip(),updated_at=time.time())).encode())
            return self.public()


def install(app,state,role):
    organization=Organization(Path(state)/'organization.json')
    app.context_processor(lambda:dict(organization=organization.public()))
    def administrator():
        if role()!='admin':abort(403)
        provider=app.config.get('SANEQUEUE_MENU_PROVIDER')
        if callable(provider) and 'settings' not in provider(current_user.get_id(),'admin'):abort(403)
    def csrf():
        if not session.get('csrf_token') or not hmac.compare_digest(request.headers.get('X-CSRF-Token',''),session['csrf_token']):abort(403)

    @app.route('/organization/logo')
    def organization_logo():
        if not organization.logo.is_file():abort(404)
        response=send_file(organization.logo,mimetype='image/png',conditional=False)
        response.headers['Cache-Control']='no-store';response.headers['X-Content-Type-Options']='nosniff'
        return response

    @app.route('/api/organization',methods=['GET','POST'])
    @login_required
    def organization_settings():
        administrator()
        if request.method=='POST':
            csrf()
            if (request.content_length or 0)>800*1024:return jsonify(error='organization_too_large'),413
            try:
                image=request.files.get('logo')
                value=organization.replace(request.form.get('name',''),request.form.get('subtitle',''),image.read(512*1024+1) if image else None,request.form.get('remove_logo')=='true')
            except ImportError:return jsonify(error='avatar_dependency_unavailable'),503
            except ValueError:return jsonify(error='invalid_organization_or_logo'),400
            except OSError:return jsonify(error='organization_storage_unavailable'),503
        else:value=organization.public()
        return jsonify(value)

    @app.route('/api/module',methods=['GET','POST'])
    @login_required
    def module_settings():
        administrator()
        if request.method=='POST':
            csrf()
            obj=request.get_json(silent=True)
            if not isinstance(obj,dict) or not isinstance(obj.get('enabled'),bool):return jsonify(error='invalid_module_state'),400
            target=Path(os.getenv('SANEQUEUE_DISABLE_FILE','/var/lib/sanequeue/module.disabled'))
            if obj['enabled']:
                target.unlink(missing_ok=True)
            else:
                target.parent.mkdir(parents=True,exist_ok=True)
                descriptor=os.open(target,os.O_CREAT|os.O_WRONLY|os.O_TRUNC,0o600)
                with os.fdopen(descriptor,'w') as stream:stream.write('Monitoring disabled by administrator\n')
        response=jsonify(enabled=not disabled(),scope='sanequeue_monitoring',asterisk_restarted=False)
        response.headers['Cache-Control']='no-store';return response
