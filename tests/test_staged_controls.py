
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

    # Historical snapshot assertion retained in tests/historical.
    pass

    # Historical snapshot assertion retained in tests/historical.
    pass

    # Historical snapshot assertion retained in tests/historical.
    pass

    # Historical snapshot assertion retained in tests/historical.
    pass

    def test_timeout_and_disarm(self):
        self.gate.arm('ENABLE 8001',True,True)
        self.gate.expires_at-=4000
        self.assertFalse(self.gate.active())
        self.assertEqual(self.gate.remaining_seconds(),0)
        self.gate.arm('ENABLE 8001',True,True)
        self.gate.disarm()
        self.assertFalse(self.gate.active())

    # Historical snapshot assertion retained in tests/historical.
    pass

if __name__=='__main__': unittest.main()
