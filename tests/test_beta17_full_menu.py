"""Beta17 menu restoration and feature-preservation checks. No PBX calls are made."""
from pathlib import Path
import re
import unittest
from jinja2 import Environment, FileSystemLoader

ROOT=Path(__file__).resolve().parents[1]
HTML=(ROOT/'qpanel/themes/qpanel/templates/operations.html').read_text(encoding='utf-8')
JS=(ROOT/'qpanel/themes/qpanel/static/js/operations.js').read_text(encoding='utf-8')
ALL=['live','queues','calls','waiting','agents','presence','reports','pbx','features','control','wallboard','alerts','audit','policies','users','telephony','settings','shifts','directory','surveys']

class FullMenuTests(unittest.TestCase):
    def test_template_is_valid_jinja(self):
        Environment().parse(HTML)
    def test_full_navigation_has_every_view(self):
        self.assertNotIn('class="sq-deep-views"',HTML)
        template=Environment(loader=FileSystemLoader(ROOT/'qpanel/themes/qpanel/templates')).get_template('module_navigation.html')
        nav=template.render(t=lambda fa,en:en,can_view_section=lambda view:True,history_available=True,user_role='admin')
        available=re.findall(r'data-view="([^"]+)"',nav)
        self.assertEqual(set(available),set(ALL))
        self.assertEqual(len(available),len(ALL))
        self.assertEqual(nav.count('class="nav-module"'),7)
        restricted=template.render(t=lambda fa,en:en,can_view_section=lambda view:view=='agents',history_available=True,user_role='agent')
        self.assertEqual(re.findall(r'data-view="([^"]+)"',restricted),['agents'])
        self.assertNotIn('data-module="administration"',restricted)
    def test_every_navigation_item_has_panel(self):
        for name in ALL:
            with self.subTest(menu=name):
                panels=HTML+''.join((ROOT/'qpanel/themes/qpanel/templates'/name).read_text(encoding='utf-8') for name in ('reports.html','surveys.html'))
                self.assertIn('id="'+name+'-view"',panels)
                self.assertIn(name+':t(',JS)
    def test_sensitive_menus_preserve_roles(self):
        template=Environment(loader=FileSystemLoader(ROOT/'qpanel/themes/qpanel/templates')).get_template('module_navigation.html')
        for role in ('agent','supervisor'):
            nav=template.render(t=lambda fa,en:en,can_view_section=lambda view:True,history_available=True,user_role=role)
            for section in ('users','settings','telephony','policies'):
                self.assertNotIn('data-view="'+section+'"',nav)
            self.assertEqual('data-view="audit"' in nav,role=='supervisor')
    def test_call_journey_and_full_wallboard_remain(self):
        for part in ['dashboard-journey-cards','wallboard-queue-picker','wallboard-fullscreen','wb-journey-rows','call-rows','dashboard-active-rows','live-view','calls-view','waiting-view','users-view']:
            with self.subTest(part=part): self.assertIn(part,HTML)
    def test_correct_launcher_port_and_version(self):
        self.assertEqual((ROOT/'VERSION').read_text(encoding='utf-8').strip(),__import__('qpanel').__version__)
        self.assertIn('18895',(ROOT/'RUN_SANEQUEUE_18895_DEBUG.cmd').read_text(encoding='utf-8'))
        self.assertIn('18895',(ROOT/'START_DIAGNOSTIC.py').read_text(encoding='utf-8'))
        self.assertFalse((ROOT/'RUN_SANEQUEUE_18894_DEBUG.cmd').exists())

if __name__=='__main__':unittest.main()
