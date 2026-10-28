import json
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sanequeue.reporting import backup
from sanequeue.reporting.agent_background import run, AggregationError, IDENTITY_SQL, _identities, Budget
from sanequeue.reporting.agent_rankings import rank_agents
from sanequeue.reporting.agent_metrics import report
from sanequeue.reporting.queries import Scope
from sanequeue.reporting.store import Archive
from sanequeue.reporting.store import QueryDeadline
from tools.generate_reporting_fixture import generate


class AgentBackgroundTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.meta = generate(self.root/'fixture', write=True)
        self.archive = Archive(self.root/'fixture'/'history.sqlite3')
        self.scope = Scope(('8001', '8002'))
        self.first = self.meta['activity_start']
        self.last = self.meta['activity_end']

    def bundle(self, name='bundle'):
        path = self.root/name
        backup.backup(self.archive.path, path)
        return path

    def test_rank_matches_interactive_and_presence_unions_shared_memberships(self):
        result = run(self.bundle(), self.root/'result', self.scope, self.first, self.last, min_samples=1)
        for metric in ('answered_count', 'avg_queue_talk_seconds'):
            expected = rank_agents(self.archive, self.scope, self.first, self.last, metric=metric, min_samples=1)
            self.assertEqual(result['rankings'][metric]['rows'], expected['rows'])
        reference = report(self.archive, self.scope, self.first, self.last, now=self.last)
        actual = {r['agent']: r for r in result['presence']}
        for row in reference['agents']:
            self.assertEqual(actual[row['agent']]['unique_on_duty_seconds'], row['on_duty_seconds'])
            self.assertEqual(actual[row['agent']]['unique_on_call_seconds'], row['on_call_seconds'])
            self.assertEqual(actual[row['agent']]['observed_seconds'], row['observed_seconds'])
        self.assertEqual(actual['PJSIP/100']['unique_on_duty_seconds'], 580)
        self.assertEqual(actual['PJSIP/100']['explicit_acw_seconds'], 20)
        self.assertIsNone(actual['PJSIP/200']['explicit_acw_seconds'])
        self.assertFalse(result['contract']['aht_occupancy_included'])
        self.assertEqual(json.loads((self.root/'result'/'result.json').read_text(encoding='utf-8')), result)

    def test_more_than_interactive_visit_cap_uses_pages_not_partial_rankings(self):
        with self.archive.writer() as db:
            db.row_factory = sqlite3.Row
            row = dict(db.execute("SELECT * FROM report_visits WHERE outcome='answered' AND agent LIKE 'Local/100%' AND coverage='observed' LIMIT 1").fetchone())
            columns = tuple(row)
            values = []
            for i in range(10001):
                copy = dict(row, id=f'{i+100000:064x}')
                values.append(tuple(copy[key] for key in columns))
            db.executemany('INSERT INTO report_visits('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')', values)
        before = rank_agents(self.archive, self.scope, self.first, self.last, min_samples=1)
        self.assertEqual(before['state'], 'limited')
        self.assertEqual(before['reason'], 'ranking_visit_limit')
        result = run(self.bundle(), self.root/'large', self.scope, self.first, self.last, min_samples=1)
        ranked = result['rankings']['answered_count']['rows']
        self.assertEqual(ranked[0]['agent'], 'PJSIP/100')
        self.assertEqual(ranked[0]['answered_count'], 10005)
        self.assertGreater(result['limits']['scanned_rows'], 10000)
        self.assertEqual(result['limits']['page_rows'], 200)

    def test_scope_cutoff_and_unknown_identity_fail_closed(self):
        scope = Scope(('8002',), ('Local/200@from-queue/n',), True, self.first)
        actual = run(self.bundle(), self.root/'self', scope, self.first, self.last, min_samples=1)
        self.assertEqual([r['agent'] for r in actual['rankings']['answered_count']['rows']], ['PJSIP/200'])
        with self.archive.writer() as db:
            db.row_factory = sqlite3.Row
            db.execute("UPDATE report_activity SET canonical_agent='PJSIP/other' WHERE agent LIKE 'Local/100%'")
            original = dict(db.execute("SELECT * FROM report_activity WHERE agent LIKE 'Local/100%' LIMIT 1").fetchone())
            original.update(source_key='conflicting', canonical_agent='PJSIP/ambiguous', starts=self.first, ends=self.last)
            columns = tuple(original)
            db.execute('INSERT INTO report_activity('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')', tuple(original.values()))
        with self.assertRaisesRegex(AggregationError, 'identity_unresolved'):
            run(self.bundle('ambiguous'), self.root/'ambiguous-result', self.scope, self.first, self.last)
        self.assertFalse((self.root/'ambiguous-result'/'result.json').exists())

    def test_presence_above_interval_cap_keeps_union_not_membership_sum(self):
        expected = report(self.archive, self.scope, self.first, self.last, now=self.last)
        with self.archive.writer() as db:
            db.row_factory = sqlite3.Row
            row = dict(db.execute("SELECT * FROM report_activity WHERE canonical_agent='PJSIP/100' AND state='available' LIMIT 1").fetchone())
            columns = tuple(row)
            db.executemany('INSERT INTO report_activity('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',
                           (tuple(dict(row, source_key='duplicate-'+str(i))[key] for key in columns) for i in range(10001)))
        with self.assertRaises(QueryDeadline):
            report(self.archive, self.scope, self.first, self.last, now=self.last)
        actual = run(self.bundle(), self.root/'many-intervals', self.scope, self.first, self.last)
        by_agent = {row['agent']: row for row in actual['presence']}
        for row in expected['agents']:
            self.assertEqual(by_agent[row['agent']]['unique_on_duty_seconds'], row['on_duty_seconds'])
        self.assertGreater(actual['limits']['scanned_rows'], 10000)

    def test_refuses_unsealed_stale_tampered_budget_and_existing_destination(self):
        bundle = self.bundle()
        destination = self.root/'exists'
        destination.mkdir()
        with self.assertRaises(FileExistsError):
            run(bundle, destination, self.scope, self.first, self.last)
        with self.assertRaisesRegex(AggregationError, 'row_limit'):
            run(bundle, self.root/'budget', self.scope, self.first, self.last, max_rows=1)
        self.assertFalse((self.root/'budget'/'result.json').exists())
        with self.archive.writer() as db:
            db.execute('UPDATE report_projection SET after_id=0')
        with self.assertRaisesRegex(AggregationError, 'projection_not_current'):
            run(self.bundle('stale'), self.root/'stale-result', self.scope, self.first, self.last)
        self.assertFalse((self.root/'stale-result').exists())
        (bundle/'archive.sqlite3-wal').write_bytes(b'')
        with self.assertRaisesRegex(backup.BackupError, 'unsealed'):
            run(bundle, self.root/'unsealed-result', self.scope, self.first, self.last)

    def test_checksum_rechecked_before_publication(self):
        bundle = self.bundle()
        verified = backup.verify(bundle)
        with patch('sanequeue.reporting.agent_background.backup.verify', side_effect=[verified, dict(verified, sha256='0'*64)]):
            with self.assertRaisesRegex(AggregationError, 'source_changed'):
                run(bundle, self.root/'changed', self.scope, self.first, self.last)
        self.assertFalse((self.root/'changed'/'result.json').exists())

    def test_cutoff_after_period_is_empty_and_unknown_state_disables_coverage(self):
        result = run(self.bundle(), self.root/'empty', Scope(('8001',), not_before=self.last+1),
                     self.first, self.last)
        self.assertEqual(result['presence'], [])
        self.assertEqual(result['rankings']['answered_count']['rows'], [])
        with self.archive.writer() as db:
            db.execute("UPDATE report_activity SET state='unrecognized' WHERE canonical_agent='PJSIP/100'")
        result = run(self.bundle('unknown'), self.root/'unknown-result', self.scope, self.first, self.last)
        row = next(r for r in result['presence'] if r['agent']=='PJSIP/100')
        self.assertFalse(row['coverage_complete'])
        self.assertGreater(row['unknown_state_interval_count'], 0)

    def test_publication_failure_does_not_leave_completed_result(self):
        bundle = self.bundle()
        with patch('sanequeue.reporting.backup.os.fsync', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                run(bundle, self.root/'failure', self.scope, self.first, self.last)
        self.assertFalse((self.root/'failure'/'result.json').exists())

    def test_identity_query_seeks_alias_index_despite_distinct_and_unrelated_rows(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.execute('CREATE TABLE activity(queue,alias,canonical,starts REAL,ends REAL,state,on_duty,coverage)')
        db.executemany('INSERT INTO activity VALUES(?,?,?,?,?,?,?,?)',
                       (('other', 'Local/other', 'PJSIP/'+str(i), 0, 1000, 'available', 1, 'observed')
                        for i in range(50000)))
        db.executemany('INSERT INTO activity VALUES(?,?,?,?,?,?,?,?)',
                       [('8001','Local/100','PJSIP/100',0,100,'available',1,'observed'),
                        ('8001','Local/100','PJSIP/200',25,75,'available',1,'observed'),
                        ('8001','Local/100','PJSIP/unknown',0,100,'available',1,'source_replaced')])
        db.execute("CREATE INDEX identity_source ON activity(queue,alias,canonical,starts,ends) WHERE coverage='observed'")
        db.execute('CREATE INDEX union_time ON activity(canonical,starts,ends)')
        _identities(db, Budget(30, 100000))
        plan = ' '.join(row[3] for row in db.execute('EXPLAIN QUERY PLAN '+IDENTITY_SQL, ('8001','Local/100',50,50)))
        self.assertIn('SEARCH identity_spans USING', plan)
        self.assertIn('identity_at', plan)
        self.assertIn('queue=? AND alias=?', plan)
        steps = []
        db.set_progress_handler(lambda: steps.append(1) or 0, 1000)
        for unused in range(20):
            self.assertEqual(set(db.execute(IDENTITY_SQL, ('8001','Local/100',50,50))),
                             {('PJSIP/100',), ('PJSIP/200',)})
        self.assertLess(len(steps), 5)

    def test_identity_spans_merge_state_changes_but_preserve_gaps_and_ambiguity(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.execute('CREATE TABLE activity(queue,alias,canonical,starts REAL,ends REAL,state,on_duty,coverage)')
        db.executemany('INSERT INTO activity VALUES(?,?,?,?,?,?,?,?)',
                       (('8001','Local/100','PJSIP/100',i,i+1,'available' if i%2 else 'on_call',1,'observed')
                        for i in range(10001)))
        db.executemany('INSERT INTO activity VALUES(?,?,?,?,?,?,?,?)',
                       [('8001','Local/100','PJSIP/100',10002,10003,'available',1,'observed'),
                        ('8001','Local/100','PJSIP/other',50,60,'available',1,'observed'),
                        ('8001','Local/100','PJSIP/replaced',0,20000,'available',1,'source_replaced')])
        db.execute("CREATE INDEX identity_source ON activity(queue,alias,canonical,starts,ends) WHERE coverage='observed'")
        _identities(db, Budget(30, 100000))
        self.assertEqual(db.execute('SELECT COUNT(*) FROM identity_spans').fetchone()[0], 3)
        self.assertEqual(set(db.execute(IDENTITY_SQL, ('8001','Local/100',55,55))),
                         {('PJSIP/100',), ('PJSIP/other',)})
        self.assertEqual(list(db.execute(IDENTITY_SQL, ('8001','Local/100',10001.5,10001.5))), [])
        self.assertEqual(list(db.execute(IDENTITY_SQL, ('8001','Local/100',9999,9999))), [('PJSIP/100',)])
