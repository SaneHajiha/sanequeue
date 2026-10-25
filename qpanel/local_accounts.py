"""Local lab account registry. Password hashes ONLY; never stores raw credentials."""
from pathlib import Path
import hashlib
import json
import os
import re
import secrets
import threading
import tempfile
import time
from copy import deepcopy

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.@-]{2,64}$")
PHONE_RE = re.compile(r"^(PJSIP|SIP)/[A-Za-z0-9_.-]{1,48}$")
ROLES = frozenset(("admin", "supervisor", "agent", "viewer"))
LOCK = threading.RLock()
ITERATIONS = 350_000
_UNSET=object()


def hash_secret(secret):
    if not isinstance(secret, str) or len(secret)<12 or len(secret)>200:
        raise ValueError('password_length_must_be_12_to_200')
    salt=secrets.token_hex(16)
    digest=hashlib.pbkdf2_hmac('sha256',secret.encode('utf-8'),salt.encode('utf-8'),ITERATIONS)
    return 'pbkdf2:sha256:%d$%s$%s' % (ITERATIONS,salt,digest.hex())


def validate_identity(username, role, phone):
    if not USERNAME_RE.fullmatch(str(username)) or role not in ROLES:
        raise ValueError('invalid_username_or_role')
    if phone and not PHONE_RE.fullmatch(str(phone)):
        raise ValueError('invalid_phone_interface')
    if role in ('supervisor','agent') and not phone:
        raise ValueError('supervisor_and_agent_require_phone')


def read_accounts(path):
    path=Path(path)
    if not path.exists():return {}
    value=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value,dict) or len(value)>100:raise ValueError('invalid_account_registry')
    for username,account in value.items():
        if not isinstance(account,dict):raise ValueError('invalid_account')
        validate_identity(username,account.get('role'),account.get('phone',''))
        if not str(account.get('password_hash','')).startswith('pbkdf2:sha256:'):
            raise ValueError('invalid_password_hash')
    return value


def write_accounts(path,accounts):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with LOCK:
        descriptor,temp=tempfile.mkstemp(prefix='.accounts-',dir=path.parent)
        try:
            with os.fdopen(descriptor,'w',encoding='utf-8') as f:
                json.dump(accounts,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
            os.replace(temp,path)
        finally:
            if os.path.exists(temp):os.unlink(temp)


def canonical_username(path,username):
    if not isinstance(username,str):return None
    return next((name for name in read_accounts(path) if name.casefold()==username.casefold()),None)


def account_config(original,accounts):
    """Build a complete replacement; readers never see deleted INI sections."""
    config=deepcopy(original)
    for section in ('users','roles','supervisor_extensions','agent_interfaces'):
        if config.has_section(section):config.remove_section(section)
        config.add_section(section)
    for username,account in accounts.items():
        config.set('users',username,account['password_hash']);config.set('roles',username,account['role'])
        phone=account.get('phone')
        if phone:
            config.set('supervisor_extensions',username,phone)
            config.set('agent_interfaces',username,phone+',Local/'+phone.split('/',1)[1]+'@from-queue/n')
    return config


def delete_account(path,username,actor,before_delete=None):
    with LOCK:
        if username==actor:raise ValueError('cannot_delete_self')
        users=read_accounts(path)
        if username not in users:raise ValueError('unknown_user')
        if users[username]['role']=='admin' and sum(a['role']=='admin' for a in users.values())<=1:raise ValueError('last_admin')
        if before_delete:before_delete()
        avatar=Path(path).parent/'avatars'/(hashlib.sha256(username.encode()).hexdigest()+'.png')
        avatar.unlink(missing_ok=True)
        del users[username];write_accounts(path,users)


def set_account(path,username,role,phone,password=None,*,menus=_UNSET):
    with LOCK:
        validate_identity(username,role,phone)
        registry=read_accounts(path)
        if username not in registry and len(registry)>=100:raise ValueError('account_limit_reached')
        old=registry.get(username,{})
        if old.get('role') == 'admin' and role != 'admin' and sum(v.get('role') == 'admin' for v in registry.values()) <= 1:
            raise ValueError('last_admin')
        if any(other != username and other.casefold() == username.casefold() for other in registry):
            raise ValueError('username_already_exists')
        if phone and any(other != username and value.get('phone') == phone for other, value in registry.items()):
            raise ValueError('phone_already_assigned')
        if not password and not old:raise ValueError('new_account_requires_password')
        hashed=hash_secret(password) if password else old['password_hash']
        from sanequeue.security.permissions import validate_sections
        selected=validate_sections(role,None if menus is _UNSET else menus)
        registry[username]=dict(old,role=role,phone=phone,password_hash=hashed)
        if phone!=old.get('phone',''):
            registry[username]['phone_assigned_at']=time.time()
        if menus is not _UNSET:
            if selected is None:registry[username].pop('menus',None)
            else:registry[username]['menus']=selected
        elif old.get('menus') is not None:
            from sanequeue.security.permissions import sections_for
            registry[username]['menus']=sorted(sections_for(role,old))
        write_accounts(path,registry)
        return {k:v for k,v in registry[username].items() if k!='password_hash'}


def bootstrap(path):
    with LOCK:
        if read_accounts(path):return None
        password=secrets.token_urlsafe(22)
        set_account(path,'admin','admin','PJSIP/100',password)
        return password


def public_accounts(path):
    return {username:{'role':x['role'],'phone':x.get('phone',''),'menus':x.get('menus'),'display_name':x.get('display_name','')} for username,x in read_accounts(path).items()}
