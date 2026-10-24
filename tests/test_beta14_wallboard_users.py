"""Lightweight regression checks for beta.14 without a running PBX.
These tests do NOT verify AMI operations or Flask integration."""
from pathlib import Path
from collections import Counter
import re
import unittest
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / 'qpanel/themes/qpanel/static/js/operations.js').read_text(encoding='utf-8')
HTML = (ROOT / 'qpanel/themes/qpanel/templates/operations.html').read_text(encoding='utf-8')
CSS = (ROOT / 'qpanel/themes/qpanel/static/css/operations.css').read_text(encoding='utf-8')

class Beta14UX(unittest.TestCase):
    def test_jinja_template_parses(self):
        Environment().parse(HTML)
    def test_unique_html_ids(self):
        ids = Counter(re.findall(r'\bid="([^"]+)"', HTML))
        self.assertEqual({k:v for k,v in ids.items() if v > 1}, {})
    def test_all_views_present(self):
        for name in ['live','queues','calls','waiting','agents','presence','pbx','features','control','wallboard','alerts','policies','audit','settings','users']:
            self.assertIn(f'id="{name}-view"',HTML)
    def test_wallboard_stays_private_and_has_scope_filter(self):
        for word in ['wallboard-queue-picker','wallboard-fullscreen','wb-select-all','wallboard-exit','wb-agent','wb-caller','requestFullscreen']:
            self.assertTrue(word in HTML or word in JS or word in CSS, word)
        self.assertIn('Caller numbers hidden on public screens', HTML)
    def test_user_forms_and_api_wiring(self):
        for element in ['account-create-form','user-permission-select','user-queues','account-list','refresh-user-catalog']:
            self.assertIn(f'id="{element}"',HTML)
        self.assertIn("fetchJSON('/api/accounts'",JS)
        self.assertIn("await savePolicyState()",JS)
        self.assertIn("{% if user_role == 'admin' %}",HTML)
    def test_status_mapping_distinguishes_telephony(self):
        self.assertIn("if(code===6||code===7)",JS)
        self.assertIn("if(code===8)",JS)
        self.assertIn("if(bool(m.InCall)||code===10)",JS)
        self.assertIn("if(code===1)",JS)
        self.assertIn("sq-state--ringing",CSS)
    def test_real_queue_counters_not_fabricated(self):
        for key in ['q.Completed','q.Abandoned','q.ServicelevelPerf',"queueMean(q,'Holdtime')","queueMean(q,'TalkTime')"]:
            self.assertIn(key,JS)
    # Historical snapshot assertion retained in tests/historical.
    pass

if __name__=='__main__':unittest.main()
