"""Regression coverage for reference UI, alert calculations, action safety and release identity."""
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'qpanel/themes/qpanel/templates/operations.html').read_text(encoding='utf-8')
JS=(ROOT/'qpanel/themes/qpanel/static/js/operations.js').read_text(encoding='utf-8')
CSS=(ROOT/'qpanel/themes/qpanel/static/css/operations.css').read_text(encoding='utf-8')
class DashboardReference(unittest.TestCase):
 def test_reference_dashboard_contains_six_metrics_and_operational_columns(self):
  self.assertIn('id="metrics"',HTML)
  for id_ in ('queue-cards','call-rows','overview-agent-list','dashboard-active-rows','capacity-donut'):
   self.assertIn('id="'+id_+'"',HTML)
  self.assertLess(HTML.index('id="metrics"'),HTML.index('reference-three-panel'))
  self.assertLess(HTML.index('reference-three-panel'),HTML.index('dashboard-bottom'))
  self.assertLess(HTML.index('dashboard-bottom'),HTML.index('realtime-graphs'))
 def test_agent_actions_grid_consistent_and_scoped(self):
  self.assertIn('agent-action-grid',JS)
  self.assertIn('agent-primary-action',JS)
  self.assertIn('data-agent=',JS)
  self.assertIn('grid-template-columns:repeat(3,minmax(0,1fr))',CSS)
 def test_empty_default_queue_not_raised_as_staffing_incident(self):
  self.assertIn('(count>0||n(q.Calls)>0)',JS)
  self.assertIn('(Object.keys(q.members||{}).length>0||n(q.Calls)>0)',JS)
 def test_sample_trends_are_observed_not_fabricated(self):
  self.assertIn('samples.push({ts:now,waiting,ready,busy,paused,offline})',JS)
  self.assertIn('currentDataSource',JS)
  self.assertIn('data-source-label',JS)
 def test_action_requires_live_ami_and_explicit_gate(self):
  self.assertIn("currentDataSource!=='ami-live'||!cfg.test_controls_enabled",JS)
  self.assertIn('SANEQUEUE_TEST_CONTROL_GUARD',(ROOT/'qpanel/operations.py').read_text(encoding='utf-8'))
 def test_release_and_launcher_consistency(self):
  version=(ROOT/'VERSION').read_text(encoding='utf-8').strip()
  self.assertEqual(version,'2.1.0-beta.9')
  self.assertIn(version,(ROOT/'qpanel/__init__.py').read_text(encoding='utf-8'))
  self.assertIn(version,HTML)
  self.assertIn('SANEQUEUE_DEMO_PORT=18887',(ROOT/'RUN_SANEQUEUE_18887_DEBUG.cmd').read_text(encoding='utf-8'))
if __name__=='__main__':unittest.main()
