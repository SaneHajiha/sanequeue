"""Presentation-only regression contracts for the November 2026 UX refresh.

These tests intentionally avoid Flask, Redis and a live Asterisk installation.
They do NOT replace browser, PBX acceptance or the existing app tests.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "qpanel/themes/qpanel"
HTML = (THEME / "templates/operations.html").read_text(encoding="utf-8")
CSS = (THEME / "static/css/sanequeue-design-system.css").read_text(encoding="utf-8")
ICONS = (THEME / "static/js/sanequeue-ui-icons.js").read_text(encoding="utf-8")
LOGIC = (THEME / "static/js/operations.js").read_text(encoding="utf-8")

GROUPS = {
    "operations": ("live", "queues", "calls", "waiting", "wallboard"),
    "team": ("agents", "presence", "shifts", "directory"),
    "control": ("control", "alerts", "audit", "policies"),
    "admin": ("pbx", "features", "users", "telephony", "settings"),
}
ALL_VIEWS = {key for values in GROUPS.values() for key in values}


class DesignSystemContractTest(unittest.TestCase):
    def test_exactly_eighteen_menu_buttons_and_panels(self):
        nav = HTML.split('<nav ', 1)[1].split('</nav>', 1)[0]
        keys = re.findall(r'class="nav-item(?: active)?" data-view="([^"]+)"', nav)
        self.assertEqual(len(keys), 18)
        self.assertEqual(set(keys), ALL_VIEWS)
        self.assertEqual(len(set(keys)), len(keys))
        for key in keys:
            self.assertIn(f'id="{key}-view"', HTML)

    def test_group_labels_are_single_and_in_expected_order(self):
        nav = HTML.split('<nav ', 1)[1].split('</nav>', 1)[0]
        labels = re.findall(r'data-nav-group="([^"]+)"', nav)
        self.assertEqual(labels, list(GROUPS))
        for group, keys in GROUPS.items():
            start = nav.index(f'data-nav-group="{group}"')
            next_group = list(GROUPS).index(group) + 1
            stop = nav.find('data-nav-group="', start + 1) if next_group < 4 else len(nav)
            fragment = nav[start:stop]
            for key in keys:
                self.assertIn(f'data-view="{key}"', fragment)

    def test_admin_sections_remain_role_and_section_guarded(self):
        nav = HTML.split('<nav ', 1)[1].split('</nav>', 1)[0]
        for key in ("users", "policies", "telephony", "settings"):
            line = next(line for line in nav.splitlines() if f'data-view="{key}"' in line)
            self.assertIn("user_role == 'admin'", line)
            self.assertIn(f"can_view_section('{key}')", line)
        audit = next(line for line in nav.splitlines() if 'data-view="audit"' in line)
        self.assertIn("user_role in ('admin','supervisor')", audit)

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
        for key in ALL_VIEWS:
            self.assertRegex(ICONS, rf"\b{re.escape(key)}:")
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
