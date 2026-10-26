"""Emergency service selection must include optional installed workers only."""
import tempfile
import unittest
from pathlib import Path
from scripts.module_control import UNITS,enabled_units

class ReportingModuleControlTests(unittest.TestCase):
    def test_optional_installations_and_ai_opt_in(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);marker=root/'ai.enabled'
            units=enabled_units(root,marker)
            self.assertFalse(any(x.startswith('sanequeue-reporting') for x in units))
            for name in UNITS:
                if name.startswith('sanequeue-reporting'):(root/name).touch()
            units=enabled_units(root,marker)
            self.assertIn('sanequeue-reporting-plans.service',units)
            self.assertIn('sanequeue-reporting-export.service',units)
            self.assertNotIn('sanequeue-reporting-ai.service',units)
            marker.touch()
            self.assertIn('sanequeue-reporting-ai.service',enabled_units(root,marker))
            self.assertTrue(all(x.startswith('sanequeue') for x in UNITS))
            self.assertFalse(any('asterisk' in x or 'mariadb' in x for x in UNITS))

if __name__=='__main__':unittest.main()
