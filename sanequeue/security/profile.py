"""Authenticated self-service profile updates; never modify roles or queue grants."""
import hashlib
import hmac
import io
import os
from pathlib import Path
import secrets
import warnings
import time

from flask import abort,jsonify,request,session,send_file
from flask_login import current_user,login_required,logout_user
from werkzeug.security import check_password_hash
from qpanel.local_accounts import LOCK,read_accounts,write_accounts,hash_secret
from sanequeue.realtime.local_inventory import read_snapshot


def clean_avatar(content):
    if not content or len(content)>512*1024:raise ValueError('avatar_max_512kb')
    from PIL import Image,ImageOps
    with warnings.catch_warnings():
        warnings.simplefilter('error',Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(content)) as image:
            if image.format not in ('PNG','JPEG','WEBP') or image.width*image.height>4_000_000:
                raise ValueError('avatar_format_or_dimensions')
            image=ImageOps.exif_transpose(image)
            image.thumbnail((256,256),Image.Resampling.LANCZOS)
            clean=Image.new('RGBA',image.size);clean.paste(image.convert('RGBA'))
            output=io.BytesIO();clean.save(output,format='PNG')
            return output.getvalue()


def install(app,accounts_path,state_dir,sync_accounts):
    state_dir=Path(state_dir)
    def avatar_path(username):return state_dir/'avatars'/(hashlib.sha256(username.encode()).hexdigest()+'.png')
    def phones(username):
        inventory=read_snapshot(os.getenv('SANEQUEUE_LOCAL_INVENTORY','/run/sanequeue/inventory.json'))
        if inventory is None:return None
        accounts=read_accounts(accounts_path)
        used={a.get('phone') for name,a in accounts.items() if name!=username}
        return sorted({r['technology']+'/'+r['endpoint'] for r in inventory['endpoints'] if r['category']=='extension'}-used)

    @app.route('/api/profile',methods=['GET','POST'])
    @login_required
    def sq_profile():
        username=current_user.get_id()
        account=read_accounts(accounts_path).get(username)
        if account is None:abort(403)
        if request.method=='GET':
            available=phones(username)
            response=jsonify(username=username,role=account['role'],phone=account.get('phone',''),
                             first_name=account.get('first_name',''),last_name=account.get('last_name',''),
                             display_name=account.get('display_name',''),available_phones=available or [],
                             inventory_available=available is not None,avatar_url='/api/profile/avatar' if avatar_path(username).exists() else None,
                             dial_options=(app.config.get('SANEQUEUE_PROFILE_DIAL_OPTIONS') or (lambda:dict(queues=[],extensions=[])))())
            response.headers['Cache-Control']='no-store';return response
        if not session.get('csrf_token') or not hmac.compare_digest(request.headers.get('X-CSRF-Token',''),session['csrf_token']):abort(403)
        if (request.content_length or 0)>1024*1024:return jsonify(error='profile_too_large'),413
        name=request.form.get('display_name',account.get('display_name','')).strip()
        first=request.form.get('first_name',account.get('first_name','')).strip()
        last=request.form.get('last_name',account.get('last_name','')).strip()
        if any(len(value)>32 or any(not c.isprintable() for c in value) for value in (first,last)):
            return jsonify(error='invalid_person_name'),400
        if 'first_name' in request.form or 'last_name' in request.form:
            name=' '.join(value for value in (first,last) if value)
        phone=request.form.get('phone',account.get('phone','')).strip()
        password=request.form.get('new_password','')
        old=request.form.get('current_password','')
        if len(name)>65 or any(not c.isprintable() for c in name):return jsonify(error='invalid_display_name'),400
        sensitive=bool(password) or phone!=account.get('phone','')
        if sensitive and (not 1<=len(old)<=200 or not check_password_hash(account['password_hash'],old)):
            return jsonify(error='current_password_required'),403
        if password and not 12<=len(password)<=200:return jsonify(error='password_length_must_be_12_to_200'),400
        if phone!=account.get('phone',''):
            if not phone and account['role'] in ('agent','supervisor'):return jsonify(error='assigned_phone_required'),400
            if phone:
                available=phones(username)
                if available is None:return jsonify(error='extension_inventory_unavailable'),503
                if phone not in available:return jsonify(error='extension_unavailable_or_assigned'),409
        avatar=None
        if request.files.get('avatar'):
            try:avatar=clean_avatar(request.files['avatar'].read(512*1024+1))
            except ImportError:return jsonify(error='avatar_dependency_unavailable'),503
            except Exception:return jsonify(error='invalid_avatar_max_512kb_4mp'),400
        with LOCK:
            accounts=read_accounts(accounts_path)
            # Reject concurrent administrator/password changes instead of overwriting them.
            if accounts.get(username)!=account:return jsonify(error='profile_changed_retry'),409
            if phone and any(user!=username and value.get('phone')==phone for user,value in accounts.items()):
                return jsonify(error='phone_already_assigned'),409
            value=dict(account,display_name=name,first_name=first,last_name=last,phone=phone)
            if phone!=account.get('phone',''):value['phone_assigned_at']=time.time()
            if password:value['password_hash']=hash_secret(password)
            if avatar is not None:
                target=avatar_path(username);target.parent.mkdir(parents=True,exist_ok=True)
                temporary=target.with_name('.'+secrets.token_hex(16)+'.png')
                try:
                    descriptor=os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
                    with os.fdopen(descriptor,'wb') as stream:stream.write(avatar);stream.flush();os.fsync(stream.fileno())
                    os.replace(temporary,target)
                finally:
                    if temporary.exists():temporary.unlink()
            elif request.form.get('remove_avatar')=='true':avatar_path(username).unlink(missing_ok=True)
            accounts[username]=value;write_accounts(accounts_path,accounts);sync_accounts()
        if sensitive:
            registry=app.config.get('SANEQUEUE_AUTH_SESSIONS')
            if registry:registry.revoke_user(username)
            logout_user();session.clear()
        return jsonify(ok=True,login_required=sensitive)

    @app.route('/api/profile/avatar')
    @login_required
    def sq_profile_avatar():
        target=avatar_path(current_user.get_id())
        if not target.is_file():abort(404)
        response=send_file(target,mimetype='image/png',conditional=False)
        response.headers['Cache-Control']='private, no-store';response.headers['X-Content-Type-Options']='nosniff'
        return response
