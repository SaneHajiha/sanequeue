"""Offline beta15 RBAC, one-click selectors, routing registration and safe launch tests.
Not a live Asterisk or installed Windows UI validation.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from jinja2 import Environment
from qpanel.account_grants import save_account_with_grants
from qpanel.queue_policies import QueuePolicyStore
from qpanel.local_accounts import read_accounts,public_accounts

R=Path(__file__).resolve().parents[1]
JS=(R/'qpanel/themes/qpanel/static/js/operations.js').read_text(encoding='utf8')
HTML=(R/'qpanel/themes/qpanel/templates/operations.html').read_text(encoding='utf8')
APP=(R/'demo_monitor.py').read_text(encoding='utf8')

class Beta15Test(unittest.TestCase):
 def setUp(self):
  self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.accounts=Path(self.tmp.name)/'accounts.json'
  self.store=QueuePolicyStore(Path(self.tmp.name)/'policy.json')
 def save(self,**overrides):
  d={'username':'superA','role':'supervisor','phone':'PJSIP/270','password':'0123456789xy','queues':['8001'],'actions':['view','monitor']}
  d.update(overrides)
  return save_account_with_grants(self.accounts,self.store,{'8001','8002'},d)
 def test_combined_create_user_phone_and_scope(self):
  result=self.save()
  self.assertEqual(result['accounts']['superA']['phone'],'PJSIP/270')
  self.assertEqual(result['policies']['supervisors']['superA']['queues'],['8001'])
  self.assertTrue(self.store.access('superA','supervisor','8001','monitor'))
  self.assertFalse(self.store.access('superA','supervisor','8002','monitor'))
  self.assertNotIn('password',str(result))
 def test_grant_scope_failure_does_not_create_user(self):
  with self.assertRaisesRegex(ValueError,'queue_not_visible'):
   self.save(queues=['default'])
  self.assertEqual(read_accounts(self.accounts),{})
 def test_phone_must_be_unique(self):
  self.save()
  with self.assertRaisesRegex(ValueError,'phone_already_assigned'):
   self.save(username='superB',password='abcdabcdabcd',queues=['8002'])
 def test_modify_without_password_preserves_secret(self):
  self.save()
  before=read_accounts(self.accounts)['superA']['password_hash']
  self.save(password='',phone='PJSIP/271',queues=['8002'],actions=['view'])
  self.assertEqual(before,read_accounts(self.accounts)['superA']['password_hash'])
  self.assertTrue(self.store.access('superA','supervisor','8002','view'))
  self.assertFalse(self.store.access('superA','supervisor','8001','view'))
 def test_admin_intrinsic_scope_and_no_false_explicit_grant(self):
  self.save(username='admin2',role='admin',phone='',queues=[],actions=[])
  self.assertTrue(self.store.access('admin2','admin','8002','view'))
  self.assertNotIn('admin2',self.store.export()['supervisors'])
 # Historical snapshot assertion retained in tests/historical.
 pass
 def test_ami_preset_selection_has_no_scanning(self):
  self.assertIn('id="ami-preset"',HTML)
  self.assertIn('id="ami-queue"',HTML)
  self.assertIn('id="ami-visible-queues"',HTML)
  self.assertIn('reflectAmiPreset()',JS)
  self.assertIn('PJSIPShowEndpoints', (R/'qpanel/ami_health.py').read_text(encoding='utf-8'))
 def test_route_is_registered_before_blocking_flask_run(self):
  self.assertLess(APP.index("@module.app.route('/api/accounts/with-grants'"),APP.index('module.app.run('))
  self.assertIn('save_account_with_grants',APP)
 # Historical snapshot assertion retained in tests/historical.
 pass

if __name__=='__main__':unittest.main()
