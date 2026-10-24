#!/usr/bin/env python3
"""Offline password recovery preserving an existing account's phone and role."""
import argparse
from getpass import getpass
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from qpanel.local_accounts import read_accounts, set_account


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', required=True)
    parser.add_argument('--username', required=True)
    args = parser.parse_args()
    path = Path(args.state) / 'local_accounts.json'
    account = read_accounts(path).get(args.username)
    if not account:
        parser.error('Account does not exist; no account was changed.')
    secret = getpass('New password (12–200 characters): ')
    if secret != getpass('Repeat password: '):
        parser.error('Passwords do not match; no account was changed.')
    if not 12 <= len(secret) <= 200:
        parser.error('Password must contain 12–200 characters; no account was changed.')
    try:
        set_account(path, args.username, account['role'], account.get('phone', ''), secret)
    except ValueError as exc:
        parser.error(str(exc))
    print('Password updated. Restart the dashboard; existing sessions will be invalidated.')


if __name__ == '__main__':
    main()
