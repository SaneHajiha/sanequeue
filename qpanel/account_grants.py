"""One-screen, atomic-in-one-process local account and queue grant updates.

This lab-only filesystem registry is not a multi-worker directory or a production
identity service. No AMI credentials are stored here.
"""
from copy import deepcopy
from threading import RLock
from qpanel.local_accounts import (read_accounts,write_accounts,set_account,
                                    validate_identity,public_accounts,LOCK)
from qpanel.queue_policies import validate_config,DEFAULT_QUEUE,ALLOWED_GRANTS

_SAVE_LOCK = RLock()


def save_account_with_grants(path, store, visible_queues, obj):
    if not isinstance(obj, dict):
        raise ValueError('invalid_account_request')
    username = str(obj.get('username', '')).strip()
    role = str(obj.get('role', '')).strip()
    phone = str(obj.get('phone', '')).strip()
    password = obj.get('password') or None
    qids = obj.get('queues', [])
    actions = obj.get('actions', [])
    validate_identity(username, role, phone)
    if not isinstance(qids, list) or not isinstance(actions, list):
        raise ValueError('invalid_grant_format')
    if any(not isinstance(x, str) for x in qids + actions):
        raise ValueError('invalid_grant_format')
    qids = list(dict.fromkeys(qids))
    actions = list(dict.fromkeys(actions))
    visible = set(visible_queues)
    if any(q not in visible for q in qids):
        raise ValueError('queue_not_visible')
    if any(action not in ALLOWED_GRANTS for action in actions):
        raise ValueError('unknown_permission')
    from sanequeue.security.permissions import ROLE_ACTIONS,validate_sections
    if any(action not in ROLE_ACTIONS[role] for action in actions):raise ValueError('permission_exceeds_role')
    menus=validate_sections(role,obj.get('menus'))
    if qids and 'view' not in actions:
        raise ValueError('view_permission_required')
    if not qids:
        actions = []
    with _SAVE_LOCK,LOCK:
        previous_accounts = read_accounts(path)
        if not password and username not in previous_accounts:
            raise ValueError('new_account_requires_password')
        if password and not 12 <= len(password) <= 200:
            raise ValueError('password_length_must_be_12_to_200')
        if phone and any(other != username and account.get('phone') == phone
                         for other, account in previous_accounts.items()):
            raise ValueError('phone_already_assigned')
        previous_policies = store.export()
        new_policies = deepcopy(previous_policies)
        for q in qids:
            new_policies['queues'].setdefault(q, deepcopy(DEFAULT_QUEUE))
        if role == 'admin':
            # Admin permission is intrinsic. Avoid stale user grants for admin.
            new_policies['supervisors'].pop(username, None)
        else:
            new_policies['supervisors'][username] = {'queues': qids, 'actions': actions}
        validate_config(new_policies)  # Validate before any disk write.
        try:
            set_account(path, username, role, phone, password, menus=menus)
            saved = store.replace(new_policies, visible_queues=visible)
        except Exception:
            write_accounts(path, previous_accounts)
            raise
        return {'accounts': public_accounts(path), 'policies': saved}
