from pathlib import Path
import tempfile
import unittest
from sanequeue.realtime.journeys import JourneyEngine
from sanequeue.actions.plans import plan
from qpanel.planning import PlanningStore


class JourneyDirectoryTests(unittest.TestCase):
    def test_ivr_observations_are_scoped_and_do_not_capture_incall_digits(self):
        engine=JourneyEngine();base=dict(Channel='PJSIP/in-00001',Linkedid='call',Uniqueid='call')
        for extension in ('s','2'):
            engine.ingest(dict(base,Event='NewExten',Context='ivr-1',Exten=extension,Priority='1',AppData='private-data'),now=100)
        engine.ingest(dict(base,Event='DTMFEnd',Digit='9',Context='ivr-1'),now=101)
        engine.ingest(dict(base,Event='NewExten',Context='from-internal',Exten='9999',Priority='1'),now=102)
        engine.ingest(dict(base,Event='QueueCallerJoin',Queue='8001'),now=103)
        self.assertEqual(engine.snapshot(['8002'],now=104)['records'],[])
        record=engine.snapshot(['8001'],now=104)['records'][0]
        self.assertEqual([step['selection'] for step in record['ivr_steps']],['s','2'])
        self.assertNotIn('private-data',str(record));self.assertNotIn('9999',str(record))

    def test_local_leg_hangup_does_not_prove_initiator(self):
        engine=JourneyEngine();base=dict(Linkedid='call',Uniqueid='caller',Channel='PJSIP/200-00001')
        engine.ingest(dict(base,Event='QueueCallerJoin',Queue='8001'),now=100)
        engine.ingest(dict(base,Event='Hangup',Channel='Local/100@from-queue-00001;1'),now=101)
        self.assertEqual(engine.snapshot(['8001'],now=102)['records'][0]['hangup_party'],'unknown')
        engine.ingest(dict(base,Event='AgentComplete',Queue='8001',Reason='agent'),now=103)
        record=engine.snapshot(['8001'],now=104)['records'][0]
        self.assertEqual((record['hangup_party'],record['hangup_evidence']),('agent','AgentComplete'))
        engine.ingest(dict(base,Event='AgentComplete',Queue='8001',Reason='transfer'),now=105)
        self.assertEqual(engine.snapshot(['8001'],now=106)['records'][0]['hangup_party'],'unknown')

    def test_contact_name_and_resolution_stay_in_own_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=PlanningStore(Path(tmp)/'planning.db')
            store.save('directory',dict(queue='8001',name='Test Contact',phone='021 12345678'),['8001'])
            ident=store.list('directory',['8001'])[0]['id']
            self.assertEqual(store.contact(ident,'8001')['name'],'Test Contact')
            with self.assertRaises(ValueError):store.contact(ident,'8002')
            data={q:{'entries':{'x':{'CallerIDNum':'02112345678'}}} for q in ('8001','8002')}
            enriched=store.enrich(data)
            self.assertEqual(enriched['8001']['entries']['x']['CallerIDName'],'Test Contact')
            self.assertNotIn('CallerIDName',enriched['8002']['entries']['x'])
            self.assertNotIn('CallerIDName',data['8001']['entries']['x'])

    def test_outbound_dial_requires_explicit_server_resolved_contact(self):
        kwargs=dict(own_phone='PJSIP/100',extensions=['200'])
        with self.assertRaises(ValueError):plan({},'8001','dial',destination='02112345678',**kwargs)
        name,fields=plan({},'8001','dial',destination='02112345678',external_destinations=['02112345678'],**kwargs)
        self.assertEqual((name,fields['Exten'],fields['Channel']),('Originate','02112345678','PJSIP/100'))
        for destination in ('200\r\nAction: Hangup','*21','../bad','${SHELL(id)}'):
            with self.assertRaises(ValueError):plan({},'8001','dial',destination=destination,external_destinations=[destination],**kwargs)
