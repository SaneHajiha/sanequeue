"""Metric contracts: boundaries, unknown evidence, RBAC and real denominators."""
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

from sanequeue.reporting.store import Archive, Event, QueryDeadline
from sanequeue.reporting.facts import project_batch
from sanequeue.reporting.queries import Scope
from sanequeue.reporting.analytics import dashboard, _bucket


class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.archive = Archive(Path(folder.name)/'reports.db', min_free_bytes=0)
        self.archive.initialize()
        self.start = datetime(2026, 10, 24, tzinfo=ZoneInfo('Asia/Tehran')).timestamp()
        self.counter = 0

    def visit(self, uid, wait, outcome='COMPLETECALLER', queue='8001', offset=0, entry=True):
        def event(kind, stamp, values):
            self.counter += 1
            return Event('queue_log', str(self.counter), stamp, kind,
                         dict(callid=uid, queue=queue, agent='PJSIP/100', values=values))
        rows = []
        if entry:
            rows.append(event('ENTERQUEUE', self.start+offset, ['', 'private-number']))
        if outcome != 'ABANDON':
            rows.append(event('CONNECT', self.start+offset+wait, [str(wait)]))
        rows.append(event(outcome, self.start+offset+wait+30,
                          ['1', '1', str(wait)] if outcome == 'ABANDON' else [str(wait), '30']))
        self.archive.append(rows)
        while project_batch(self.archive)['processed']:
            pass

    def test_percentiles_policy_and_previous_period(self):
        for i, wait in enumerate((0, 10, 20, 30, 40)):
            self.visit(str(i), wait, offset=i*100)
        self.visit('abandon', 5, outcome='ABANDON', offset=800)
        self.visit('hidden', 100, queue='8002')
        result = dashboard(self.archive, Scope(('8001',)), self.start, self.start+86400,
                           sla_basis='offered_known_wait', short_abandon_seconds=6, compare=True)
        totals = result['totals']
        self.assertEqual((totals['visits'], totals['sla_numerator'], totals['sla_denominator']), (6, 3, 5))
        self.assertEqual(totals['sla_percent'], 60)
        self.assertEqual(totals['asa_seconds'], 20)
        self.assertAlmostEqual(totals['abandon_percent'], 100/6)
        quantiles = result['queues'][0]['wait_percentiles']
        self.assertEqual((quantiles['samples'], quantiles['p50_seconds'], quantiles['p90_seconds'],
                          quantiles['p95_seconds']), (6, 10, 40, 40))
        self.assertEqual(result['previous']['metrics']['visits'], 0)
        self.assertEqual(result['heatmap'][0]['weekday'], 0)  # Saturday.
        self.assertNotIn('private-number', str(result))
        self.assertIsNone(result['policy']['aht'])

    def test_orphaned_completions_do_not_inflate_offered_sla(self):
        self.visit('orphan', 1, entry=False)
        result = dashboard(self.archive, Scope(('8001',)), self.start, self.start+86400,
                           sla_basis='offered_known_wait')
        self.assertEqual(result['totals']['known_entries'], 0)
        self.assertEqual(result['totals']['sla_numerator'], 0)
        self.assertIsNone(result['totals']['sla_percent'])
        self.assertEqual(result['totals']['incomplete'], 1)

    def test_scope_cutoff_and_exclusive_end(self):
        self.visit('start', 10)
        self.visit('end', 10, offset=86400)
        scope = Scope(('8001',), ('PJSIP/100',), True)
        result = dashboard(self.archive, scope, self.start, self.start+86400)
        self.assertEqual(result['totals']['visits'], 1)
        for scope in (Scope(()), Scope(('8001',), (), True),
                      Scope(('8001',), ('PJSIP/200',), True), Scope(('8001',), not_before=self.start+1)):
            with self.subTest(scope=scope):
                result = dashboard(self.archive, scope, self.start, self.start+86400)
                self.assertEqual(result['totals']['visits'], 0)
                self.assertIsNone(result['totals']['average_wait_seconds'])
                self.assertIsNone(result['totals']['sla_percent'])

    def test_calendar_and_input_validation(self):
        self.assertEqual(_bucket(self.start-1, 'day'), '2026-10-23')
        self.assertEqual(_bucket(self.start+86400, 'week'), '2026-10-24')
        self.assertEqual(_bucket(self.start, 'month'), '2026-10')
        project_batch(self.archive)
        for kwargs in (dict(interval='raw'), dict(sla_seconds='nan'), dict(sla_basis='bad'),
                       dict(short_abandon_seconds=-1), dict(sla_seconds=0)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                dashboard(self.archive, Scope(('8001',)), self.start, self.start+100, **kwargs)


if __name__ == '__main__':
    unittest.main()
