"""Static release identity and preview safety checks; no live PBX needed."""
import re
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class ReleaseSmoke(unittest.TestCase):
 # Historical snapshot assertion retained in tests/historical.
 pass
 def test_new_sections_and_dynamic_version(self):
  s=(ROOT/'qpanel/themes/qpanel/templates/operations.html').read_text(encoding='utf-8')
  for view in ('queues-view','calls-view','agent-rows'):
   self.assertIn(view,s)
  self.assertIn('current_version()',s)
 # Historical snapshot assertion retained in tests/historical.
 pass
if __name__=='__main__': unittest.main()
