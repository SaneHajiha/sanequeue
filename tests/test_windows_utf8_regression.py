"""Regression: smoke tests must not rely on the system ANSI code page."""
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
class WindowsUTF8Regression(unittest.TestCase):
    def test_no_default_encoding_source_reads_in_smoke_tests(self):
        for relative in ('tests/test_release_smoke.py','tests/test_webstart_scripts.py'):
            data=(ROOT/relative).read_text(encoding='utf-8')
            self.assertNotIn('.read_text' + '()',data)
            self.assertNotIn('.read_text()',data)
    # Historical snapshot assertion retained in tests/historical.
    pass
    # Historical snapshot assertion retained in tests/historical.
    pass
