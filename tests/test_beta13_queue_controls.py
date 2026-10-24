"""Pure-Python regressions for queue visibility, AMI fields, and role scoping."""
import tempfile
from pathlib import Path
import unittest
from qpanel.queue_visibility import filter_queue_data, is_queue_visible, normalize_visible_queues
from qpanel.privacy import public_queue_snapshot
from qpanel.ami_live import parse_queue_events
from qpanel.local_accounts import bootstrap,read_accounts,set_account
from qpanel.test_control_gate import TestControlGate

class Beta13Regressions(unittest.TestCase):
    def test_all_real_queues_except_default(self):
        data={'default': {}, '8001': {'Completed':'1'}, '8002': {}, 'sales-north':{}}
        self.assertEqual(list(filter_queue_data(data,'!default')),['8001','8002','sales-north'])
        self.assertFalse(is_queue_visible('default','!default'))
        self.assertTrue(is_queue_visible('8002','!default'))
        self.assertEqual(normalize_visible_queues('!default'),'!default')
        self.assertIn('default',filter_queue_data(data,'*'))
    def test_queue_entry_explicit_ingress_and_sla(self):
        e=[{'Event':'QueueParams','Queue':'8002','Calls':'1','Completed':'2','ServiceLevelPerf':'0','ServiceLevel':'60','Holdtime':'106'},
           {'Event':'QueueEntry','Queue':'8002','Channel':'PJSIP/provider-00001','CallerIDNum':'09122223344','IngressTrunk':'incoming-ims','Wait':'15','Position':'1','Priority':'0'}]
        q=parse_queue_events(e,'8002')['8002']
        self.assertEqual(q['ServicelevelPerf'],'0')
        self.assertEqual(q['ServiceLevelSeconds'],'60')
        self.assertEqual(q['Holdtime'],'106')
        self.assertEqual(q['entries']['PJSIP/provider-00001']['SourceTrunk'],'incoming-ims')
    def test_missing_trunk_is_not_guessed(self):
        e=[{'Event':'QueueParams','Queue':'8002','Calls':'1'},
           {'Event':'QueueEntry','Queue':'8002','Channel':'PJSIP/abc-0002','CallerIDNum':'911','Wait':'1'}]
        q=parse_queue_events(e,'8002')['8002']
        self.assertEqual(q['entries']['PJSIP/abc-0002']['SourceTrunk'],'')
    def test_admin_caller_id_vs_viewer_mask(self):
        queues={'8002':{'members':{},'entries':{'PJSIP/sip-123':{'CallerIDNum':'09121112233','CallerIDName':'Customer','Channel':'PJSIP/sip-123','SourceTrunk':'inbound-1'}}}}
        admin=public_queue_snapshot(queues,privileged=True,reveal_numbers=True)
        self.assertEqual(admin['8002']['entries']['PJSIP/sip-123']['CallerIDNum'],'09121112233')
        viewer=public_queue_snapshot(queues,privileged=False,reveal_numbers=False)
        self.assertNotIn('PJSIP/sip-123',str(viewer))
        self.assertNotIn('09121112233',str(viewer))
    def test_bootstrap_admin_uses_own_phone(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'users.json'
            secret=bootstrap(p)
            self.assertTrue(secret)
            self.assertEqual(read_accounts(p)['admin']['phone'],'PJSIP/100')
    def test_existing_admin_phone_edit_keeps_hash(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'users.json';set_account(p,'admin','admin','', 'a-long-strong-password-123')
            before=read_accounts(p)['admin']['password_hash']
            set_account(p,'admin','admin','PJSIP/100',None)
            self.assertEqual(read_accounts(p)['admin']['password_hash'],before)
    def test_control_gate_requires_selected_queue(self):
        g=TestControlGate()
        ok=g.arm('ENABLE 8001',True,True,queue='8001',agents=['PJSIP/100'],owner_user='admin',owner_session='a'*32,allowed_actions=['priority'])
        self.assertTrue(ok)
        self.assertFalse(g.authorize('ops_control',{'action':'priority','queue':'8002','channel':'PJSIP/x'},True,True,owner_user='admin',owner_session='a'*32))
        self.assertTrue(g.authorize('ops_control',{'action':'priority','queue':'8001','channel':'PJSIP/x'},True,True,owner_user='admin',owner_session='a'*32))

if __name__=='__main__':unittest.main()
