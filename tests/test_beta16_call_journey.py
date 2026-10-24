import unittest
from qpanel.call_journey import JourneyEngine
from qpanel.call_journey_listener import parse_trunk_map


class CallJourneyTests(unittest.TestCase):
    def setUp(self):
        self.time=1000
        self.j=JourneyEngine({'PJSIP/ims-in-':'IMS trunk'},clock=lambda:self.time)
    def send(self,event,**fields):
        self.j.ingest({'Event':event,**fields}, now=self.time)
        self.time+=1
    def visible(self,scope=('8002',),numbers=True,wallboard=False):
        return self.j.snapshot(scope,numbers=numbers,wallboard=wallboard,now=self.time)
    def test_blind_transfer_traced_until_all_legs_hangup(self):
        self.j.mark_connection(True)
        self.send('Newchannel', Channel='PJSIP/ims-in-0001',Uniqueid='1000.1',Linkedid='1000.1',Context='from-trunk',CallerIDNum='09121234567')
        self.send('QueueCallerJoin', Channel='PJSIP/ims-in-0001',Uniqueid='1000.1',Linkedid='1000.1',Queue='8002',CallerIDNum='09121234567')
        self.send('AgentCalled',Channel='PJSIP/ims-in-0001',Linkedid='1000.1', Queue='8002',MemberName='200')
        self.send('AgentConnect',Channel='PJSIP/ims-in-0001',Linkedid='1000.1',Queue='8002',MemberName='200',DestChannel='PJSIP/200-0002',DestUniqueid='1000.2')
        self.send('QueueCallerLeave',Channel='PJSIP/ims-in-0001',Linkedid='1000.1',Queue='8002')
        self.send('BlindTransfer',Result='Success',TransfereeChannel='PJSIP/ims-in-0001',TransfereeLinkedid='1000.1',Extension='270')
        r=self.visible()['records'][0]
        self.assertEqual(r['trunk'],'IMS trunk')
        self.assertTrue(r['trunk_verified'])
        self.assertEqual(r['destination'],'270')
        self.assertEqual(r['status'],'transferred')
        self.send('Hangup',Channel='PJSIP/200-0002',Linkedid='1000.1')
        self.send('DialBegin',Channel='PJSIP/ims-in-0001',Linkedid='1000.1',DestChannel='PJSIP/270-0003',DestUniqueid='1000.3')
        self.send('Newstate',Channel='PJSIP/270-0003',Linkedid='1000.1',ChannelStateDesc='Ringing')
        self.assertEqual(self.visible()['records'][0]['status'],'post_transfer_ringing')
        self.send('BridgeEnter',Channel='PJSIP/270-0003',Linkedid='1000.1',BridgeUniqueid='bridge-1')
        self.assertNotEqual(self.visible()['records'][0]['status'],'post_transfer_talking')
        self.send('BridgeEnter',Channel='PJSIP/ims-in-0001',Linkedid='1000.1',BridgeUniqueid='bridge-1')
        self.assertEqual(self.visible()['records'][0]['status'],'post_transfer_talking')
        self.assertEqual(self.visible()['records'][0]['destination'],'270')
        self.send('Hangup',Channel='PJSIP/270-0003',Linkedid='1000.1')
        self.assertNotEqual(self.visible()['records'][0]['status'],'ended')
        self.send('Hangup',Channel='PJSIP/ims-in-0001',Linkedid='1000.1')
        self.time+=6
        r=self.visible()['records'][0]
        self.assertEqual(r['status'],'ended')
        self.assertTrue(r['ended_at'])
        self.assertGreaterEqual(len(r['timeline']),5)
        self.assertNotIn('1000.1',str(r))
        self.assertNotIn('PJSIP/ims-in-0001',str(r))
    def test_attended_transfer_and_unanswered_destination_not_falsely_confirmed(self):
        self.send('QueueCallerJoin',Channel='PJSIP/trunk-0001',Uniqueid='88',Linkedid='88',Queue='8001')
        self.send('AgentConnect',Channel='PJSIP/trunk-0001',Linkedid='88',Queue='8001',MemberName='100')
        self.send('AttendedTransfer',Result='Success',TransfereeChannel='PJSIP/trunk-0001',TransfereeLinkedid='88',OrigTransfererChannel='PJSIP/100-01')
        self.assertEqual(self.visible(('8001',))['records'][0]['status'],'transferred')
        self.assertNotEqual(self.visible(('8001',))['records'][0]['status'],'post_transfer_talking')
    def test_failed_transfer_cannot_be_reported_as_success(self):
        self.send('QueueCallerJoin',Channel='PJSIP/in-01',Linkedid='77',Queue='8001')
        self.send('BlindTransfer',Result='Fail',TransfereeChannel='PJSIP/in-01',TransfereeLinkedid='77',Extension='202')
        r=self.visible(('8001',))['records'][0]
        self.assertEqual(r['status'],'transfer_failed')
        self.assertEqual(r['transfers'],0)
    def test_queue_permission_and_numbers_are_enforced(self):
        self.send('QueueCallerJoin',Channel='PJSIP/in-01',Linkedid='99',Queue='8002',CallerIDNum='09121234567')
        self.assertEqual(self.visible(('8001',))['records'],[])
        r=self.visible(numbers=False)['records'][0]
        self.assertEqual(r['caller'],'')
        self.assertNotIn('09121234567',str(self.visible(numbers=False)))
        self.assertEqual(self.visible(wallboard=True)['records'][0]['caller'],'')
        self.assertEqual(self.visible()['records'][0]['caller'],'09121234567')
    def test_cross_queue_trace_cannot_leak_into_partial_scope(self):
        self.send('QueueCallerJoin',Channel='PJSIP/in-01',Linkedid='cross1',Queue='8001',CallerIDNum='09127778888')
        self.send('QueueCallerJoin',Channel='PJSIP/in-01',Linkedid='cross1',Queue='8002')
        self.assertEqual(self.visible(('8001',))['records'],[])
        self.assertEqual(self.visible(('8002',))['records'],[])
        allowed=self.visible(('8001','8002'))['records'][0]
        self.assertEqual(sorted(allowed['queues']),['8001','8002'])
    def test_queue_caller_entry_starts_with_ingress_even_if_not_verified(self):
        self.send('QueueCallerJoin',Channel='PJSIP/in-01',Linkedid='no-trunk',Queue='8002')
        self.assertEqual(self.visible()['records'][0]['timeline'][0]['state'],'ingress')
        self.assertEqual(self.visible()['records'][0]['timeline'][0]['detail'],'unknown')
    def test_system_default_never_is_a_visible_journey(self):
        self.send('QueueCallerJoin',Channel='PJSIP/test-11',Linkedid='11',Queue='default')
        self.assertEqual(self.visible(('default',))['records'],[])
    def test_unverified_trunk_cannot_be_claimed_verified(self):
        self.send('Newchannel',Channel='PJSIP/maybe-0001',Linkedid='41',Context='from-trunk')
        self.send('QueueCallerJoin',Channel='PJSIP/maybe-0001',Linkedid='41',Queue='8002')
        r=self.visible()['records'][0]
        self.assertEqual(r['trunk'],'')
        self.assertEqual(r['ingress_hint'],'maybe')
        self.assertFalse(r['trunk_verified'])
    def test_reconnect_and_bound(self):
        self.j.max_calls=5
        for i in range(12):
            self.send('QueueCallerJoin',Channel=f'PJSIP/in-{i}',Linkedid=str(i),Queue='8002')
        self.assertLessEqual(len(self.j.traces),5)
        self.j.mark_connection(False)
        self.assertFalse(self.visible()['connected'])
    def test_trunk_map_rejects_untrusted_oversized_or_wrong_endpoint(self):
        self.assertEqual(parse_trunk_map('{"http://fake":"bogus"}'),{})
        self.assertEqual(parse_trunk_map('{"PJSIP/ims-in-":"SIP IMS"}'),{'PJSIP/ims-in-':'SIP IMS'})
        self.assertEqual(parse_trunk_map('not-json'),{})

if __name__ == '__main__':unittest.main()
