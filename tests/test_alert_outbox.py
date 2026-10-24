from pathlib import Path
import tempfile
import unittest
from qpanel.queue_policies import QueuePolicyStore
from sanequeue.alerts.outbox import AlertOutbox


class OutboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.now=1000
        self.policy=QueuePolicyStore(self.root/'policy.json')
        self.policy.replace({'queues':{'a':{'alerts':{'bale_enabled':True,'cooldown_seconds':60}}},'supervisors':{}})
        self.box=AlertOutbox(self.root/'outbox.db',clock=lambda:self.now)
        self.alert={'queue':'a','type':'waiting_count','value':6,'threshold':5,'label':'Synthetic queue','caller':'must-not-be-saved'}

    def tearDown(self):self.tmp.cleanup()

    def test_opt_in_cooldown_and_restart_are_durable(self):
        self.box.observe([self.alert],self.policy)
        self.assertIsNone(self.box.claim())
        self.box.observe([self.alert],self.policy,delivery_enabled=True)
        job=self.box.claim();self.assertNotIn('caller',job['payload']);self.box.finish(job,True)
        other=AlertOutbox(self.root/'outbox.db',clock=lambda:self.now)
        other.observe([self.alert],self.policy,delivery_enabled=True)
        self.assertIsNone(other.claim())
        self.now+=61;other.observe([self.alert],self.policy,delivery_enabled=True)
        self.assertIsNotNone(other.claim())
        self.assertFalse(other.report(['private'])['alerts'])
        self.assertEqual(other.report(['private'])['notification_status']['sent'],0)

    def test_claim_is_exclusive_retry_is_delayed_and_resolved_alert_is_cancelled(self):
        self.box.observe([self.alert],self.policy,delivery_enabled=True)
        other=AlertOutbox(self.root/'outbox.db',clock=lambda:self.now)
        first=self.box.claim();self.assertIsNone(other.claim())
        self.box.finish(first,False);self.assertIsNone(other.claim())
        self.now+=3
        second=other.claim();self.assertEqual(first['id'],second['id'])
        other.finish(second,False)
        self.box.observe([],self.policy,delivery_enabled=True)
        self.now+=60;self.assertIsNone(self.box.claim())
        self.assertFalse(self.box.report(['a'])['alerts'])

    def test_old_worker_cannot_finish_reclaimed_lease(self):
        self.box.observe([self.alert],self.policy,delivery_enabled=True)
        first=self.box.claim();self.now+=31;second=self.box.claim()
        self.box.finish(first,True)
        self.assertEqual(self.box.report(['a'])['notification_status']['sent'],0)
        self.box.finish(second,True)
        self.assertEqual(self.box.report(['a'])['notification_status']['sent'],1)
