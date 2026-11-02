"""Verifier streams genuine CSV/XLSX artifacts, never a production archive."""
from pathlib import Path
import tempfile
import unittest

from tools.verify_reporting_month import _exports,_validate_rows,_read_manifest,_read_checks
from tools.generate_reporting_month import _write,_plan
from sanequeue.reporting.store import Archive
from tests import test_reporting_export_jobs as fixtures


class MonthVerifierTests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.ExportJobTests();self.case.setUp();self.addCleanup(self.case.doCleanups)

    def test_real_pinned_csv_and_xlsx_are_both_counted_with_same_ids(self):
        self.case.seed(405)
        metadata=dict(start=90,end=300,queues=['8001'],queue_visit_count=405,
                      expected={'overview':[dict(queue='8001',visits=405)]})
        result=_exports(self.case.archive,metadata,self.case.root/'validator-output')
        self.assertEqual([r['state'] for r in result['checks']],['passed','passed'])
        self.assertEqual([r['verification']['rows'] for r in result['checks']],[405,405])
        self.assertEqual([r['verification']['distinct_visit_ids'] for r in result['checks']],[405,405])
        self.assertTrue(all(len(r['checksum_sha256'])==64 for r in result['checks']))
        self.assertEqual(result['limits']['max_rows'],100000)
        self.assertEqual(result['limits']['max_bytes'],32*1024*1024)
        self.assertEqual(result['xlsx_xml_limit_bytes'],64*1024*1024)

    def test_stream_checker_rejects_duplicate_or_missing_visits(self):
        wanted=dict(queues=['8001'],queue_visit_count=2,expected={'overview':[dict(queue='8001',visits=2)]})
        row=['8001']+['']*10+['a'*64]
        with self.assertRaises(AssertionError):_validate_rows(iter([row,row]),wanted)
        with self.assertRaises(AssertionError):_validate_rows(iter([row]),wanted)

    def test_existing_non_synthetic_directory_is_not_a_valid_input(self):
        root=self.case.root/'fake';root.mkdir()
        (root/'manifest.json').write_text('{"synthetic":false}',encoding='utf-8')
        (root/'history.sqlite3').touch()
        with self.assertRaises(ValueError):_read_manifest(root)
        self.assertFalse((root/'jobs.sqlite3').exists())

    def test_real_two_day_fixture_verifies_charts_scopes_and_ring_durations(self):
        metadata=_write(self.case.root/'small-month',_plan(days=2,cycles=2))
        archive=Archive(self.case.root/'small-month'/'history.sqlite3',min_free_bytes=0)
        checks=_read_checks(archive,metadata)
        self.assertTrue(all(row['state']=='passed' for row in checks),checks)
        rings=[row for row in checks if row['name'].endswith(':ring_attempts')]
        self.assertEqual(len(rings),2)
        self.assertTrue(all(row['result']['totals']['known_ring_seconds']==2 for row in rings))
        self.assertTrue(all(row['result']['other_queue_attempts']==0 for row in rings))
        month=next(row for row in checks if row['name']=='month:ring_attempt_bound')
        self.assertEqual(month['result']['totals']['attempts'],2)


if __name__=='__main__':unittest.main()
