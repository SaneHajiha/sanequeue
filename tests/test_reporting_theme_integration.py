"""Render real prefixed Flask theme loaders, not isolated Jinja parse checks."""
from pathlib import Path
import unittest
from flask import Flask
from qpanel.theme_support import setup_themes,render_theme_template


class ReportingThemeTests(unittest.TestCase):
    def test_nested_reporting_templates_resolve_in_installed_theme(self):
        root=Path(__file__).resolve().parents[1]
        app=Flask('theme-contract',root_path=str(root/'qpanel'));setup_themes(app)
        for lang in ('fa','en'):
            with self.subTest(lang=lang),app.test_request_context('/'):
                html=render_theme_template('qpanel','reports.html',t=lambda fa,en:fa if lang=='fa' else en,
                    user_role='admin',can_view_section=lambda key:True,
                    ops_config={'allowed_sections':['reports','audit','shifts','users']})
                for name in ('history-customer-segments-section','history-builder-section','history-transcript-section','history-ring-attempts-section'):
                    self.assertIn('id="'+name+'"',html)

    def test_voice_feedback_is_rendered_only_for_granted_supervisors(self):
        root=Path(__file__).resolve().parents[1]
        app=Flask('voice-theme-contract',root_path=str(root/'qpanel'));setup_themes(app)
        with app.test_request_context('/'):
            def render(role,granted):return render_theme_template('qpanel','voice_feedback.html',t=lambda fa,en:en,
                user_role=role,can_view_section=lambda key:key=='surveys' and granted)
            self.assertIn('id="voice-feedback-view"',render('supervisor',True))
            self.assertNotIn('id="voice-feedback-view"',render('supervisor',False))
            self.assertNotIn('id="voice-feedback-view"',render('agent',True))
