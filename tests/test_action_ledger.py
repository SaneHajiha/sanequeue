import concurrent.futures
from pathlib import Path
import tempfile
import unittest

from sanequeue.actions.ledger import ActionLedger, QueueBusy
from sanequeue.actions.transport import send_action


class ActionLedgerTests(unittest.TestCase):
    def test_two_independent_stores_reserve_only_five_departures_of_ten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'actions.db'
            stores=[ActionLedger(path) for _ in range(10)]
            members={'PJSIP/'+str(i):{'Status':'1','Paused':'0'} for i in range(10)}
            policy=dict(roster_size=10,max_absent_percent=50,max_absent_count=5,min_on_duty=0)
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
                results=list(pool.map(lambda i:stores[i].reserve('q','PJSIP/'+str(i),members,policy),range(10)))
            self.assertEqual(sum(accepted for accepted,_ in results),5)
            fresh=ActionLedger(path)
            self.assertFalse(fresh.reserve('q','PJSIP/9',members,policy)[0])

    def test_queue_lock_fences_old_owner_and_rejects_parallel_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            now=[1]
            a=ActionLedger(Path(tmp)/'a.db',clock=lambda:now[0]);b=ActionLedger(Path(tmp)/'a.db',clock=lambda:now[0])
            with a.queue_lock('q'):
                with self.assertRaises(QueueBusy):
                    with b.queue_lock('q'):pass
                now[0]+=21
                with b.queue_lock('q'):
                    with self.assertRaises(QueueBusy):
                        with a.queue_lock('q'):pass

    def test_outcome_requires_newer_state_and_authorization(self):
        with tempfile.TemporaryDirectory() as tmp:
            now=[100]
            ledger=ActionLedger(Path(tmp)/'a.db',clock=lambda:now[0])
            ident=ledger.create('supervisor','q','QueuePause',{'Queue':'q','Interface':'SIP/1','Paused':'true'})
            state={'last_event_at':99,'queues':{'q':{'members':{'SIP/1':{'paused':'1'}}}}}
            ledger.reconcile(state)
            self.assertEqual(ledger.public(ident,'supervisor',['q'])['state'],'pending')
            state['last_event_at']=101;ledger.reconcile(state)
            result=ledger.public(ident,'supervisor',['q'])
            self.assertEqual(result['state'],'confirmed');self.assertFalse(result['audio_verified'])
            self.assertNotIn('fields',result)
            self.assertIsNone(ledger.public(ident,'other',['q']))
            self.assertIsNone(ledger.public(ident,'supervisor',['other']))
            ident=ledger.create('supervisor','q','Originate',{'Channel':'SIP/300'})
            now[0]=191;ledger.reconcile({})
            self.assertEqual(ledger.public(ident,'supervisor',['q'])['state'],'unknown')

    def test_write_transport_rejects_unlisted_actions_and_injection_before_connect(self):
        for action,fields in [('Command',{'Command':'stop now'}),('Hangup',{'Channel':'x\r\nAction: Command'}),
                              ('Originate',{'Secret':'x'}),('Hangup',{'Channel':'x\0'})]:
            with self.subTest(action=action),self.assertRaises(ValueError):
                send_action('unused',action,fields,'sq-test')
