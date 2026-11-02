from datetime import datetime
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sanequeue.reporting.report_plans import SavedReports,PlanConflict,PlanUnavailable,period_bounds
from sanequeue.reporting.store import QueryDeadline


class ReportPlanTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=SavedReports(Path(self.temp.name)/'plans.db');self.store.initialize()
        self.stamp=datetime(2026,10,24,9,tzinfo=ZoneInfo('Asia/Tehran')).timestamp()
        self.clock=patch('sanequeue.reporting.report_plans.time.time',return_value=self.stamp)
        self.now=self.clock.start();self.addCleanup(self.clock.stop)

    def plan(self,owner='owner',**changes):
        spec=dict(owner=owner,name='Daily report',queues=['8001'],enabled=True)
        spec.update(changes);return self.store.save(**spec)

    def test_periods_are_complete_tehran_days_and_gregorian_month(self):
        now=datetime(2024,3,1,12,tzinfo=ZoneInfo('Asia/Tehran')).timestamp()
        for period,first,last in (('yesterday','2024-02-29','2024-03-01'),
                                  ('last7days','2024-02-23','2024-03-01'),
                                  ('previous_month','2024-02-01','2024-03-01')):
            bounds=period_bounds(now,period)
            self.assertEqual(datetime.fromtimestamp(bounds['start'],ZoneInfo('Asia/Tehran')).date().isoformat(),first)
            self.assertEqual(datetime.fromtimestamp(bounds['end'],ZoneInfo('Asia/Tehran')).date().isoformat(),last)
            self.assertEqual(bounds['calendar'],'gregorian')
        self.assertEqual(period_bounds(now,'previous_month')['end']-period_bounds(now,'previous_month')['start'],29*86400)

    def test_owner_only_edits_versions_and_soft_archive_retain_history(self):
        plan=self.plan();self.assertEqual(plan['version'],1)
        self.assertIsNone(self.store.get(plan['id'],'other'))
        self.assertIsNone(self.plan(owner='other',ident=plan['id']))
        updated=self.plan(ident=plan['id'],queues=['8002','8001']);self.assertEqual(updated['version'],2)
        self.assertFalse(self.store.delete(plan['id'],'other'))
        self.assertTrue(self.store.delete(plan['id'],'owner'))
        archived=self.store.get(plan['id'],'owner')
        self.assertTrue(archived['archived']);self.assertFalse(archived['enabled']);self.assertEqual(archived['version'],3)
        with self.assertRaises(PlanConflict):self.plan(ident=plan['id'])
        with self.store._db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM report_plan_versions').fetchone()[0],3)
        self.assertEqual(len(self.store.list('owner')),1)

    def test_previous_persian_month_nowruz_leap_esfand_and_thirty_one_day_month(self):
        cases=[
            # 1400/01/01 follows the leap 1399 Esfand (30 days).
            ('2021-03-21','2021-02-19','2021-03-21',30),
            # Non-leap 1400 Esfand has 29 days.
            ('2022-03-21','2022-02-20','2022-03-21',29),
            # 1403/02: previous Farvardin has 31 days.
            ('2024-05-01','2024-03-20','2024-04-20',31),
            # New year in 1404 follows leap 1403 Esfand.
            ('2025-03-21','2025-02-19','2025-03-21',30),
        ]
        zone=ZoneInfo('Asia/Tehran')
        for current,first,last,days in cases:
            now=datetime.fromisoformat(current+'T12:00:00').replace(tzinfo=zone).timestamp()
            result=period_bounds(now,'previous_persian_month')
            begin=datetime.fromtimestamp(result['start'],zone);end=datetime.fromtimestamp(result['end'],zone)
            with self.subTest(current=current):
                self.assertEqual(begin.date().isoformat(),first)
                self.assertEqual(end.date().isoformat(),last)
                self.assertEqual((end.date()-begin.date()).days,days)
                self.assertEqual((begin.hour,begin.minute,begin.second),(0,0,0))
                self.assertEqual((end.hour,end.minute,end.second),(0,0,0))
                self.assertEqual(result['calendar'],'persian')
        plan=self.plan(period='previous_persian_month')
        self.assertEqual(plan['period'],'previous_persian_month')
        self.assertEqual(plan['calendar'],'persian')

    def test_persian_calendar_fallback_is_rejected_not_guessed(self):
        zone=ZoneInfo('Asia/Tehran')
        for date in ('1899-12-01','2100-01-01','1900-01-01'):
            now=datetime.fromisoformat(date+'T12:00:00').replace(tzinfo=zone).timestamp()
            # Negative Unix timestamps are rejected by the shared range guard;
            # modern out-of-calendar ranges must reject the Gregorian fallback.
            with self.subTest(date=date),self.assertRaises(ValueError):
                period_bounds(now,'previous_persian_month')

    def test_due_clock_weekdays_default_disabled_and_bound_twenty(self):
        self.plan(enabled=False)
        self.plan(at='10:00')
        self.plan(weekdays=[1])
        matching=[self.plan(weekdays=[0]) for _ in range(25)]
        due=self.store.due(self.stamp)
        self.assertEqual(len(due),20)
        self.assertTrue(all(row['date_key']=='2026-10-24' for row in due))
        self.assertTrue({row['id'] for row in due}.issubset({p['id'] for p in matching}))
        self.assertEqual(self.store.due(self.stamp-2*3600),[])

    def test_occurrence_unique_daily_and_reservation_does_not_dispatch_concurrently(self):
        plan=self.plan();first=self.store.reserve_due('attempt-a')
        self.assertEqual(first['plan_id'],plan['id']);self.assertEqual(first['attempts'],1)
        self.assertEqual(first['spec']['queues'],['8001'])
        self.assertEqual(first['spec']['destination'],'in_app')
        self.assertEqual(first['spec']['end'],period_bounds(self.stamp,'yesterday')['end'])
        self.assertIsNone(self.store.reserve_due('attempt-b'))
        self.assertEqual(self.store.due(self.stamp),[])
        self.assertTrue(self.store.finish(first['id'],'attempt-a','a'*32))
        self.assertIsNone(self.store.reserve_due('attempt-c'))
        self.assertIsNone(self.store.occurrence(first['id'],'other'))
        self.assertEqual(self.store.occurrences(plan['id'],'other'),[])
        self.assertNotIn('worker',self.store.occurrence(first['id'],'owner'))
        self.now.return_value=self.stamp+86400
        second=self.store.reserve_due('attempt-next-day')
        self.assertNotEqual(first['id'],second['id']);self.assertNotEqual(first['date_key'],second['date_key'])

    def test_frozen_scope_version_survives_edit_but_disabled_pending_cannot_run(self):
        plan=self.plan();job=self.store.reserve_due('attempt-a')
        self.store.defer(job['id'],'attempt-a')
        updated=self.plan(ident=plan['id'],queues=['8002'])
        self.now.return_value=self.stamp+31
        retried=self.store.reserve_due('attempt-b')
        self.assertEqual(retried['spec']['queues'],['8001']);self.assertEqual(retried['version'],1)
        self.assertEqual(updated['version'],2)
        self.plan(ident=plan['id'],enabled=False)
        self.assertFalse(self.store.finish(job['id'],'attempt-b','b'*32))
        self.assertIsNone(self.store.reserve_due('attempt-c'))
        self.assertEqual(self.store.occurrence(job['id'],'owner')['state'],'cancelled')

    def test_lease_recovery_three_attempts_and_stale_worker_fencing(self):
        self.plan();first=self.store.reserve_due('attempt-a')
        self.now.return_value=self.stamp+61
        self.assertFalse(self.store.finish(first['id'],'attempt-a','a'*32))
        second=self.store.reserve_due('attempt-b');self.assertEqual(second['attempts'],2)
        self.assertFalse(self.store.fail(first['id'],'attempt-a','export_failed'))
        self.now.return_value=self.stamp+122
        third=self.store.reserve_due('attempt-c');self.assertEqual(third['attempts'],3)
        self.now.return_value=self.stamp+183
        self.assertIsNone(self.store.reserve_due('attempt-d'))
        self.assertEqual(self.store.occurrence(first['id'],'owner')['state'],'failed')
        self.assertFalse(self.store.retry(first['id'],'owner'))

    def test_defer_no_attempt_cost_and_explicit_owner_retry_is_bounded(self):
        self.plan();job=self.store.reserve_due('attempt-a')
        self.assertTrue(self.store.defer(job['id'],'attempt-a','system_busy',delay=5))
        self.assertEqual(self.store.occurrence(job['id'],'owner')['attempts'],0)
        self.assertIsNone(self.store.reserve_due('too-early'))
        self.now.return_value=self.stamp+5
        self.assertEqual(self.store.reserve_due('attempt-b')['attempts'],1)
        self.assertTrue(self.store.fail(job['id'],'attempt-b','access_revoked'))
        self.assertFalse(self.store.retry(job['id'],'other'))
        self.assertTrue(self.store.retry(job['id'],'owner'))
        self.assertEqual(self.store.reserve_due('attempt-c')['attempts'],2)

    def test_retained_quota_validation_and_no_external_destination(self):
        for spec in (dict(name='x'*121),dict(queues=[]),dict(queues=['8001']*257),dict(period='persian_month'),
                     dict(at='24:00'),dict(at='8:00'),dict(weekdays=[]),dict(weekdays=[True]),
                     dict(enabled=1),dict(format='html')):
            with self.subTest(spec=spec),self.assertRaises(ValueError):self.plan(**spec)
        for _ in range(200):self.plan()
        with self.assertRaises(PlanConflict):self.plan()
        oldest=self.store.list('owner')[0];self.store.delete(oldest['id'],'owner')
        with self.assertRaises(PlanConflict):self.plan()
        with patch('sanequeue.reporting.report_plans.time.monotonic',side_effect=[0,1]),self.assertRaises(QueryDeadline):
            self.store.list('owner')

    def test_global_retained_quota_and_no_downtime_backfill(self):
        with patch('sanequeue.reporting.report_plans.MAX_PLANS',3):
            for index in range(3):self.plan(owner='owner-'+str(index))
            with self.assertRaises(PlanConflict):self.plan(owner='fourth-owner')
        self.now.return_value=self.stamp+2*86400
        occurrence=self.store.reserve_due('attempt-after-downtime')
        self.assertEqual(occurrence['date_key'],'2026-10-26')
        self.assertEqual(len(self.store.occurrences(occurrence['plan_id'],occurrence['owner'])),1)

    def test_archived_running_occurrence_is_cancelled_without_erasing_history(self):
        plan=self.plan();job=self.store.reserve_due('attempt-a')
        self.assertTrue(self.store.delete(plan['id'],'owner'))
        self.assertFalse(self.store.renew(job['id'],'attempt-a'))
        self.assertFalse(self.store.finish(job['id'],'attempt-a','a'*32))
        history=self.store.occurrences(plan['id'],'owner')
        self.assertEqual(history[0]['state'],'cancelled');self.assertEqual(history[0]['spec']['queues'],['8001'])

    def test_private_missing_and_busy_storage_fail_without_creating_or_leaking(self):
        missing=SavedReports(Path(self.temp.name)/'missing.db')
        with self.assertRaises(PlanUnavailable):missing.list('owner')
        self.assertFalse(missing.path.exists())
        if os.name!='nt':self.assertEqual(self.store.path.stat().st_mode&0o777,0o600)
        db=sqlite3.connect(self.store.path);db.execute('BEGIN IMMEDIATE')
        try:
            with self.assertRaisesRegex(PlanUnavailable,'^report_plan_store_unavailable$'):self.plan()
        finally:db.rollback();db.close()


if __name__=='__main__':unittest.main()
