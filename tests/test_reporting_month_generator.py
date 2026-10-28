import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools.generate_reporting_month import generate,plan,_plan,_write,verify,_day_events
from sanequeue.reporting.store import Archive


class ReportingMonthGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def test_default_is_dry_and_contract_is_exact_thirty_thousand_unique_calls(self):
        result=generate(self.root/'no-write')
        self.assertFalse((self.root/'no-write').exists());self.assertFalse(result['written'])
        self.assertEqual(result['calls_per_day'],1000);self.assertEqual(result['days'],30)
        self.assertEqual(result['unique_synthetic_call_ids'],30000);self.assertEqual(result['queue_visit_count'],33330)
        self.assertEqual(result['event_count'],193500);self.assertEqual(len(result['daily']),30)
        self.assertEqual(sum(row['unique_synthetic_call_ids'] for row in result['daily']),30000)
        self.assertEqual(result['expected']['overview'][0]['visits'],20010)
        self.assertEqual(result['expected']['overview'][1]['visits'],13320)
    def test_full_day_event_stream_has_exact_1000_ids_and_unique_source_keys(self):
        from datetime import date
        identities=set();keys=set();count=0
        for event in _day_events(date(2026,9,1),111):
            count+=1;key=(event.source,event.key);self.assertNotIn(key,keys);keys.add(key)
            if event.source=='queue_log':identities.add(event.payload['callid'])
        self.assertEqual(count,6450);self.assertEqual(len(identities),1000)
    def test_small_two_day_internal_fixture_matches_public_readers_and_noanswer_report(self):
        # The private cycle control keeps CI fast. Public generate/CLI always
        # require exactly 1,000 identities/day; they do not expose this switch.
        metadata=_plan('2026-09-01',2,cycles=1);path=self.root/'small'
        result=_write(path,metadata)
        self.assertEqual(result['verification']['unique_calls_verified'],20)
        self.assertEqual(result['verification']['queue_visits_verified'],22)
        self.assertTrue(result['verification']['ring_attempts_daily'])
        self.assertLessEqual(result['generation']['maximum_batch_events'],250)
        saved=json.loads((path/'manifest.json').read_text());self.assertEqual(saved,result)
        self.assertEqual(verify(Archive(path/'history.sqlite3'),saved),result['verification'])
    def test_rejects_existing_paths_invalid_ranges_and_non1000_public_counts(self):
        path=self.root/'existing';path.mkdir();keep=path/'keep';keep.write_text('unchanged')
        with self.assertRaises(FileExistsError):generate(path,write=True,days=1)
        self.assertEqual(keep.read_text(),'unchanged')
        for days in (0,32,True):
            with self.assertRaises(ValueError):plan(days=days)
        for calls in (10,999,1001,True):
            with self.assertRaises(ValueError):plan(calls_per_day=calls)
        with self.assertRaises(ValueError):generate(write=True)
    def test_metric_tamper_and_failed_verification_are_not_published(self):
        path=self.root/'bad';metadata=_plan('2026-09-01',1,cycles=1)
        with patch('tools.generate_reporting_month._actual',return_value={}):
            with self.assertRaises(AssertionError):_write(path,metadata)
        self.assertTrue((path/'FAILED.txt').exists());self.assertFalse((path/'manifest.json').exists())
        good=self.root/'good';result=_write(good,metadata);archive=Archive(good/'history.sqlite3')
        with archive.writer() as db:db.execute("UPDATE report_visits SET talk_seconds=999 WHERE queue='8001' AND talk_seconds=60")
        with self.assertRaises(AssertionError):verify(archive,result)
