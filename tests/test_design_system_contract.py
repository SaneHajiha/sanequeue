"""Presentation-only regression contracts for the November 2026 UX refresh.

These tests intentionally avoid Flask, Redis and a live Asterisk installation.
They do NOT replace browser, PBX acceptance or the existing app tests.
"""
from pathlib import Path
import re
import unittest
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "qpanel/themes/qpanel"
HTML = (THEME / "templates/operations.html").read_text(encoding="utf-8")
CSS = (THEME / "static/css/sanequeue-design-system.css").read_text(encoding="utf-8")
ICONS = (THEME / "static/js/sanequeue-ui-icons.js").read_text(encoding="utf-8")
LOGIC = (THEME / "static/js/operations.js").read_text(encoding="utf-8")

NAV = Environment(loader=FileSystemLoader(THEME / "templates")).get_template("module_navigation.html")


class DesignSystemContractTest(unittest.TestCase):
    def render_nav(self, role="admin", sections=None, history=True):
        return NAV.render(t=lambda fa, en: en, user_role=role, history_available=history,
                          can_view_section=lambda key: sections is None or key in sections)

    def test_reporting_families_are_distinct_and_permissioned(self):
        nav = self.render_nav()
        self.assertEqual(re.findall(r'data-report-family="([^"]+)"', nav), ["pbx", "contact-center", "shared"])
        self.assertIn('data-module-target="history-cdr-section"', nav)
        self.assertIn('data-module-target="history-summary-section"', nav)
        supervisor = self.render_nav("supervisor", {"reports"})
        self.assertIn('data-module-target="history-unit-section"', supervisor)
        self.assertNotIn('data-module-target="history-cdr-section"', supervisor)
        self.assertNotIn('data-report-family=', self.render_nav(history=False))
        self.assertNotIn('data-report-family=', self.render_nav("agent", {"live"}))

    def test_view_router_and_mobile_selector_are_preserved(self):
        for marker in (
            'id="view-jump"',
            'id="queue-filter"',
            'id="connection"',
            'id="context-help"',
            'id="ops-config"',
            'id="action-dialog"',
        ):
            self.assertIn(marker, HTML)
        self.assertIn("document.querySelectorAll('nav button[data-view]')", LOGIC)
        self.assertIn("viewJump.onchange=", LOGIC)
        self.assertIn("document.body.dataset.view=button.dataset.view", LOGIC)

    def test_design_assets_versioned_after_existing_styles(self):
        names = ("operations.css", "accessibility.css", "overview.css",
                 "sanequeue-design-system.css")
        for name in names:
            self.assertIn(f"css/{name}", HTML)
        positions = [HTML.index(f"css/{name}") for name in names]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("js/sanequeue-ui-icons.js", HTML)
        self.assertLess(HTML.index("js/operations.js"), HTML.index("js/sanequeue-ui-icons.js"))
        self.assertIn("current_version()", HTML)

    def test_no_external_icon_fonts_and_no_untrusted_svg_html(self):
        nav = self.render_nav()
        for key, children in re.findall(r'data-view="([^"]+)"[^>]*>(.*?)</button>', nav):
            self.assertRegex(ICONS, rf"(?:\b|'){re.escape(key)}'?:")
            self.assertIn('data-nav-icon aria-hidden="true"', children)
        self.assertIn("document.createElementNS(ns, 'svg')", ICONS)
        self.assertIn("icon.replaceChildren(svg)", ICONS)
        self.assertNotIn(".innerHTML", ICONS)
        self.assertNotIn("fetch(", ICONS)

    def test_semantic_tokens_and_accessible_responsiveness(self):
        for name in ("--sq-sidebar-width", "--sq-touch-target", "--sq-focus",
                     "--sq-danger", "--sq-warning", "--sq-success",
                     "--sq-radius-lg", "--sq-content-width"):
            self.assertIn(name, CSS)
        for marker in ("body.dark", "focus-visible", "prefers-reduced-motion",
                       "max-width:760px", "max-width:420px",
                       "body .sidebar nav.sq-full-nav{display:none}"):
            self.assertIn(marker, CSS)
        self.assertIn("margin-inline-start", CSS)
        self.assertNotIn("@import url(", CSS)

if __name__ == "__main__":
    unittest.main()
