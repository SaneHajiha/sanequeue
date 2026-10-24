from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile,unittest
from qpanel.local_accounts import set_account,delete_account,canonical_username,read_accounts,write_accounts
from qpanel.queue_policies import QueuePolicyStore
from sanequeue.security.login import LoginLimiter

class IdentityLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.path=self.root/'accounts.json'

    def test_successful_users_behind_nat_do_not_consume_failed_login_budget(self):
        limiter=LoginLimiter(clock=lambda:100)
        for index in range(200):
            ticket=limiter.reserve('192.0.2.1','user'+str(index));self.assertIsNotNone(ticket);limiter.success(ticket)
        self.assertEqual(len(limiter.attempts),0)
        for _ in range(20):self.assertIsNotNone(limiter.reserve('192.0.2.1','victim'))
        self.assertIsNone(limiter.reserve('192.0.2.1','VICTIM'))
        self.assertIsNotNone(limiter.reserve('192.0.2.1','another_user'))

    def test_source_failure_budget_and_expiry_are_bounded(self):
        now=[100];limiter=LoginLimiter(clock=lambda:now[0])
        for index in range(100):self.assertIsNotNone(limiter.reserve('192.0.2.1','random'+str(index)))
        self.assertIsNone(limiter.reserve('192.0.2.1','valid_user'))
        now[0]+=301;self.assertIsNotNone(limiter.reserve('192.0.2.1','valid_user'))

    def test_case_variant_resolves_to_same_identity_and_menu_policy(self):
        set_account(self.path,'Alice','admin','','Synthetic-password-123',menus=['queues'])
        self.assertEqual(canonical_username(self.path,'ALICE'),'Alice')
        self.assertIsNone(canonical_username(self.path,'missing'))
        account=read_accounts(self.path)[canonical_username(self.path,'alice')]
        self.assertEqual(account['menus'],['queues'])

    def test_deletion_and_parallel_edits_preserve_other_users_and_remove_grants(self):
        for name in ('admin','victim','other'):set_account(self.path,name,'admin' if name=='admin' else 'viewer','','Synthetic-password-123')
        store=QueuePolicyStore(self.root/'policies.json')
        store.replace({'queues':{'8001':{}},'supervisors':{'victim':{'queues':['8001'],'actions':['view']}}})
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(delete_account,self.path,'victim','admin',lambda:store.remove_subject('victim'))
            b=pool.submit(set_account,self.path,'other','viewer','')
            a.result();b.result()
        self.assertEqual(set(read_accounts(self.path)),{'admin','other'})
        self.assertNotIn('victim',store.export()['supervisors'])
        with self.assertRaisesRegex(ValueError,'cannot_delete_self'):delete_account(self.path,'admin','admin')
        with self.assertRaisesRegex(ValueError,'last_admin'):delete_account(self.path,'admin','other')

    def test_account_limit_rejects_before_corrupting_readable_registry(self):
        registry={f'user{index}':dict(role='viewer',phone='',password_hash='pbkdf2:sha256:synthetic') for index in range(100)}
        write_accounts(self.path,registry)
        with self.assertRaisesRegex(ValueError,'account_limit_reached'):set_account(self.path,'overflow','viewer','','Synthetic-password-123')
        self.assertEqual(len(read_accounts(self.path)),100)
