import unittest
from sanequeue.pbx.events import CallbackEvents
from sanequeue.realtime.state import QueueState

class CallbackEvidenceTests(unittest.TestCase):
    def test_actual_target_bridge_and_source_hangup_are_separate_from_acceptance(self):
        clock=[100];state=QueueState(clock=lambda:clock[0]);tracker=CallbackEvents()
        def send(kind,**values):
            packet=dict(Event=kind,**values);state.ingest(packet);tracker.observe(packet,state);clock[0]+=1
        send('Newchannel',Uniqueid='s',Channel='PJSIP/300-000abc',ChannelStateDesc='Up')
        send('OriginateResponse',ActionID='sq-cb-test',Response='Success',Uniqueid='s',Exten='100')
        self.assertNotIn('connected_at',state.action_events['sq-cb-test'])
        send('Newchannel',Uniqueid='t',Channel='PJSIP/100-000def',ChannelStateDesc='Up')
        send('BridgeEnter',Uniqueid='s',Channel='PJSIP/300-000abc',BridgeUniqueid='bridge')
        send('BridgeEnter',Uniqueid='t',Channel='PJSIP/100-000def',BridgeUniqueid='bridge')
        row=state.action_events['sq-cb-test'];self.assertEqual(row['connected_at'],104)
        send('Hangup',Uniqueid='s',Channel='PJSIP/300-000abc');self.assertEqual(row['ended_at'],105)
    def test_other_phone_bridge_is_not_proof_target_answered(self):
        state=QueueState();tracker=CallbackEvents()
        for event in (dict(Event='OriginateResponse',ActionID='sq-cb-test',Response='Success',Uniqueid='s',Exten='100'),dict(Event='Newchannel',Uniqueid='s',Channel='PJSIP/300-000abc'),dict(Event='Newchannel',Uniqueid='t',Channel='PJSIP/200-000def'),dict(Event='BridgeEnter',Uniqueid='s',BridgeUniqueid='b'),dict(Event='BridgeEnter',Uniqueid='t',BridgeUniqueid='b')):
            state.ingest(event);tracker.observe(event,state)
        self.assertNotIn('connected_at',state.action_events['sq-cb-test'])
