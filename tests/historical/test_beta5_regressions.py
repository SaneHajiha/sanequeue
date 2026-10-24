"""Standalone regression tests. No actual PBX commands are emitted."""
import unittest
from pathlib import Path
from unittest.mock import patch

from qpanel.ami_targets import validate_target
from qpanel.ami_live import parse_queue_events
from qpanel.ami_health import _unavailable_reason, parse_health, read_capabilities, read_health

ROOT = Path(__file__).resolve().parents[1]

class FakeAMI:
    packets = []
    actions = []
    def __init__(self, host, port, timeout=6):
        self.host,self.port = host,port
        self.sock=self
        self.actions=[]
        self.packets=iter(type(self).packets)
    def login(self,user,password): return True
    def settimeout(self,value): pass
    def send(self,**kw): self.actions.append(kw)
    def read_packet(self): return next(self.packets)
    def close(self): pass

class Beta5(unittest.TestCase):
    def test_monitors_all_queues(self):
        events=[{'Event':'QueueParams','Queue':'8001','Calls':'1'},
                {'Event':'QueueMember','Queue':'8001','Location':'PJSIP/100','Status':'1'},
                {'Event':'QueueParams','Queue':'8002','Calls':'2'},
                {'Event':'QueueMember','Queue':'8002','Location':'PJSIP/200','Status':'5'},
                {'Event':'QueueEntry','Queue':'8002','Channel':'PJSIP/a1','Wait':'4'}]
        result=parse_queue_events(events,'*')
        self.assertEqual(set(result),{'8001','8002'})
        self.assertEqual(result['8002']['Calls'],'1')
        self.assertEqual(result['8001']['Calls'],'1')
        self.assertEqual(result['8002']['members']['PJSIP/200']['Status'],'5')
    def test_read_wildcard_valid_but_public_ip_blocked(self):
        self.assertEqual(validate_target('192.168.2.2',5038,'*')[2],'*')
        self.assertEqual(validate_target('127.0.0.1',15038,'*')[2],'*')
        with self.assertRaises(ValueError):validate_target('8.8.8.8',5038,'*')
        with self.assertRaises(ValueError):validate_target('127.0.0.1',5038,'*;Originate')
    def test_denial_errors_are_classified_and_redacted(self):
        self.assertEqual(_unavailable_reason('Permission denied'),'action_permission_denied')
        self.assertEqual(_unavailable_reason('Invalid/unknown action'),'action_or_module_unavailable')
        self.assertEqual(_unavailable_reason('internal secret value is wrong'),'ami_action_rejected')
    def test_capabilities_list_is_filtered(self):
        FakeAMI.packets=[{'Response':'Success','QueueStatus':'Queue status','CoreShowChannels':'Channels','Hangup':'Hangup','Secret':'NEVER_RETURN'}]
        with patch('qpanel.ami_health.ReadOnlyAMI', FakeAMI):
            result=read_capabilities('127.0.0.1',15038,'sq','SECRET','*')
        self.assertTrue(result['supported'])
        self.assertTrue(result['actions']['CoreShowChannels'])
        self.assertFalse(result['actions']['PJSIPShowEndpoints'])
        self.assertNotIn('Secret',repr(result))
    def test_health_fails_with_distinct_reason(self):
        FakeAMI.packets=[{'Response':'Error','Message':'Permission denied'}]
        with patch('qpanel.ami_health.ReadOnlyAMI', FakeAMI):
            result=read_health('127.0.0.1',15038,'sq','SECRET','*','channels')
        self.assertFalse(result['supported'])
        self.assertEqual(result['reason'],'action_permission_denied')
    def test_health_success_counters_without_numbers(self):
        FakeAMI.packets=[{'Response':'Success','ActionID':'arbitrary'},
                         {'Event':'CoreShowChannel','Channel':'PJSIP/100-1','CallerIDNum':'09129998888','ChannelStateDesc':'Up'},
                         {'Event':'CoreShowChannelsComplete'}]
        with patch('qpanel.ami_health.ReadOnlyAMI', FakeAMI):
            result=read_health('127.0.0.1',15038,'sq','SECRET','*','channels')
        self.assertTrue(result['supported'])
        self.assertEqual(result['data']['channel_legs'],1)
        self.assertNotIn('09129998888',repr(result))
    def test_pjsip_contacts_redact_addresses(self):
        out=parse_health('contacts',[{'Status':'Avail','Uri':'sip:100@192.168.2.2','UserAgent':'private'}])
        self.assertEqual(out,{'contacts':1,'available':1})
        self.assertNotIn('192.168.',repr(out))
    def test_light_theme_and_port(self):
        css=(ROOT/'qpanel/themes/qpanel/static/css/operations.css').read_text(encoding='utf-8')
        html=(ROOT/'qpanel/themes/qpanel/templates/operations.html').read_text(encoding='utf-8')
        self.assertIn('body:not(.dark) .detail-hero',css)
        self.assertIn('data-pbx-check="permissions"',html)
        self.assertIn('data-pbx-check="contacts"',html)
        self.assertIn('18887',(ROOT/'START_SANEQUEUE_KEEP_OPEN_18887.cmd').read_text(encoding='utf-8'))

if __name__=='__main__':unittest.main()

class ScopedWrites(unittest.TestCase):
    def test_explicit_queue_confirmation_required_and_expires(self):
        from qpanel.test_control_gate import TestControlGate
        g=TestControlGate()
        self.assertFalse(g.arm('ENABLE *',True,True,queue='*',agents={'PJSIP/101'}))
        self.assertFalse(g.arm('ENABLE 8001',True,True,queue='8002',agents={'PJSIP/200'}))
        self.assertTrue(g.arm('ENABLE 8002',True,True,queue='8002',agents={'PJSIP/200'}))
        self.assertTrue(g.authorize('pause_member',{'queue':'8002','agent':'PJSIP/200','paused':'true'},True,True))
        self.assertFalse(g.authorize('pause_member',{'queue':'8001','agent':'PJSIP/200','paused':'true'},True,True))
        self.assertFalse(g.authorize('pause_member',{'queue':'8002','agent':'PJSIP/100','paused':'true'},True,True))
        g.disarm()
        self.assertFalse(g.authorize('pause_member',{'queue':'8002','agent':'PJSIP/200','paused':'true'},True,True))
    def test_write_scope_is_not_inferred_from_all_queues_read(self):
        from qpanel.test_control_gate import TestControlGate
        g=TestControlGate()
        self.assertFalse(g.arm('ENABLE *',True,True,queue='*',agents={'PJSIP/100'}))
