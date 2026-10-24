import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask
from werkzeug.security import check_password_hash
from qpanel.local_accounts import set_account, read_accounts
from qpanel.theme_support import setup_themes


class RecoveryTests(unittest.TestCase):
    def test_empty_password_is_rejected_and_valid_reset_preserves_identity(self):
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location('recovery', root/'scripts/reset_password.py')
        recovery = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(recovery)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'local_accounts.json'
            set_account(path, 'admin', 'admin', 'PJSIP/300', 'original-test-password')
            original = path.read_bytes()
            args = ['reset_password.py', '--state', tmp, '--username', 'admin']
            with patch('sys.argv', args), patch.object(recovery, 'getpass', side_effect=['', '']), self.assertRaises(SystemExit):
                recovery.main()
            self.assertEqual(path.read_bytes(), original)
            with patch('sys.argv', args), patch.object(recovery, 'getpass', side_effect=['new-test-password', 'new-test-password']):
                recovery.main()
            account = read_accounts(path)['admin']
            self.assertEqual((account['role'], account['phone']), ('admin', 'PJSIP/300'))
            self.assertTrue(check_password_hash(account['password_hash'], 'new-test-password'))
            self.assertNotIn('new-test-password', path.read_text())


class AssetTests(unittest.TestCase):
    def test_brand_asset_alias_works_without_allowing_path_traversal(self):
        app = Flask('asset-test', root_path=str(Path(__file__).resolve().parents[1]/'qpanel'))
        setup_themes(app)
        client = app.test_client()
        self.assertEqual(client.get('/assets/js/operations.js').status_code, 200)
        for path in ('/assets/../config.py', '/assets/%2e%2e/config.py', '/assets/../../LICENSE'):
            self.assertEqual(client.get(path).status_code, 404)
