from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from sanequeue.reporting.sql_source import SQLSource, cdr_page, identifier, FIELDS
from sanequeue.reporting.store import Archive, Event
from sanequeue.reporting.worker import cycle, SourceRunner
from sanequeue.reporting.facts import project_batch


class SQLTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.archive=Archive(Path(self.temp.name)/'archive.db',min_free_bytes=0)
        self.archive.initialize()

    def test_timestamp_groups_are_never_split(self):
        rows=[dict(calldate='a'),dict(calldate='b'),dict(calldate='b')]
        self.assertEqual(cdr_page(rows,2),rows[:1])
        with self.assertRaises(ValueError):cdr_page([dict(calldate='a')]*3,2)
        self.assertEqual(cdr_page(rows,3),rows)

    def test_identifiers_and_remote_connections_fail_closed(self):
        for name in ('x;DROP TABLE cdr','a.b','`cdr`','cdr\n'):
            with self.assertRaises(ValueError):identifier(name)
        with self.assertRaises(ValueError):SQLSource(dict(generation='../x'))

    def test_cel_checkpoint_anchor_prevents_silent_source_reset(self):
        cursor=Mock();cursor.__enter__=Mock(return_value=cursor);cursor.__exit__=Mock(return_value=False)
        connection=Mock();connection.cursor.return_value=cursor
        source=SQLSource({},connect=lambda:connection)
        source.schema['cel']=set(FIELDS['cel'])
        source.schema['cdr']=set(FIELDS['cdr'])
        self.archive.append([],checkpoint_source='sql:cel:',checkpoint=dict(after_id=10,anchor='old'))
        cursor.fetchone.side_effect=[dict(version='10.3.39-MariaDB'),None]
        with self.assertRaisesRegex(ValueError,'source_reset'):source.ingest(self.archive)
        self.assertEqual(self.archive.checkpoint('sql:cel:')['after_id'],10)
        connection.close.assert_called_once()
        self.assertTrue(any('TRANSACTION READ ONLY' in c.args[0] for c in cursor.execute.call_args_list))

    def test_incremental_cdr_import_is_idempotent(self):
        cursor=Mock();source=SQLSource({})
        source.schema['cdr']=set(FIELDS['cdr'])
        stamp=datetime(2026,10,25,10)
        cursor.fetchall.return_value=[dict(calldate=stamp,uniqueid='a',linkedid='a',duration=20,billsec=10)]
        self.assertEqual(source._cdr_backfill(cursor,self.archive,250,100)['cdr_inserted'],1)
        self.assertEqual(source._cdr_backfill(cursor,self.archive,250,110)['cdr_inserted'],0)
        self.assertEqual(self.archive.checkpoint('sql:cdr:')['after_time'],'2026-10-25 10:00:00')
        query,parameters=cursor.execute.call_args.args
        self.assertIn('WHERE `calldate`>%s',query)
        self.assertEqual(parameters,('2026-10-25 10:00:00',251))

    def test_delayed_cdr_lookup_retries_and_deduplicates_legs(self):
        self.archive.append([],update_state=lambda db:db.execute('INSERT INTO sql_cdr_pending VALUES(?,?,?,?,?)',('primary','call-a',0,0,0)))
        source=SQLSource({});source.schema['cdr']=set(FIELDS['cdr'])
        cursor=Mock();cursor.fetchall.return_value=[dict(calldate=datetime(2026,10,25),uniqueid='leg-b',linkedid='call-a',billsec=15)]
        self.assertEqual(source._cdr_pending(cursor,self.archive,10)['cdr_lookup_inserted'],1)
        self.assertEqual(source._cdr_pending(cursor,self.archive,11)['cdr_lookups'],0)
        for now in (20,40,80):source._cdr_pending(cursor,self.archive,now)
        with self.archive.reader() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM sql_cdr_pending').fetchone()[0],0)
        self.assertEqual(len(self.archive.page(source='cdr')),1)

    def test_missing_source_does_not_stop_projection_and_backs_off(self):
        self.archive.append([Event('cdr','a',1,'CDR',dict(uniqueid='a',billsec=12))])
        runner=SourceRunner()
        result=cycle(self.archive,activity_cache=str(Path(self.temp.name)/'missing'),runner=runner)
        self.assertFalse(result['activity']['ok'])
        self.assertEqual(result['projection']['processed'],1)
        self.assertTrue(cycle(self.archive,activity_cache='missing',runner=runner)['activity']['deferred'])

    def test_source_health_uses_allowlisted_reasons_without_exception_details(self):
        def missing_index():raise ValueError('reporting_source_index_required')
        status=SourceRunner().run(self.archive,'sql',missing_index)
        self.assertEqual(status['reason'],'reporting_source_index_required')
        def private_error():raise RuntimeError('secret-password=/private/config.ini')
        status=SourceRunner().run(self.archive,'sql',private_error)
        self.assertEqual(status['reason'],'source_unavailable')
        self.assertNotIn('secret-password',str(self.archive.checkpoint('health:sql')))

    def test_old_activity_schema_migrates_without_losing_history(self):
        with self.archive.writer() as db:
            db.execute('CREATE TABLE report_activity(pbx TEXT,source_key TEXT,event_id INTEGER,queue TEXT,agent TEXT,state TEXT,reason TEXT,starts REAL,ends REAL,on_duty INTEGER,coverage TEXT,PRIMARY KEY(pbx,source_key))')
            db.execute("INSERT INTO report_activity VALUES('primary','old',1,'8001','PJSIP/100','available','',1,2,1,'observed')")
        project_batch(self.archive)
        with self.archive.reader() as db:self.assertEqual(db.execute('SELECT canonical_agent FROM report_activity').fetchone()[0],'PJSIP/100')

    def test_recent_overlap_discovers_late_commits_without_moving_main_cursor(self):
        source=SQLSource({});source.schema['cdr']=set(FIELDS['cdr'])
        cursor=Mock();cursor.fetchall.return_value=[]
        now=datetime(2026,10,25,15).timestamp()
        first=source._cdr_overlap(cursor,self.archive,250,now)
        self.assertTrue(first['cdr_overlap_caught_up'])
        self.assertTrue(source._cdr_overlap(cursor,self.archive,250,now+1)['cdr_overlap_deferred'])
        cursor.fetchall.return_value=[dict(calldate=datetime(2026,10,25,14),uniqueid='late',linkedid='late')]
        self.assertEqual(source._cdr_overlap(cursor,self.archive,250,now+301)['cdr_overlap_inserted'],1)
        self.assertEqual(self.archive.checkpoint('sql:cdr:'),{})

    def test_unresolved_identity_is_retained_outside_hot_retry_queue(self):
        self.archive.append([],update_state=lambda db:db.execute('INSERT INTO sql_cdr_pending VALUES(?,?,?,?,?)',('primary','no-cdr',0,12,1)))
        source=SQLSource({});source.schema['cdr']=set(FIELDS['cdr'])
        cursor=Mock();cursor.fetchall.return_value=[]
        source._cdr_pending(cursor,self.archive,90000)
        with self.archive.reader() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM sql_cdr_pending').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT reason FROM sql_cdr_unresolved').fetchone()[0],'no_cdr_after_24h')

    def test_full_pending_queue_drains_before_new_cel_identity_is_enqueued(self):
        with self.archive.writer() as db:
            db.executemany('INSERT INTO sql_cdr_pending VALUES(?,?,?,?,?)',
                           [('primary','old-'+str(i),0,3,i+1) for i in range(20000)])
        cursor=Mock();cursor.__enter__=Mock(return_value=cursor);cursor.__exit__=Mock(return_value=False)
        connection=Mock();connection.cursor.return_value=cursor
        source=SQLSource({},connect=lambda:connection)
        source.schema={name:set(fields) for name,fields in FIELDS.items()}
        cursor.fetchone.return_value=dict(version='10.3.39-MariaDB')
        def rows():
            sql,parameters=cursor.execute.call_args.args
            if ' IN (' in sql:
                return [dict(calldate=datetime(2026,10,25),uniqueid='old-19999',linkedid='old-19999')]
            if 'WHERE `id`>%s' in sql:
                return [dict(id=1,eventtime=datetime(2026,10,25),eventtype='CHAN_END',uniqueid='new',linkedid='new')]
            return []
        cursor.fetchall.side_effect=rows
        result=source.ingest(self.archive,now=90000)
        self.assertEqual(result['cel_rows'],1)
        self.assertEqual(result['cdr_lookup_inserted'],1)
        self.assertEqual(self.archive.checkpoint('sql:cel:')['after_id'],1)
        with self.archive.reader() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM sql_cdr_pending').fetchone()[0],20000)
            self.assertIsNone(db.execute("SELECT 1 FROM sql_cdr_pending WHERE uid='old-19999'").fetchone())
            self.assertIsNotNone(db.execute("SELECT 1 FROM sql_cdr_pending WHERE uid='new'").fetchone())
        calls=[call.args[0] for call in cursor.execute.call_args_list]
        self.assertLess(next(i for i,q in enumerate(calls) if ' IN (' in q),
                        next(i for i,q in enumerate(calls) if 'WHERE `id`>%s' in q))

    def test_dense_identity_is_quarantined_without_blocking_healthy_work(self):
        with self.archive.writer() as db:
            db.executemany('INSERT INTO sql_cdr_pending VALUES(?,?,?,?,?)',
                           [('primary','dense',0,3,2),('primary','healthy',0,3,1)])
        source=SQLSource({});source.schema['cdr']=set(FIELDS['cdr'])
        cursor=Mock()
        def rows():
            parameters=cursor.execute.call_args.args[1]
            if 'dense' in parameters:
                return [dict(calldate=datetime(2026,10,25),uniqueid='dense',linkedid='dense',sequence=i) for i in range(501)]
            return [dict(calldate=datetime(2026,10,25),uniqueid='healthy',linkedid='healthy')]
        cursor.fetchall.side_effect=rows
        result=source._cdr_pending(cursor,self.archive,10)
        self.assertEqual(result['cdr_lookup_quarantined'],1)
        self.assertLessEqual(cursor.execute.call_count,4)
        with self.archive.reader() as db:
            self.assertEqual(db.execute('SELECT uid,reason FROM sql_cdr_unresolved').fetchone()[:],('dense','identity_fanout_limit'))
            self.assertEqual(db.execute('SELECT uid FROM sql_cdr_pending').fetchone()[0],'healthy')
        cursor.reset_mock()
        result=source._cdr_pending(cursor,self.archive,11)
        self.assertEqual(result['cdr_lookup_inserted'],1)
        with self.archive.reader() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM sql_cdr_pending').fetchone()[0],0)
        self.assertEqual(len(self.archive.page(source='cdr')),1)

    def test_aggregate_density_retries_a_healthy_identity_instead_of_quarantining_it(self):
        with self.archive.writer() as db:
            db.executemany('INSERT INTO sql_cdr_pending VALUES(?,?,?,?,?)',
                           [('primary','first',0,3,2),('primary','later',0,3,1)])
        source=SQLSource({});source.schema['cdr']=set(FIELDS['cdr'])
        cursor=Mock()
        def rows():
            parameters=cursor.execute.call_args.args[1]
            return [dict(calldate=datetime(2026,10,25),uniqueid='first',linkedid='first',sequence=i)
                    for i in range(501 if len(parameters)>1 else 1)]
        cursor.fetchall.side_effect=rows
        result=source._cdr_pending(cursor,self.archive,10)
        self.assertEqual(result['cdr_lookup_quarantined'],0)
        self.assertEqual(result['cdr_lookup_inserted'],1)
        self.assertLessEqual(cursor.execute.call_count,4)
        with self.archive.reader() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM sql_cdr_unresolved').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT uid FROM sql_cdr_pending').fetchone()[0],'later')
