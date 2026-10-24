"""Set local admin's supervisor phone to PJSIP/100, preserving the password hash."""
from pathlib import Path
from qpanel.local_accounts import read_accounts,write_accounts
path=Path(__file__).resolve().parent / 'local_accounts.json'
accounts=read_accounts(path)
if 'admin' not in accounts:
    raise SystemExit('admin account not found; launch server once to bootstrap it')
if accounts['admin']['role']!='admin':
    raise SystemExit('not an admin identity')
accounts['admin']['phone']='PJSIP/100'
write_accounts(path,accounts)
print('OK: admin phone PJSIP/100; password hash preserved. Restart SaneQueue.')
