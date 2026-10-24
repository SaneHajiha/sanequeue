"""Offline tests for SaneQueue 2.1.0-beta.3 LAN AMI and honest monitoring."""
from __future__ import annotations
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from qpanel.ami_targets import validate_target
from qpanel.ami_live import parse_queue_events, read_queue_data
from qpanel.ami_health import parse_health, read_health
from qpanel.test_control_gate import TestControlGate


class TargetTests(unittest.TestCase):
    def test_ssh_tunnel(self): self.assertEqual(validate_target('127.0.0.1', 15038, '8001'), ('127.0.0.1', 15038, '8001'))
    def test_localhost(self): self.assertEqual(validate_target('localhost', 5038, '8001')[0], '127.0.0.1')
    def test_direct_pbx(self): self.assertEqual(validate_target('192.168.2.2', '5038', '8001')[0], '192.168.2.2')
    def test_other_rfc1918(self):
        for host in ('10.1.2.3','172.20.0.9'):
            self.assertEqual(validate_target(host, 5038, 'sales-main')[0], host)
    def test_public_ip_denied(self):
        for host in ('8.8.8.8','1.1.1.1','169.254.169.254','0.0.0.0','127.0.0.2','example.com','::1'):
            with self.subTest(host=host),self.assertRaises(ValueError): validate_target(host,5038,'8001')
    def test_port_validation(self):
        for port in ('0','65536','oops'):
            with self.subTest(port=port),self.assertRaises(ValueError):validate_target('192.168.2.2',port,'8001')
    def test_queue_input(self):
        for queue in ('','../sales','foo\r\nSecret: wow','a'*33):
            with self.subTest(queue=queue),self.assertRaises(ValueError):validate_target('127.0.0.1',5038,queue)
    def test_multiple_queue_names(self):
        for queue in ('8001','9005','sales_2026'):
            self.assertEqual(validate_target('192.168.2.2',5038,queue)[2],queue)


class QueueParseTests(unittest.TestCase):
    @staticmethod
    def packets(queue='9005'):
        return [dict(Event='QueueParams',Queue=queue,Calls='1',Completed='3',Abandoned='0',Strategy='ringall',Holdtime='12',TalkTime='65'),
                dict(Event='QueueMember',Queue=queue,Location='Local/100@from-queue/n',Name='test',Status='1',Membership='static',Paused='0'),
                dict(Event='QueueEntry',Queue=queue,Channel='PJSIP/test-00001',CallerIDNum='5550001234',Wait='30',Position='1',Priority='0')]
    def test_parse_other_queue(self):
        result=parse_queue_events(self.packets(),'9005')
        self.assertEqual(list(result),['9005'])
        self.assertEqual(result['9005']['Calls'],'1')
        self.assertEqual(result['9005']['members']['Local/100@from-queue/n']['Status'],'1')
    def test_off_queue_excluded(self):
        result=parse_queue_events(self.packets('9005')+self.packets('8001'),'9005')
        self.assertEqual(list(result),['9005'])
    def test_missing_queue_errors(self):
        with self.assertRaises(RuntimeError): parse_queue_events([], '9005')
    def test_native_reader_direct_host(self):
        class FakeAMI:
            def __init__(self,host,port,timeout):self.host=host;self.sock=self
            def login(self,*args):return True
            def settimeout(self,*args): pass
            def send(self,**args):self.action=args
            def read_packet(self):return self.events.pop(0)
            def close(self):pass
        FakeAMI.events=self.packets('9005')+[{'Event':'QueueStatusComplete','ActionID':'sq-live-queue'}]
        with patch('AMI_READONLY_TEST.ReadOnlyAMI',FakeAMI):
            result=read_queue_data('192.168.2.2',5038,'sq','redacted','9005')
        self.assertEqual(result['9005']['Calls'],'1')
    def test_native_reader_scope(self):
        with self.assertRaises(ValueError):read_queue_data('8.8.8.8',5038,'sq','redacted','9005')


class HealthTests(unittest.TestCase):
    def test_channel_leg_label(self):
        data=parse_health('channels',[{'ChannelStateDesc':'Up','Channel':'PJSIP/100-xyz','CallerIDNum':'SECRET'},
                     {'ChannelStateDesc':'Ringing','Channel':'Local/a'}])
        self.assertEqual(data['channel_legs'],2)
        self.assertEqual(data['up'],1)
        self.assertNotIn('SECRET',str(data))
    def test_pjsip_counts(self):
        data=parse_health('extensions',[{'ObjectName':'100','DeviceState':'Not in use','Contact':'10.0.0.1'},
                    {'ObjectName':'101','DeviceState':'Unavailable'}])
        self.assertEqual(data['total'],2)
        self.assertEqual(data['available'],1)
        self.assertNotIn('10.0.0.1',str(data))
    def test_parked_data_redacted(self):
        result=parse_health('parking',[{'ParkingSpace':'701','ParkeeCallerIDNum':'SECRET'}])
        self.assertEqual(result,{'parked_calls':1,'spaces':['701']})
    def test_unknown_action_denied(self):
        with self.assertRaises(ValueError):read_health('192.168.2.2',5038,'sq','redacted','8001','Originate')


class SupervisorTests(unittest.TestCase):
    def test_control_needs_arming(self):
        g=TestControlGate()
        self.assertFalse(g.authorize('pause_member',{'queue':'8001','agent':'PJSIP/100','paused':'true'},True,True))
    # Historical snapshot assertion retained in tests/historical.
    pass
    def test_built_source_components(self):
        html=(ROOT/'qpanel/themes/qpanel/templates/operations.html').read_text(encoding='utf-8')
        js=(ROOT/'qpanel/themes/qpanel/static/js/operations.js').read_text(encoding='utf-8')
        self.assertIn('id="trend-wait"',html)
        self.assertIn('id="feature-catalog"',html)
        self.assertIn('id="pbx-health-results"',html)
        self.assertIn('data-pbx-check="channels"',html)
        self.assertIn('function updateSamples',js)
        self.assertIn('192.168.2.2',html)

if __name__=='__main__':unittest.main()
