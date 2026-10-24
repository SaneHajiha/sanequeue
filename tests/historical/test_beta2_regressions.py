"""Offline regressions. Does not connect to a PBX."""
import unittest
from pathlib import Path
from qpanel.ami_live import parse_queue_events

ROOT=Path(__file__).resolve().parents[1]

class Beta2RegressionTests(unittest.TestCase):
    def test_hint_state_and_static_membership_kept(self):
        events=[
            {'Event':'QueueParams','Queue':'8001','Calls':'0'},
            {'Event':'QueueMember','Queue':'8001','Location':'Local/100@from-queue/n','StateInterface':'hint:100@ext-local','Membership':'static','Status':'1'},
        ]
        data=parse_queue_events(events)
        member=data['8001']['members']['Local/100@from-queue/n']
        self.assertEqual(member['StateInterface'],'hint:100@ext-local')
        self.assertEqual(member['Membership'],'static')

    def test_control_targets_local_hint_only_for_allowed_extension(self):
        source=(ROOT/'qpanel/operations.py').read_text(encoding='utf-8')
        self.assertIn("queue == '8001' and agent in ('Local/100@from-queue/n','PJSIP/100')",source)
        self.assertIn("target = 'PJSIP/100'",source)
        self.assertIn('static_member_must_be_managed_in_issabel',source)

    def test_ami_timeout_and_runtime_fields(self):
        js=(ROOT/'qpanel/themes/qpanel/static/js/operations.js').read_text(encoding='utf-8')
        demo=(ROOT/'demo_monitor.py').read_text(encoding='utf-8')
        self.assertIn("url.includes('/api/ami/')?30000:15000",js)
        self.assertIn("'password','enabled','save_password'",demo)
        self.assertIn("'18887'",demo)

    def test_version_and_launcher(self):
        expected=(ROOT/'VERSION').read_text(encoding='utf-8').strip()
        import qpanel
        self.assertEqual(qpanel.__version__,expected)
        self.assertEqual(expected,'2.1.0-beta.9')
        launcher=(ROOT/'RUN_SANEQUEUE_18887_DEBUG.cmd').read_text(encoding='utf-8')
        self.assertIn('SANEQUEUE_DEMO_PORT=18887',launcher)
        self.assertNotIn('unittest',launcher)

if __name__=='__main__':unittest.main()
