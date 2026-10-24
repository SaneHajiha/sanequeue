import concurrent.futures
import tempfile
import time
import unittest
from pathlib import Path
from qpanel.snapshot_cache import SnapshotCache
from qpanel.compatibility import spy_target
from qpanel.ami_live import parse_queue_events
from qpanel.local_accounts import set_account, read_accounts


class SharedCollectionTests(unittest.TestCase):
    def test_concurrent_viewers_collect_once_and_receive_copies(self):
        cache=SnapshotCache(ttl=5)
        calls=[]
        def collect():
            calls.append(1);time.sleep(.01)
            return {'queue':{'Calls':2}}
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
            results=list(pool.map(lambda _:cache.get('pbx',collect),range(100)))
        self.assertEqual(len(calls),1)
        results[0][0]['queue']['Calls']=99
        self.assertEqual(results[1][0]['queue']['Calls'],2)

    def test_failure_backoff_and_fresh_control_snapshot(self):
        now=[10.0];cache=SnapshotCache(clock=lambda:now[0]);calls=[]
        def fail():calls.append(1);raise OSError('offline')
        for _ in range(20):
            with self.assertRaises((OSError,RuntimeError)):cache.get('pbx',fail)
        self.assertEqual(len(calls),1)
        now[0]+=3
        cache.get('pbx',lambda:{'ok':True})
        cache.get('pbx',lambda:{'ok':False},fresh=True)
        self.assertEqual(cache.collections,3)
        self.assertFalse(cache.data['ok'])


class DriverCompatibilityTests(unittest.TestCase):
    def test_asterisk_16_18_20_member_variants(self):
        for major,field,interface in [(16,'Location','SIP/100'),(18,'Interface','PJSIP/100'),(20,'Location','Local/100@from-queue/n')]:
            with self.subTest(asterisk=major):
                data=parse_queue_events([{'Event':'QueueParams','Queue':'8001','Calls':'0'}, {'Event':'QueueMember','Queue':'8001',field:interface,'Status':'1','Name':'Test'}],'8001')
                self.assertIn(interface,data['8001']['members'])

    def test_hint_is_resolved_from_actual_driver(self):
        for tech in ('SIP','PJSIP'):
            target=tech+'/100-0000abcd'
            self.assertEqual(spy_target({'StateInterface':'hint:100@ext-local'},'Local/100@from-queue/n',[{'Channel':target}]),target)
        with self.assertRaises(ValueError):spy_target({'StateInterface':'hint:100@ext-local'},'Local/100@from-queue/n',[])
        with self.assertRaises(ValueError):spy_target({'StateInterface':'hint:100@ext-local'},'Local/100@from-queue/n',[{'Channel':'SIP/100-aaaa'},{'Channel':'PJSIP/100-bbbb'}])

    def test_explicit_mapping_and_injection(self):
        self.assertEqual(spy_target({'StateInterface':'hint:100@ext-local'},'',overrides={'100':'SIP/100'}),'SIP/100')
        with self.assertRaises(ValueError):spy_target({'StateInterface':'SIP/100\r\nAction:Hangup'},'')


class AccountIntegrityTests(unittest.TestCase):
    def test_last_admin_and_duplicate_phone_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'accounts.json'
            set_account(p,'admin','admin','PJSIP/300','test-only-password-123')
            with self.assertRaises(ValueError):set_account(p,'admin','viewer','','')
            with self.assertRaises(ValueError):set_account(p,'other','supervisor','PJSIP/300','test-only-password-123')
            self.assertEqual(read_accounts(p)['admin']['role'],'admin')


class PlanningIntegrityTests(unittest.TestCase):
    def test_scope_overlap_and_timezone(self):
        from qpanel.planning import PlanningStore
        with tempfile.TemporaryDirectory() as tmp:
            store=PlanningStore(Path(tmp)/'planning.sqlite3')
            shift={'queue':'8001','agent':'agent1','starts':'2026-10-24T09:00:00+03:30','ends':'2026-10-24T17:00:00+03:30'}
            store.save('shifts',shift,['8001'])
            self.assertEqual(len(store.list('shifts',['8001'])),1)
            self.assertEqual(store.list('shifts',['8002']),[])
            with self.assertRaises(ValueError):store.save('shifts',dict(shift,queue='8002'),['8002'])
            with self.assertRaises(ValueError):store.save('shifts',dict(shift,starts='2026-10-24T09:00:00'),['8001'])
            with self.assertRaises(PermissionError):store.save('shifts',dict(shift,id=1,queue='8002',delete=True),['8002'])
            self.assertEqual(len(store.list('shifts',['8001'])),1)

    def test_contact_validation_and_delete_scope(self):
        from qpanel.planning import PlanningStore
        with tempfile.TemporaryDirectory() as tmp:
            store=PlanningStore(Path(tmp)/'planning.sqlite3')
            data={'queue':'8001','name':'Test','phone':'+98 21 12345678'}
            store.save('directory',data,['8001'])
            with self.assertRaises(ValueError):store.save('directory',dict(data,phone='x\r\nAction:Hangup'),['8001'])
            with self.assertRaises(PermissionError):store.save('directory',dict(data,id=1,queue='8002',delete=True),['8002'])
            store.save('directory',dict(data,id=1,delete=True),['8001'])
            self.assertEqual(store.list('directory',['8001']),[])
