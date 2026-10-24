#!/usr/bin/env python3
"""Create an installation-specific configuration; never overwrite an existing one."""
import configparser
import getpass
import os
import secrets
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qpanel.local_accounts import set_account
from werkzeug.security import generate_password_hash

target = sys.argv[1] if len(sys.argv) > 1 else 'config.ini'
if os.path.exists(target):
    sys.exit('Configuration already exists; edit it manually: ' + target)
cfg = configparser.ConfigParser(interpolation=None)
cfg['manager'] = {'host': input('AMI host [127.0.0.1]: ').strip() or '127.0.0.1',
                  'port': '5038', 'user': input('AMI username: ').strip(),
                  'password': getpass.getpass('AMI password: ')}
username = input('Dashboard admin username [admin]: ').strip() or 'admin'
password = getpass.getpass('Dashboard password (at least 12 characters): ')
if len(password) < 12 or password != getpass.getpass('Repeat dashboard password: '):
    sys.exit('Passwords must match and contain at least 12 characters.')
cfg['general'] = {'host': '127.0.0.1', 'port': '5000', 'language': 'fa',
                  'interval': '5', 'debug': 'False', 'check_upgrade': 'False',
                  'secret_key': secrets.token_hex(32), 'theme': 'qpanel'}
cfg['users'] = {username: generate_password_hash(password, method='pbkdf2:sha256:600000')}
cfg['roles'] = {username: 'admin'}
state = Path(os.getenv('SANEQUEUE_STATE_DIR', '/var/lib/sanequeue'))
if (state / 'local_accounts.json').exists():
    sys.exit('Account state already exists; use MANAGE_LOCAL_USERS.py.')
cfg['sanequeue'] = {'queue_log_path': '/var/log/asterisk/queue_log',
                    'report_database': '/var/lib/sanequeue/reports.sqlite3',
                    'sla_seconds': '20', 'wait_threshold': '60', 'minimum_ready': '0'}
os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as f:
    cfg.write(f)
set_account(state / 'local_accounts.json', username, 'admin', '', password)
print('Created configuration and hashed administrator account: ' + target)
