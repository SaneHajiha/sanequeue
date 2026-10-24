"""Tests that raw Asterisk QueueStatus results do not leak unmanaged queues into Issabel UI."""
import unittest
from pathlib import Path
from qpanel.queue_visibility import parse_visible_queues, normalize_visible_queues, filter_queue_data, is_queue_visible
from qpanel.ami_live import parse_queue_events

ROOT = Path(__file__).resolve().parents[1]


class IssabelQueueVisibility(unittest.TestCase):
    def setUp(self):
        self.events = [
            {'Event':'QueueParams', 'Queue':'8001', 'Calls':'0', 'Strategy':'rrmemory'},
            {'Event':'QueueMember', 'Queue':'8001','Location':'Local/100@from-queue/n','Status':'1'},
            {'Event':'QueueParams', 'Queue':'default', 'Calls':'0', 'Strategy':'ringall'},
        ]

    def test_asterisk_default_is_real_but_not_a_gui_managed_queue(self):
        raw = parse_queue_events(self.events, '*')
        self.assertEqual(set(raw), {'8001', 'default'})
        gui = filter_queue_data(raw, '8001')
        self.assertEqual(list(gui), ['8001'])
        self.assertEqual(len(gui['8001']['members']), 1)

    def test_multiple_issabel_gui_queues(self):
        self.assertEqual(normalize_visible_queues('8001, 8002 ؛8003'), '8001,8002,8003')
        raw={'8001':{},'8002':{},'default':{}}
        self.assertEqual(set(filter_queue_data(raw, '8001,8002')), {'8001','8002'})

    def test_star_is_explicit_asterisk_raw_diagnostics_mode(self):
        self.assertIsNone(parse_visible_queues('*'))
        self.assertEqual(set(filter_queue_data({'8001':{},'default':{}}, '*')), {'8001','default'})

    def test_injection_and_invalid_whitelists_rejected(self):
        for raw in ('', 'default;Originate:1', '*;8001', 'x'*33, '8001\nChannel:100'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_visible_queues(raw)

    def test_hidden_queues_unavailable_for_supervisor_test(self):
        self.assertTrue(is_queue_visible('8001','8001'))
        self.assertFalse(is_queue_visible('default','8001'))

    def test_user_interface_and_server_boundaries_present(self):
        demo=(ROOT/'demo_monitor.py').read_text(encoding='utf-8')
        js=(ROOT/'qpanel/themes/qpanel/static/js/operations.js').read_text(encoding='utf-8')
        html=(ROOT/'qpanel/themes/qpanel/templates/operations.html').read_text(encoding='utf-8')
        self.assertIn('filter_queue_data(data, settings.get(', demo)
        self.assertIn('is_queue_visible(selected_queue',demo)
        self.assertIn('name="visible_queues"', html)
        self.assertIn("visible_queues:$('ami-visible-queues').value.trim()", js)
        self.assertIn("'visible_queues': '8001'",demo)

    def test_regression_version_and_correct_windows_launcher(self):
        self.assertEqual((ROOT/'VERSION').read_text(encoding='utf-8').strip(),'2.1.0-beta.9')
        launcher=(ROOT/'RUN_SANEQUEUE_18887_DEBUG.cmd').read_text(encoding='utf-8')
        self.assertIn('SANEQUEUE_DEMO_PORT=18887',launcher)
        self.assertNotIn('SANEQUEUE_DEMO_PORT=18884',launcher)

if __name__=='__main__': unittest.main()
