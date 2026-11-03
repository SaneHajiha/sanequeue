"""Render real templates for the offline, synthetic PBX report browser test."""
from pathlib import Path
import sys

from flask import Flask
from qpanel.theme_support import render_theme_template, setup_themes

root = Path(__file__).resolve().parents[1]
app = Flask('pbx-visual-fixture', root_path=str(root / 'qpanel'))
setup_themes(app)
app.jinja_env.globals.update(current_version=lambda: 'fixture',
                             has_users=lambda: False,
                             can_view_section=lambda _: True)
with app.test_request_context('/'):
    html = render_theme_template(
        'qpanel', 'operations.html', ui_language='fa', ui_direction='rtl',
        user_role='admin', history_available=True, can_view_section=lambda _: True,
        ops_config={'allowed_sections': ['reports', 'audit', 'shifts', 'users'],
                    'report_extensions': [], 'logged_in_user': 'مدیر آزمایشی',
                    'wait_threshold': 30, 'realtime_push': False, 'csrf': 'fixture-token'},
        current_version=lambda: 'fixture', has_users=lambda: False)
    Path(sys.argv[1]).write_text(html, encoding='utf-8')
