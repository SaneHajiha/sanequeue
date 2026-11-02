"""Emergency service selection must include optional installed workers only."""
import tempfile
import unittest
from pathlib import Path
from scripts.module_control import UNITS,enabled_units

class ReportingModuleControlTests(unittest.TestCase):
    def test_generative_worker_is_stopped_but_not_enabled_without_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);marker=root/'generative.enabled';unit='sanequeue-generative.service'
            self.assertIn(unit,UNITS)
            self.assertNotIn(unit,enabled_units(root,generative_marker=marker))
            (root/unit).touch()
            self.assertNotIn(unit,enabled_units(root,generative_marker=marker))
            marker.touch();self.assertIn(unit,enabled_units(root,generative_marker=marker))
    def test_survey_stop_coverage_but_enable_requires_installed_unit_and_opt_in(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);marker=root/'surveys.enabled';unit='sanequeue-surveys.service'
            self.assertIn(unit,UNITS)
            self.assertNotIn(unit,enabled_units(root,root/'ai.enabled',marker))
            marker.touch()
            self.assertNotIn(unit,enabled_units(root,root/'ai.enabled',marker))
            (root/unit).touch()
            self.assertIn(unit,enabled_units(root,root/'ai.enabled',marker))
            marker.unlink()
            self.assertNotIn(unit,enabled_units(root,root/'ai.enabled',marker))

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
