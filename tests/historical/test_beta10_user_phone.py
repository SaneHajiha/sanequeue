"""Offline security/UX regression tests for beta.10; no PBX or Flask required."""
import tempfile
import unittest
from pathlib import Path
from hashlib import pbkdf2_hmac
from qpanel.local_accounts import bootstrap,read_accounts,set_account,hash_secret
from qpanel.queue_policies import DEFAULT_REASONS,QueuePolicyStore
from qpanel.ami_live import parse_queue_events
from qpanel.test_control_gate import TestControlGate

ROOT=Path(__file__).resolve().parents[1]

class Beta10IdentityTests(unittest.TestCase):
    def test_password_compatible_with_werkzeug_pbkdf2(self):
        stored=hash_secret('AnExampleOnlyStrongPass_1234')
        method,salt,digest=stored.split('$')
        self.assertEqual(pbkdf2_hmac('sha256',b'AnExampleOnlyStrongPass_1234',salt.encode(),int(method.split(':')[-1])).hex(),digest)
        self.assertNotIn('AnExampleOnlyStrongPass_1234',stored)
    def test_bootstrap_once_hash_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'accounts.json'
            initial=bootstrap(path)
            self.assertTrue(initial)
            self.assertIsNone(bootstrap(path))
            self.assertNotIn(initial,path.read_text(encoding='utf-8'))
            self.assertIn('admin',read_accounts(path))
    def test_multiple_distinct_phone_bindings(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'accounts.json'
            set_account(path,'ali','supervisor','PJSIP/101','StrongExamplePassword_123')
            set_account(path,'sara','supervisor','PJSIP/201','StrongExamplePassword_456')
            self.assertEqual(read_accounts(path)['ali']['phone'],'PJSIP/101')
            self.assertEqual(read_accounts(path)['sara']['phone'],'PJSIP/201')
    def test_invalid_identity_cannot_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'accounts.json'
            for phone in ('PJSIP/101;rm -rf','SIP/100\nBad','http://google.com'):
                with self.assertRaises(ValueError):set_account(path,'ali','supervisor',phone,'StrongPassword_12345')
            self.assertFalse(path.exists())
    def test_supervisor_requires_phone(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):set_account(Path(tmp)/'x.json','sup','supervisor','','StrongPassword_123456')
    def test_existing_user_password_preserved_on_profile_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'accounts.json'
            set_account(path,'sup','supervisor','PJSIP/101','StrongPassword_123456')
            before=read_accounts(path)['sup']['password_hash']
            set_account(path,'sup','supervisor','PJSIP/102',None)
            self.assertEqual(read_accounts(path)['sup']['password_hash'],before)
    def test_no_default_survey_reason(self):
        self.assertNotIn('survey',[v['id'] for v in DEFAULT_REASONS])
    def test_old_survey_reason_filtered_on_loading(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=QueuePolicyStore(Path(tmp)/'policies.json')
            data=store.export();data['queues']['8001']=store.queue('8001')
            data['queues']['8001']['pause_reasons'].append({'id':'survey','label':'Old survey'})
            store.replace(data,visible_queues={'8001'})
            self.assertNotIn('survey',[r['id'] for r in store.reasons('8001')])
    def test_scope_never_permits_global_write(self):
        gate=TestControlGate()
        self.assertFalse(gate.arm('ENABLE *',True,True,queue='*',agents={'PJSIP/100'}))
        self.assertTrue(gate.arm('ENABLE 8001',True,True,queue='8001',agents={'PJSIP/100'}))
        self.assertFalse(gate.authorize('ops_control',{'queue':'8002','action':'spy','agent':'PJSIP/100'},True,True))
        self.assertTrue(gate.authorize('ops_control',{'queue':'8001','action':'spy','agent':'PJSIP/100'},True,True))
        self.assertFalse(gate.authorize('ops_control',{'queue':'8001','action':'spy','agent':'PJSIP/100','destination':'PJSIP/201'},True,True))
    def test_adapter_preserves_queue_holdtime(self):
        events=[{'Event':'QueueParams','Queue':'8001','Calls':'0','Completed':'5','Abandoned':'3','Holdtime':'22','TalkTime':'26','ServicelevelPerf':'60'}]
        q=parse_queue_events(events,'8001')['8001'];self.assertEqual(q['Holdtime'],'22');self.assertEqual(q['TalkTime'],'26')
    def test_frontend_has_multi_queue_summary_and_one_row_operations(self):
        js=(ROOT/'qpanel/themes/qpanel/static/js/operations.js').read_text(encoding='utf-8')
        css=(ROOT/'qpanel/themes/qpanel/static/css/operations.css').read_text(encoding='utf-8')
        self.assertIn('queue-mini-summary',js)
        self.assertIn('queueMean(q,\'Holdtime\')',js)
        self.assertIn('flex-wrap:nowrap',css)
        self.assertNotIn("id:'survey'",js)
    def test_server_uses_bound_phone_only(self):
        source=(ROOT/'qpanel/operations.py').read_text(encoding='utf-8')
        self.assertIn('destination=allowed[0]',source)
        self.assertIn('destination_not_allowed',source)
        self.assertIn('agent_not_in_active_call',source)
        self.assertIn('assigned_phone',source)
    def test_demo_autologin_removed(self):
        source=(ROOT/'demo_monitor.py').read_text(encoding='utf-8')
        self.assertNotIn("session['_user_id'] = 'demo'",source)
        self.assertIn('bootstrap(ACCOUNTS_PATH)',source)
        self.assertIn('enforce_authenticated_admin_settings',source)

if __name__=='__main__':unittest.main()
