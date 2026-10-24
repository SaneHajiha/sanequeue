"""Static release identity and preview safety checks; no live PBX needed."""
import re
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class ReleaseSmoke(unittest.TestCase):
 def test_consistent_release_id(self):
  v=(ROOT/'VERSION').read_text(encoding='utf-8').strip()
  self.assertEqual(v, '2.1.0-beta.9')
  self.assertIn(v,(ROOT/'qpanel/__init__.py').read_text(encoding='utf-8'))
 def test_new_sections_and_dynamic_version(self):
  s=(ROOT/'qpanel/themes/qpanel/templates/operations.html').read_text(encoding='utf-8')
  for view in ('queues-view','calls-view','agent-rows'):
   self.assertIn(view,s)
  self.assertIn('current_version()',s)
 def test_separate_local_preview_and_control_lock(self):
  demo=(ROOT/'demo_monitor.py').read_text(encoding='utf-8')
  ops=(ROOT/'qpanel/operations.py').read_text(encoding='utf-8')
  self.assertIn("'18887'",demo)
  self.assertIn("demo_mode', 'false'",ops)
  self.assertIn('abort(403)',ops)
  self.assertIn("host='127.0.0.1'",demo)
  self.assertIn('/__sanequeue__/ami-snapshot',demo)
  self.assertIn('api/ami',(ROOT/'demo_monitor.py').read_text(encoding='utf-8'))
if __name__=='__main__': unittest.main()
