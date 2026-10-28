import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools.generate_reporting_fixture import generate,plan,verify,_new_destination
from sanequeue.reporting.store import Archive


class ReportingFixtureGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def test_default_is_dry_and_does_not_create_requested_path(self):
        path=self.root/'dry';result=generate(path)
        self.assertFalse(result['written']);self.assertFalse(path.exists())
        self.assertLess(result['event_count'],1000);self.assertEqual(result['queue_visit_count'],10)
        self.assertEqual(plan()['events_sha256'],result['events_sha256'])
    def test_actual_archive_matches_literal_overview_agents_builder_and_presence(self):
        path=self.root/'new';result=generate(path,write=True)
        self.assertTrue(result['written']);self.assertEqual(result['verification']['compared_queue_visits'],10)
        self.assertEqual(result['verification']['compared_agent_queue_groups'],4)
        self.assertTrue(all(result['verification'][key] for key in ('overview','agents','builder','agent_unique_activity','custom_csv')))
        saved=json.loads((path/'manifest.json').read_text(encoding='utf-8'));self.assertEqual(saved,result)
        self.assertEqual(verify(Archive(path/'history.sqlite3'),saved),result['verification'])
        self.assertEqual(saved['expected']['overview'][0]['answered'],4)
        self.assertEqual(saved['expected']['builder'][0]['answered_known'],3)
    def test_deterministic_repeat_stays_bounded_and_unions_memberships(self):
        first=generate(self.root/'a',write=True,repeat=2);second=generate(self.root/'b',write=True,repeat=2)
        self.assertEqual(first,second);self.assertEqual(first['verification']['compared_queue_visits'],20)
        self.assertEqual(first['expected']['agent_unique_activity'][0]['observed_seconds'],1200)
        self.assertLessEqual(plan(15)['event_count'],1000)
        with self.assertRaises(ValueError):plan(16)
    def test_refuses_existing_destination_and_production_paths_without_overwrite(self):
        existing=self.root/'existing';existing.mkdir();sentinel=existing/'keep';sentinel.write_text('unchanged')
        with self.assertRaises(FileExistsError):generate(existing,write=True)
        self.assertEqual(sentinel.read_text(),'unchanged')
        with self.assertRaises(ValueError):generate(write=True)
        for path in ('/etc/sanequeue-fixture-test','/opt/sanequeue-fixture-test','/var/lib/sanequeue-fixture-test'):
            with patch('tools.generate_reporting_fixture.Path.resolve',return_value=Path(path)):
                with self.assertRaises(ValueError):_new_destination(self.root/'fake')
    def test_failed_verification_is_never_marked_success_or_cleaned_recursively(self):
        path=self.root/'failure'
        with patch('tools.generate_reporting_fixture.verify',side_effect=AssertionError('expected fixture mismatch')):
            with self.assertRaises(AssertionError):generate(path,write=True)
        self.assertTrue((path/'history.sqlite3').exists());self.assertTrue((path/'FAILED.txt').exists())
        self.assertFalse((path/'manifest.json').exists())
    def test_changed_source_facts_make_verification_fail_instead_of_accepting_observed_values(self):
        path=self.root/'tampered';metadata=generate(path,write=True);archive=Archive(path/'history.sqlite3')
        with archive.writer() as db:db.execute("UPDATE report_visits SET talk_seconds=999 WHERE queue='8001' AND talk_seconds=60")
        with self.assertRaisesRegex(AssertionError,'fixture_metric_mismatch'):
            verify(archive,metadata)
