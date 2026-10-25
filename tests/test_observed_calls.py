"""Events prove measured durations; queue membership never duplicates global calls."""
import asyncio,tempfile,unittest
from datetime import datetime
from pathlib import Path
from sanequeue.realtime.calls import CallRecorder,CallStore

class CallsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.store=CallStore(Path(self.tmp.name)/'calls.sqlite3');self.rec=CallRecorder(self.store,Path(self.tmp.name)/'absent.json');self.rec.phones={'PJSIP/100':'100','PJSIP/200':'200'};self.start=datetime.fromisoformat('2026-10-25T08:00:00+03:30').timestamp()
        self.queues={q:{'params':{'servicelevel':'60'},'members':{'Local/100@from-queue/n':{'paused':'1','pausedreason':'survey'}}} for q in ('8001','8002')}
    def event(self,kind,seconds,**values):self.rec.ingest(dict(Event=kind,**values),self.queues,self.start+seconds)
    def test_outbound_manual_survey_attribution_dedup_and_unknown_hangup(self):
        self.event('DialBegin',0,Uniqueid='out',Linkedid='out',Channel='PJSIP/100-000abc',DestUniqueid='dest',DialString='PJSIP/trunk/09121234567')
        self.event('DialEnd',3,Uniqueid='out',DialStatus='ANSWER')
        self.event('Hold',5,Uniqueid='out');self.event('Unhold',7,Uniqueid='out');self.event('Hangup',13,Uniqueid='out')
        asyncio.run(self.rec.flush());data=self.store.daily(['8001','8002'],'2026-10-25')
        self.assertEqual(len(data['rows']),2);self.assertEqual(len({r['call_key'] for r in data['rows']}),1)
        for row in data['rows']:self.assertEqual((row['talk_seconds'],row['hold_seconds'],row['reason'],row['end_party']),(10,2,'survey','unknown'))
        self.assertFalse(self.rec.active);self.assertFalse(self.rec.links)
    def test_queue_answer_durations_sla_and_explicit_party(self):
        self.event('QueueCallerJoin',0,Queue='8001',Uniqueid='in',Linkedid='in',CallerIDNum='200')
        self.event('AgentConnect',10,Queue='8001',Uniqueid='in',Interface='Local/100@from-queue/n',HoldTime='10',DestUniqueid='d')
        self.event('DialBegin',11,Uniqueid='in',Linkedid='in',Channel='PJSIP/100-000abc',DialString='200')
        self.event('AgentComplete',30,Queue='8001',Uniqueid='in',Interface='Local/100@from-queue/n',HoldTime='10',TalkTime='20',Reason='agent',DestUniqueid='d')
        asyncio.run(self.rec.flush());data=self.store.daily(['8001'],'2026-10-25')
        self.assertEqual(len(data['rows']),1);row=data['rows'][0];self.assertEqual((row['agent'],row['within_sla'],row['end_party']),('PJSIP/100',1,'agent'))
        self.assertEqual(data['summaries'][0]['answered'],1);self.assertEqual(data['summaries'][0]['talk_seconds'],20)
        self.assertEqual(self.store.daily(['8002'],'2026-10-25')['rows'],[])
    def test_disconnect_does_not_invent_duration_and_flush_is_idempotent(self):
        self.event('DialBegin',0,Uniqueid='out',Channel='PJSIP/100-000abc',DialString='200')
        self.rec.disconnected();self.event('Hangup',10,Uniqueid='out');asyncio.run(self.rec.flush())
        self.assertEqual(self.store.daily(['8001'],'2026-10-25')['rows'],[])
        self.event('QueueCallerAbandon',15,Queue='8001',Uniqueid='abandon',HoldTime='5');asyncio.run(self.rec.flush());asyncio.run(self.rec.flush())
        self.assertEqual(len(self.store.daily(['8001'],'2026-10-25')['rows']),1)
    def test_assignment_cutoff_and_agent_scope(self):
        self.event('QueueCallerAbandon',15,Queue='8001',Uniqueid='abandon',HoldTime='5');asyncio.run(self.rec.flush())
        self.assertEqual(self.store.daily(['8001'],'2026-10-25',agents=['PJSIP/200'])['rows'],[])
        self.assertEqual(self.store.daily(['8001'],'2026-10-25',not_before=self.start+11)['rows'],[])
