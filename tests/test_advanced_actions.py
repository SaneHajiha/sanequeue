import unittest
from sanequeue.actions.plans import plan
from sanequeue.realtime.state import QueueState


class PlansTests(unittest.TestCase):
    def setUp(self):
        self.state={'channels':{
            'agent':{'channel':'PJSIP/100-aaa','queues':['q'],'bridge':'b','channelstatedesc':'Up'},
            'caller':{'channel':'PJSIP/200-bbb','queues':['q'],'bridge':'b','channelstatedesc':'Up'}},
            'parked':{'default:701':{'queues':['q'],'parkinglot':'default','parkingspace':'701'}}}

    def test_transfer_and_park_use_exact_scoped_legs(self):
        name,fields=plan(self.state,'q','transfer','PJSIP/100-aaa',destination='300',extensions=['300'])
        self.assertEqual((name,fields['Channel'],fields['Exten']),('BlindTransfer','PJSIP/100-aaa','300'))
        name,fields=plan(self.state,'q','park','PJSIP/100-aaa')
        self.assertEqual((name,fields['Channel'],fields['TimeoutChannel']),('Park','PJSIP/200-bbb','PJSIP/100-aaa'))
        with self.assertRaises(ValueError):plan(self.state,'q','transfer','PJSIP/100-aaa',destination='0098999',extensions=['300'])
        self.state['channels']['caller']['queues']=['other']
        with self.assertRaises(ValueError):plan(self.state,'q','transfer','PJSIP/100-aaa',destination='300',extensions=['300'])
        with self.assertRaises(ValueError):plan(self.state,'q','park','PJSIP/100-aaa')

    def test_pickup_requires_ringing_and_own_phone_is_not_browser_supplied(self):
        with self.assertRaises(ValueError):plan(self.state,'q','pickup','PJSIP/100-aaa',own_phone='PJSIP/300')
        self.state['channels']['agent']['channelstatedesc']='Ringing'
        name,fields=plan(self.state,'q','pickup','PJSIP/100-aaa',own_phone='PJSIP/300')
        self.assertEqual(fields['Data'],'PJSIP/100-aaa');self.assertEqual(fields['Channel'],'PJSIP/300')
        with self.assertRaises(ValueError):plan(self.state,'q','pickup','PJSIP/100-aaa',own_phone='PJSIP/100')
        with self.assertRaises(ValueError):plan(self.state,'q','pickup','PJSIP/100-aaa',own_phone='Local/300@outside')

    def test_retrieve_and_click_to_call_reject_out_of_scope_or_non_internal_targets(self):
        name,fields=plan(self.state,'q','retrieve','default:701',own_phone='SIP/300')
        self.assertEqual((name,fields['Application'],fields['Data']),('Originate','ParkedCall','default,701'))
        self.state['parked']['default:701']['queues']=['q','private']
        with self.assertRaises(ValueError):plan(self.state,'q','retrieve','default:701',own_phone='SIP/300')
        name,fields=plan(self.state,'q','dial',destination='100',own_phone='SIP/300',extensions=['100'])
        self.assertEqual(fields['Exten'],'100')
        for target in ('100\r\nAction: Command','PJSIP/100','009821111','300'):
            with self.subTest(target=target),self.assertRaises(ValueError):plan(self.state,'q','dial',destination=target,own_phone='SIP/300',extensions=['100','300'])


class AdditionalEventTests(unittest.TestCase):
    def test_park_scope_survives_leave_and_is_removed_on_retrieve(self):
        state=QueueState()
        state.ingest(dict(Event='Newchannel',Uniqueid='u',Channel='PJSIP/1-aaa'))
        state.ingest(dict(Event='QueueCallerJoin',Queue='q',Uniqueid='u'))
        state.ingest(dict(Event='QueueCallerLeave',Queue='q',Uniqueid='u'))
        event=dict(ParkeeUniqueid='u',ParkeeChannel='PJSIP/1-aaa',Parkinglot='default',ParkingSpace='701')
        state.ingest(dict(event,Event='ParkedCall'))
        self.assertEqual(state.snapshot()['parked']['default:701']['queues'],['q'])
        state.ingest(dict(event,Event='UnParkedCall'))
        self.assertFalse(state.parked)

    def test_rtcp_units_and_missing_measurements_are_not_invented(self):
        state=QueueState()
        state.ingest(dict(Event='Newchannel',Uniqueid='u',Channel='PJSIP/1-aaa'))
        state.ingest(dict(Event='RTCPReceived',Uniqueid='u',RTT='.025',Report0FractionLost='16',Report0IAJitter='80',From='private-ip'))
        q=state.snapshot()['channels']['u']['rtcp']
        self.assertEqual(q['rtt_ms'],25);self.assertEqual(q['loss_pct'],6.25);self.assertEqual(q['jitter_ticks'],80)
        self.assertNotIn('private-ip',str(q))
        state.ingest(dict(Event='RTCPReceived',Uniqueid='u',RTT='nan'))
        self.assertIsNone(state.channels['u']['rtcp']['rtt_ms'])

    def test_snapshot_bridge_and_elapsed_duration_are_recovered_when_available(self):
        state=QueueState(clock=lambda:1000)
        for uid in ('a','b'):state.ingest(dict(Event='CoreShowChannel',Uniqueid=uid,Channel='PJSIP/'+uid,BridgeId='bridge',Duration='00:01:30'))
        self.assertEqual(state.channels['a']['bridge'],'bridge')
        self.assertEqual(state.channels['a']['created_at'],910)
        self.assertEqual(state.bridges['bridge'],{'a','b'})
