import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from sanequeue.reporting.store import Archive, Event, QueryDeadline
from sanequeue.reporting.sources import QueueLog, sql_event, import_json_lines
from sanequeue.reporting.correlate import relations
from sanequeue.reporting.privacy import display_number


class ReportingArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = Archive(self.root / 'reports.sqlite3', min_free_bytes=0)
        self.store.initialize()

    def tearDown(self):
        self.temporary.cleanup()

    def test_idempotent_versions_and_atomic_checkpoint(self):
        first = Event('cel', '1', 100, 'CHAN_START', {'uniqueid': 'a', 'channame': 'PJSIP/100-1'})
        self.assertEqual(self.store.append([first], checkpoint_source='cel', checkpoint={'id': 1}), 1)
        self.assertEqual(self.store.append([first]), 0)
        newer = Event('cel', '1', 100, 'CHAN_START', {'uniqueid': 'a', 'channame': 'PJSIP/100-2'})
        self.assertEqual(self.store.append([newer]), 1)
        self.store.append([first])
        with self.store.reader() as db:
            current = db.execute('SELECT event_id FROM source_items').fetchone()[0]
            self.assertEqual(current, 2)
        bad = Event('cel', '2', float('nan'), 'ANSWER', {})
        with self.assertRaises(ValueError):
            self.store.append([bad], checkpoint_source='cel', checkpoint={'id': 2})
        self.assertEqual(self.store.checkpoint('cel'), {'id': 1})
        self.assertEqual(len(self.store.page()), 2)
        with self.assertRaises(ValueError):
            self.store.append([Event('cel', 'bad', 100, 'ANSWER', [])])

    def test_projection_failure_rolls_back_source_and_checkpoint(self):
        with self.store.writer() as db:
            db.execute("CREATE TRIGGER reject_edge BEFORE INSERT ON evidence_edges BEGIN SELECT RAISE(ABORT,'test'); END")
        event = Event('cel', '3', 100, 'LOCAL_OPTIMIZE', {'uniqueid': 'u', 'extra': {'local_two': 'Local/100;2'}})
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.append([event], checkpoint_source='cel', checkpoint={'id': 3})
        self.assertEqual(self.store.page(), [])
        self.assertEqual(self.store.checkpoint('cel'), {})

    def test_pbx_scope_history_is_not_deleted_and_reader_is_bounded(self):
        self.store.append([Event('cel', '1', 1, 'ANSWER', {'uniqueid': 'u'})])
        other = Archive(self.store.path, pbx='other', min_free_bytes=0)
        other.append([Event('cel', '1', 1, 'ANSWER', {'uniqueid': 'u'})])
        self.assertEqual(len(self.store.page()), 1)
        self.assertEqual(self.store.status()['retention'], 'no_automatic_deletion')
        self.assertEqual(self.store.page()[0]['ts'], 1)
        short = Archive(self.store.path, read_seconds=.001)
        with self.assertRaises(QueryDeadline), short.reader() as db:
            db.execute('WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<100000000) SELECT sum(x) FROM n').fetchone()
        # The timed-out reader was closed and does not hold the WAL open.
        self.store.append([Event('cel', '2', 2, 'ANSWER', {'uniqueid': 'v'})])
        self.assertEqual(self.store.passive_checkpoint()[0], 0)

    def test_keyset_pages_and_no_follow_archive(self):
        self.store.append([Event('test', str(i), i, 'TEST', {}) for i in range(8)])
        a = self.store.page(limit=3)
        b = self.store.page(after=a[-1]['id'], limit=3)
        self.assertEqual(len({r['id'] for r in a+b}), 6)
        link = self.root / 'alias.db'
        try:
            link.symlink_to(self.store.path)
        except OSError:
            return  # Windows can deny symlink creation without developer mode.
        with self.assertRaises((ValueError, OSError)):
            Archive(link).initialize()

    def test_explicit_local_and_transfer_evidence_does_not_fabricate_consultation(self):
        self.store.append([
            Event('cel', '1', 100, 'LOCAL_OPTIMIZE', {'uniqueid': 'local-1', 'linkedid': 'root', 'extra': {'local_two': 'Local/100;2'}}),
            Event('cel', '2', 110, 'ATTENDEDTRANSFER', {'uniqueid': 'local-1', 'extra': {'transfer_target_channel_name': 'PJSIP/200-1'}}),
            Event('cel', '3', 111, 'BRIDGE_ENTER', {'uniqueid': 'local-1', 'extra': {'bridge_id': 'conference'}}),
        ])
        edges = relations(self.store, 'local-1')
        self.assertEqual({e['relation'] for e in edges}, {'linkedid_membership','local_optimize','attendedtransfer','bridge_enter'})
        with self.store.reader() as db:
            row = db.execute('SELECT transfer_type,consultation_duration,handoff_at FROM transfers').fetchone()
            self.assertEqual(tuple(row), ('attended', None, 110))
        # An optimization event itself is not a hangup.
        with self.store.reader() as db:
            self.assertIsNone(db.execute('SELECT ended FROM legs').fetchone()[0])


class ReportingSourceTests(unittest.TestCase):
    setUp = ReportingArchiveTests.setUp
    tearDown = ReportingArchiveTests.tearDown
    def test_queue_partial_line_resume_and_copytruncate_regrow(self):
        path = self.root / 'queue_log'
        path.write_bytes(b'100|u|8001|NONE|ENTERQUEUE||100|1\n101|u|8001|Local/100|CONNECT|1')
        importer = QueueLog(path)
        result = importer.ingest(self.store)
        self.assertFalse(result['caught_up'])
        self.assertEqual(len(self.store.page()), 1)
        with path.open('ab') as stream:
            stream.write(b'|dest|1\n')
        self.assertEqual(importer.ingest(self.store)['inserted'], 1)
        self.assertEqual(importer.ingest(self.store)['inserted'], 0)
        # Same inode, regrown beyond the old offset: tail anchoring detects it.
        path.write_bytes(b'200|v|8001|NONE|ENTERQUEUE||200|1\n' + b'201|v|8001|Local/200|CONNECT|1|dest|1\n' * 4)
        result = importer.ingest(self.store)
        self.assertTrue(result['rotation_detected'])
        self.assertTrue(result['coverage_gap'])
        self.assertTrue(importer.ingest(self.store)['coverage_gap'])
        self.assertTrue(self.store.checkpoint('queue_log')['generation'])
        self.assertEqual(self.store.page()[0]['payload']['callid'], 'u')

    def test_poison_line_does_not_pin_cursor(self):
        path = self.root / 'queue_log'
        path.write_bytes(b'x' * 90000 + b'\n100|u|8001|NONE|ENTERQUEUE||100|1\n')
        importer = QueueLog(path)
        for _ in range(5):
            result = importer.ingest(self.store, max_bytes=1000)
            if result['caught_up']:
                break
        self.assertTrue(result['caught_up'])
        self.assertEqual([r['kind'] for r in self.store.page()], ['INGEST_REJECTED','ENTERQUEUE'])

    def test_cel_and_legacy_cdr_datetime_and_continuation(self):
        row = dict(id=3,eventtime='2026-10-25 12:00:00',eventtype='ANSWER',uniqueid='u')
        event = sql_event('cel', row)
        self.assertTrue(event.payload['_source_time']['assumed'])
        self.assertEqual(event.timestamp, sql_event('cel', {**row,'eventtime':'2026-10-25T08:30:00+00:00'}).timestamp)
        cdr = dict(calldate='2026-10-25 12:00:00', uniqueid='u', linkedid='r',sequence=2,billsec=10)
        self.assertEqual(sql_event('cdr', cdr).key, sql_event('cdr', {**cdr, 'billsec':20}).key)
        path = self.root / 'cel.jsonl'
        path.write_text('\n'.join(json.dumps({**row,'id':i}) for i in range(4))+'\n', encoding='utf-8')
        self.assertFalse(import_json_lines(self.store,path,'cel',max_events=2)['caught_up'])
        self.assertTrue(import_json_lines(self.store,path,'cel',max_events=2)['caught_up'])
        self.assertEqual(import_json_lines(self.store,path,'cel')['inserted'], 0)
        with path.open('a') as stream:
            stream.write(json.dumps({**row,'id':99})+'\n')
        with self.assertRaisesRegex(ValueError, 'snapshot_modified'):
            import_json_lines(self.store,path,'cel')


class ReportingPrivacyTests(unittest.TestCase):
    def test_mask_and_scoped_stable_hmac(self):
        args=dict(secret=b'x'*32,tenant='org',pbx='pbx')
        self.assertEqual(display_number('۰۹۱۲۳۴۵۶۷۸۹','masked',**args),'0912***6789')
        self.assertEqual(display_number('100','masked',**args),'***')
        first=display_number('09123456789','pseudonymous',**args)
        self.assertEqual(first,display_number('۰۹۱۲۳۴۵۶۷۸۹','pseudonymous',**args))
        self.assertNotEqual(first,display_number('09123456789','pseudonymous',**{**args,'tenant':'other'}))
        self.assertEqual(display_number('09123456789','hidden',**args),'')
        with self.assertRaises(ValueError):display_number('09123456789','pseudonymous',**{**args,'secret':b'x'})
