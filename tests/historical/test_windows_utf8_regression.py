"""Regression: smoke tests must not rely on the system ANSI code page."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class WindowsUTF8Regression(unittest.TestCase):
    def test_no_default_encoding_source_reads_in_smoke_tests(self):
        for relative in ('tests/test_release_smoke.py','tests/test_webstart_scripts.py'):
            data=(ROOT/relative).read_text(encoding='utf-8')
            self.assertNotIn('.read_text()',data)
            self.assertIn("read_text(encoding='utf-8')",data)
    def test_windows_start_does_not_run_unit_tests(self):
        data=(ROOT/'RUN_SANEQUEUE_18887_DEBUG.cmd').read_text(encoding='utf-8')
        self.assertNotIn('-m unittest ',data)
        self.assertIn('PYTHONUTF8=1',data)
        self.assertIn('START_DIAGNOSTIC.py',data)
    def test_local_demo_lockout(self):
        data=(ROOT/'demo_monitor.py').read_text(encoding='utf-8')
        self.assertIn("host='127.0.0.1'",data)
        self.assertIn("cfg.config.set('sanequeue', 'demo_mode', 'true')",data)
        self.assertIn("'controls_locked': not CONTROL_GATE.active()",data)
        self.assertIn("CONTROL_GATE = TestControlGate()",data)
