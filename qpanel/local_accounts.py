"""Local lab account registry. Password hashes ONLY; never stores raw credentials."""
from pathlib import Path
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.@-]{2,64}$")
PHONE_RE = re.compile(r"^(PJSIP|SIP)/[A-Za-z0-9_.-]{1,48}$")
ROLES = frozenset(("admin", "supervisor", "agent", "viewer"))
LOCK = threading.RLock()
ITERATIONS = 350_000


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
    temp=path.with_suffix('.tmp')
    with temp.open('w',encoding='utf-8') as f:
        json.dump(accounts,f,ensure_ascii=False,indent=2)
        f.flush();os.fsync(f.fileno())
    try:os.chmod(temp,0o600)
    except OSError:pass
    os.replace(temp,path)


def set_account(path,username,role,phone,password=None):
    with LOCK:
        validate_identity(username,role,phone)
        registry=read_accounts(path)
        old=registry.get(username,{})
        if old.get('role') == 'admin' and role != 'admin' and sum(v.get('role') == 'admin' for v in registry.values()) <= 1:
            raise ValueError('last_admin')
        if any(other != username and other.casefold() == username.casefold() for other in registry):
            raise ValueError('username_already_exists')
        if phone and any(other != username and value.get('phone') == phone for other, value in registry.items()):
            raise ValueError('phone_already_assigned')
        if not password and not old:raise ValueError('new_account_requires_password')
        hashed=hash_secret(password) if password else old['password_hash']
        registry[username]={'role':role,'phone':phone,'password_hash':hashed}
        write_accounts(path,registry)
        return {k:v for k,v in registry[username].items() if k!='password_hash'}


def bootstrap(path):
    with LOCK:
        if read_accounts(path):return None
        password=secrets.token_urlsafe(22)
        set_account(path,'admin','admin','PJSIP/100',password)
        return password


def public_accounts(path):
    return {username:{'role':x['role'],'phone':x.get('phone','')} for username,x in read_accounts(path).items()}
