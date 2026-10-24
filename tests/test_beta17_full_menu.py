"""Beta17 menu restoration and feature-preservation checks. No PBX calls are made."""
from pathlib import Path
import re
import unittest
from jinja2 import Environment

ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'qpanel/themes/qpanel/templates/operations.html').read_text(encoding='utf-8')
JS=(ROOT/'qpanel/themes/qpanel/static/js/operations.js').read_text(encoding='utf-8')
ALL=['live','queues','calls','waiting','agents','presence','pbx','features','control','wallboard','alerts','audit','policies','users','settings','shifts','directory']

class FullMenuTests(unittest.TestCase):
    def test_template_is_valid_jinja(self):
        Environment().parse(HTML)
    def test_full_navigation_has_every_view(self):
        self.assertIn('class="sq-full-nav"',HTML)
        self.assertNotIn('class="sq-deep-views"',HTML)
        nav=HTML.split('<nav ',1)[1].split('</nav>',1)[0]
        available=re.findall(r'class="nav-item(?: active)?" data-view="([^"]+)"',nav)
        # Button type="button" is allowed; order matches the original full sidebar.
        self.assertEqual(available, ALL)
    def test_every_navigation_item_has_panel(self):
        for name in ALL:
            with self.subTest(menu=name):
                self.assertIn('id="'+name+'-view"',HTML)
                self.assertIn(name+':t(',JS)
    def test_sensitive_menus_preserve_roles(self):
        self.assertIn("{% if user_role in ('admin','supervisor') %}",HTML)
        self.assertIn("{% if user_role == 'admin' %}",HTML)
    def test_call_journey_and_full_wallboard_remain(self):
        for part in ['dashboard-journey-cards','wallboard-queue-picker','wallboard-fullscreen','wb-journey-rows','call-rows','dashboard-active-rows','live-view','calls-view','waiting-view','users-view']:
            with self.subTest(part=part): self.assertIn(part,HTML)
    def test_correct_launcher_port_and_version(self):
        self.assertEqual((ROOT/'VERSION').read_text(encoding='utf-8').strip(),__import__('qpanel').__version__)
        self.assertIn('18895',(ROOT/'RUN_SANEQUEUE_18895_DEBUG.cmd').read_text(encoding='utf-8'))
        self.assertIn('18895',(ROOT/'START_DIAGNOSTIC.py').read_text(encoding='utf-8'))
        self.assertFalse((ROOT/'RUN_SANEQUEUE_18894_DEBUG.cmd').exists())

if __name__=='__main__':unittest.main()
