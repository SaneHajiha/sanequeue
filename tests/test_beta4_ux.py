"""Offline UI and safety contract tests; no PBX connection or call changes."""
import unittest
from pathlib import Path
R=Path(__file__).resolve().parents[1]
class UXTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html=(R/'qpanel/themes/qpanel/templates/operations.html').read_text(encoding='utf-8')
        cls.js=(R/'qpanel/themes/qpanel/static/js/operations.js').read_text(encoding='utf-8')
        cls.css=(R/'qpanel/themes/qpanel/static/css/operations.css').read_text(encoding='utf-8')
    # Historical snapshot assertion retained in tests/historical.
    pass
    def test_queue_chart_not_historical(self):
        self.assertIn('queue-comparison',self.html)
        self.assertIn("entries.map(([name,q])=>",self.js)
        self.assertIn("data_source",(R/'qpanel/operations.py').read_text(encoding='utf-8'))
    def test_agent_cards_are_escaped(self):
        self.assertIn('agent-presence-tiles',self.html)
        self.assertIn('esc(a.m.Name||a.key)',self.js)
        self.assertIn('esc(a.name)',self.js)
    def test_waiting_spotlight_is_current_only(self):
        self.assertIn('waiting-spotlight',self.html)
        self.assertIn('n(b.c.Wait)-n(a.c.Wait)',self.js)
        self.assertNotIn('historical forecast',self.js)
    def test_sensitive_controls_locked_in_demo(self):
        self.assertIn("currentDataSource!=='ami-live'||!cfg.test_controls_enabled",self.js)
        self.assertIn('SANEQUEUE_TEST_CONTROL_GUARD',(R/'qpanel/operations.py').read_text(encoding='utf-8'))
    def test_ami_secret_not_included_in_file(self):
        demo=(R/'demo_monitor.py').read_text(encoding='utf-8')
        self.assertIn("if k not in ('password','enabled','save_password')",demo)
        self.assertNotIn('secret = ',demo)
    def test_mobile_breakpoints(self):
        self.assertIn('@media(max-width:760px)',self.css)
        self.assertIn('.detail-hero-kpis{grid-template-columns:repeat(2',self.css)
    # Historical snapshot assertion retained in tests/historical.
    pass
if __name__=='__main__':unittest.main()
