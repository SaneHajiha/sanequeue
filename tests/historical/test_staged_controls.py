
"""Offline safety policy tests; does not contact AMI or Asterisk."""
import unittest
from pathlib import Path
from unittest.mock import patch
from qpanel.test_control_gate import TestControlGate, ALLOWED_ACTIONS
ROOT=Path(__file__).resolve().parents[1]

class StagedControls(unittest.TestCase):
    def setUp(self):
        self.gate=TestControlGate()
        self.live=True

    def test_defaults_locked(self):
        self.assertFalse(self.gate.active())
        self.assertFalse(self.gate.authorize('pause_member',{'queue':'8001','agent':'PJSIP/100','paused':'true'}, True,True))

    def test_exact_phrase_live_and_credential_required(self):
        self.assertFalse(self.gate.arm('ENABLE ALL',True,True))
        self.assertFalse(self.gate.arm('ENABLE 8001',False,True))
        self.assertFalse(self.gate.arm('ENABLE 8001',True,False))
        self.assertTrue(self.gate.arm('ENABLE 8001',True,True))
        self.assertGreater(self.gate.remaining_seconds(),0)

    def test_queue_and_agent_scoping(self):
        self.gate.arm('ENABLE 8001',True,True)
        ok={'queue':'8001','agent':'Local/100@from-queue/n','paused':'true'}
        self.assertTrue(self.gate.authorize('pause_member',ok,True,True))
        self.assertFalse(self.gate.authorize('pause_member',{**ok,'queue':'8002'},True,True))
        self.assertFalse(self.gate.authorize('pause_member',{**ok,'agent':'PJSIP/999'},True,True))
        self.assertFalse(self.gate.authorize('pause_member',{**ok,'paused':'bad'},True,True))
        self.assertFalse(self.gate.authorize('pause_member',ok,False,True))

    def test_spy_requires_specific_supervisor(self):
        self.gate.arm('ENABLE 8001',True,True)
        payload={'queue':'8001','action':'spy','agent':'Local/100@from-queue/n','destination':'PJSIP/101'}
        self.assertTrue(self.gate.authorize('ops_control',payload,True,True))
        self.assertFalse(self.gate.authorize('ops_control',{**payload,'destination':'PJSIP/777'},True,True))
        self.assertFalse(self.gate.authorize('ops_control',{**payload,'action':'originate_raw'},True,True))

    def test_waiting_caller_scope_uses_application_second_check(self):
        self.gate.arm('ENABLE 8001',True,True)
        payload={'queue':'8001','action':'hangup','channel':'PJSIP/test-123'}
        self.assertTrue(self.gate.authorize('ops_control',payload,True,True))
        self.assertFalse(self.gate.authorize('ops_control',{**payload,'channel':''},True,True))
        # The Flask controller additionally verifies channel membership in current queue.
        self.assertIn("any(str(e.get('Channel')) == channel for e in entries)",(ROOT/'qpanel/operations.py').read_text(encoding='utf-8'))

    def test_timeout_and_disarm(self):
        self.gate.arm('ENABLE 8001',True,True)
        self.gate.expires_at-=4000
        self.assertFalse(self.gate.active())
        self.assertEqual(self.gate.remaining_seconds(),0)
        self.gate.arm('ENABLE 8001',True,True)
        self.gate.disarm()
        self.assertFalse(self.gate.active())

    def test_url_auth_ui_smoke(self):
        html=(ROOT/'qpanel/themes/qpanel/templates/operations.html').read_text(encoding='utf-8')
        js=(ROOT/'qpanel/themes/qpanel/static/js/operations.js').read_text(encoding='utf-8')
        demo=(ROOT/'demo_monitor.py').read_text(encoding='utf-8')
        for fragment in ('test-controls-enable','test-controls-disable','ENABLE 8001','ami-settings-form'):
            self.assertIn(fragment,html)
        self.assertNotIn('Classic view',html)
        self.assertIn("'X-CSRF-Token':cfg.csrf",js)
        self.assertIn("not in ('password','enabled','save_password')",demo)
        self.assertIn('SANEQUEUE_TEST_CONTROL_GUARD',(ROOT/'qpanel/operations.py').read_text(encoding='utf-8'))
        self.assertIn('18886',demo)

if __name__=='__main__': unittest.main()
