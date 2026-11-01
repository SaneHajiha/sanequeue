import unittest
from unittest.mock import patch
from tests import test_reporting_queries as fixtures
from sanequeue.reporting.facts import project_batch
from sanequeue.reporting.queries import Scope,visits
from sanequeue.reporting.repair_exit_key import step,CHECKPOINT
from sanequeue.reporting import visit_snapshots


class ExitKeyRepairTests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.ReportTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        c=self.case
        c.archive.append([c.event('a','8001','ENTERQUEUE',0,['','100','4']),
                          c.event('a','8001','EXITWITHKEY',25,['9','2','4','25']),
                          c.event('b','8001','ENTERQUEUE',30,['','200','3']),
                          c.event('b','8001','EXITWITHKEY',50,['7','1','3','20'])])
        while project_batch(c.archive,limit=2)['processed']:pass
        with c.archive.writer() as db:db.execute("UPDATE report_visits SET wait_seconds=2 WHERE pbx='primary'")

    def rows(self):
        c=self.case
        return {row['caller']:row['wait_seconds'] for row in visits(c.archive,Scope(('8001',)),c.stamp,c.stamp+100)['rows']}

    def test_resumes_across_bounded_steps_and_keeps_pinned_snapshots(self):
        c=self.case;old=visit_snapshots.capture(c.archive)
        first=step(c.archive,scan_limit=2,max_calls=1);self.assertFalse(first['completed']);self.assertLessEqual(first['rebuilt_calls'],1)
        self.assertEqual(self.rows(),{'100':25,'200':2})
        second=step(c.archive,scan_limit=2,max_calls=1);self.assertLessEqual(second['rebuilt_calls'],1)
        third=step(c.archive,scan_limit=2,max_calls=1);self.assertTrue(third['completed'])
        self.assertEqual(self.rows(),{'100':25,'200':20})
        self.assertEqual(step(c.archive)['rebuilt_calls'],0)
        with c.archive.reader() as db:
            old_rows=visit_snapshots.page(db,c.archive.pbx,old,Scope(('8001',)),c.stamp,c.stamp+100)
        self.assertEqual({row['wait_seconds'] for row in old_rows},{2})
        self.assertEqual(c.archive.checkpoint(CHECKPOINT)['target_id'],4)

    def test_failure_rolls_back_both_visit_and_progress(self):
        with patch('sanequeue.reporting.repair_exit_key._rebuild_visits',side_effect=ValueError('failed')):
            with self.assertRaises(ValueError):step(self.case.archive,scan_limit=2)
        self.assertEqual(self.rows(),{'100':2,'200':2})
        self.assertEqual(self.case.archive.checkpoint(CHECKPOINT),{})

    def test_limits_reject_unbounded_or_invalid_values(self):
        for kwargs in ({'scan_limit':501},{'max_calls':11},{'seconds':4},{'scan_limit':0}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):step(self.case.archive,**kwargs)

if __name__=='__main__':unittest.main()
