"""Render real prefixed Flask theme loaders, not isolated Jinja parse checks."""
from pathlib import Path
import unittest
from flask import Flask
from qpanel.theme_support import setup_themes,render_theme_template


class ReportingThemeTests(unittest.TestCase):
    def test_shared_calendar_assets_precede_consumers_and_styles_are_in_head(self):
        root=Path(__file__).resolve().parents[1]
        source=(root/'qpanel/themes/qpanel/templates/operations.html').read_text(encoding='utf-8')
        for style in ('report-charts.css','date-picker.css','report-date-range.css'):
            self.assertLess(source.index(style),source.index('</head>'))
        for helper in ('date-picker.js','report-periods.js','report-date-range.js'):
            for consumer in ('surveys.js','reports.js'):
                self.assertLess(source.index(helper),source.index(consumer))

    def test_nested_reporting_templates_resolve_in_installed_theme(self):
        root=Path(__file__).resolve().parents[1]
        app=Flask('theme-contract',root_path=str(root/'qpanel'));setup_themes(app)
        for lang in ('fa','en'):
            with self.subTest(lang=lang),app.test_request_context('/'):
                html=render_theme_template('qpanel','reports.html',t=lambda fa,en:fa if lang=='fa' else en,
                    user_role='admin',can_view_section=lambda key:True,
                    ops_config={'allowed_sections':['reports','audit','shifts','users']})
                for name in ('history-customer-segments-section','history-builder-section','history-transcript-section','history-ring-attempts-section','history-agent-rankings-section'):
                    self.assertIn('id="'+name+'"',html)

    def test_report_family_navigation_retains_rankings_and_role_gates(self):
        from jinja2 import Environment,FileSystemLoader
        root=Path(__file__).resolve().parents[1]
        template=Environment(loader=FileSystemLoader(root/'qpanel/themes/qpanel/templates')).get_template('module_navigation.html')
        def render(role,granted=True):return template.render(t=lambda fa,en:en,history_available=True,
            user_role=role,can_view_section=lambda key:granted)
        admin=render('admin')
        for family in ('pbx','contact-center','shared'):self.assertIn('data-report-family="'+family+'"',admin)
        self.assertIn('data-module-target="history-agent-rankings-section"',admin)
        self.assertNotIn('history-cdr-section',render('agent'))
        self.assertNotIn('history-plan-section',render('agent'))
        self.assertNotIn('history-agent-rankings-section',render('admin',False))

    def test_voice_feedback_is_rendered_only_for_granted_supervisors(self):
        root=Path(__file__).resolve().parents[1]
        app=Flask('voice-theme-contract',root_path=str(root/'qpanel'));setup_themes(app)
        with app.test_request_context('/'):
            def render(role,granted):return render_theme_template('qpanel','voice_feedback.html',t=lambda fa,en:en,
                user_role=role,can_view_section=lambda key:key=='surveys' and granted)
            self.assertIn('id="voice-feedback-view"',render('supervisor',True))
            self.assertNotIn('id="voice-feedback-view"',render('supervisor',False))
            self.assertNotIn('id="voice-feedback-view"',render('agent',True))
