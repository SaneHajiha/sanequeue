#!/usr/bin/env python3
"""Initialize server account state interactively, without logging credentials."""
import argparse
import getpass
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from qpanel.local_accounts import read_accounts, set_account
parser=argparse.ArgumentParser()
parser.add_argument('--state',required=True)
args=parser.parse_args()
path=Path(args.state)/'local_accounts.json'
if read_accounts(path):parser.error('Accounts already initialized; use account management.')
name=input('Administrator username [admin]: ').strip() or 'admin'
secret=getpass.getpass('Password (12–200 characters): ')
if secret != getpass.getpass('Repeat password: '):parser.error('Passwords do not match')
set_account(path,name,'admin','',secret)
print('Administrator initialized. Assign supervisor phones in Users & access.')
