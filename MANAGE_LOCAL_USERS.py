"""Offline local account recovery tool. Never accepts passwords as CLI args."""
from pathlib import Path
from getpass import getpass
from qpanel.local_accounts import set_account,public_accounts
path=Path(__file__).resolve().parent/'local_accounts.json'
print('Local SaneQueue users:',public_accounts(path))
name=input('Username: ').strip()
role=input('Role (admin/supervisor/agent/viewer): ').strip()
phone=input('Own phone PJSIP/101, or blank for admin/viewer: ').strip()
password=getpass('New password (empty keeps existing): ')
try:
    print('Account updated:',set_account(path,name,role,phone,password or None))
    print('Restart SaneQueue to load the updated account.')
except ValueError as exc:
    print('Invalid account:',exc)
