"""Current Windows startup checks; no PBX/Flask needed."""
from pathlib import Path
import unittest
R=Path(__file__).resolve().parents[1]
class WebStartSmokeTests(unittest.TestCase):
 def test_debug_launcher_runs_server_and_shows_failures(self):
  s=(R/'RUN_SANEQUEUE_18887_DEBUG.cmd').read_text(encoding='utf-8')
  self.assertIn('SANEQUEUE_DEMO_PORT=18887',s)
  self.assertIn('START_DIAGNOSTIC.py',s)
  self.assertIn('pause',s.lower())
  self.assertIn('PYTHONUTF8=1',s)
  self.assertNotIn('-m unittest',s)
 def test_start_diagnostic_checks_build_and_writes_log(self):
  s=(R/'START_DIAGNOSTIC.py').read_text(encoding='utf-8')
  for v in ('/__sanequeue__/build','startup_last.log','2.1.0-beta.9','18887'):
   self.assertIn(v,s)
 def test_local_bind_and_test_guard(self):
  s=(R/'demo_monitor.py').read_text(encoding='utf-8')
  self.assertIn("host='127.0.0.1'",s)
  self.assertIn('TestControlGate()',s)
  self.assertIn("'controls_locked': not CONTROL_GATE.active()",s)
