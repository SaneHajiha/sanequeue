"""Private isolated store: no PBX, HTTP, packet capture or external services."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from sanequeue.diagnostics.store import Store,Scope,Conflict,Unavailable


class DiagnosticsStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=Store(self.root/'diagnostics.sqlite3',min_free_bytes=0);self.store.initialize()
        self.actor='a'*32;self.other='b'*32;self.scope=Scope(('8001',),actor=self.actor)

    def manual(self,queues=('8001',),reporter=None,**kwargs):
        description=kwargs.pop('description','متن خصوصی؛ مثال 09123456789')
        return self.store.create_manual('unexpected_disconnect',queues,reporter or self.actor,100,description=description,**kwargs)

    def observation(self,n=1,**changes):
        value=dict(incident_id='c'*64,kind='short_after_answer',queues=['8001'],generation='archive_v1',event_id=n,source='cel',rule='short_after_answer',rule_version=1,occurred_at=100+n,reason='short_duration')
        value.update(changes);return value

    def test_private_wal_separate_database_and_restart_without_deletion(self):
        row=self.manual(now=100)
        with closing(sqlite3.connect(self.store.path)) as db:self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0],'wal')
        reopened=Store(self.store.path,min_free_bytes=0);reopened.initialize()
        other=reopened.create_manual('media_quality',('8001',),self.actor,4000000,now=4000000)
        self.assertEqual(reopened.get(row['id'],self.scope)['description'],row['description'])
        self.assertEqual(len(reopened.page(self.scope)['rows']),2)
        self.assertNotEqual(row['id'],other['id'])
        absent=Store(self.root/'missing.sqlite3',min_free_bytes=0)
        with self.assertRaises(Unavailable):absent.page(self.scope)
        self.assertFalse(absent.path.exists())

    def test_scope_requires_every_queue_hides_global_and_supports_reporter_own(self):
        one=self.manual();both=self.manual(('8001','8002'));foreign=self.manual(('8002',));other=self.manual(reporter=self.other)
        global_row=self.store.create_manual('source_health',(),self.actor,101)
        self.assertIsNone(self.store.get(both['id'],self.scope));self.assertIsNone(self.store.get(foreign['id'],self.scope))
        self.assertIsNone(self.store.get(global_row['id'],self.scope))
        own=Scope(('8001','8002'),self.actor,True)
        self.assertEqual({r['id'] for r in self.store.page(own)['rows']},{one['id'],both['id'],foreign['id']})
        admin=Scope(pbx_admin=True)
        self.assertEqual(len(self.store.page(admin)['rows']),5)
        self.assertEqual(self.store.get(global_row['id'],admin)['kind'],'source_health')
        with self.assertRaises(PermissionError):self.store.page(Scope())
        with self.assertRaises(ValueError):self.store.page(Scope(('8001',),own_only=True))

    def test_keyset_same_timestamp_filters_and_no_scope_counts(self):
        ids={self.manual(now=100)['id'] for _ in range(5)}
        self.manual(('8002',),now=101)
        first=self.store.page(self.scope,limit=2,kind='unexpected_disconnect',status='open',start=99,end=101)
        second=self.store.page(self.scope,limit=2,before=first['next']);third=self.store.page(self.scope,limit=2,before=second['next'])
        result=[r['id'] for page in (first,second,third) for r in page['rows']]
        self.assertEqual(set(result),ids);self.assertEqual(len(result),5);self.assertIsNone(third['next']);self.assertNotIn('total',first)

    def test_atomic_actions_versions_private_notes_and_immutable_history(self):
        row=self.manual();changed=self.store.add_action(row['id'],self.scope,self.actor,'acknowledge',note='Private 09123456789',expected_version=1,now=110)
        self.assertEqual(changed['status'],'acknowledged');self.assertEqual(changed['version'],2)
        with self.assertRaises(Conflict):self.store.add_action(row['id'],self.scope,self.actor,'resolve',expected_version=1)
        resolved=self.store.add_action(row['id'],self.scope,self.actor,'resolve',expected_version=2)
        self.assertEqual(resolved['status'],'resolved');self.assertEqual(len(resolved['actions']),3)
        self.assertIsNone(self.store.add_action(row['id'],Scope(('8002',)),self.other,'comment'))
        with closing(sqlite3.connect(self.store.path)) as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM diagnostic_actions')
            with self.assertRaises(sqlite3.IntegrityError):db.execute("UPDATE diagnostic_actions SET note='changed'")

    def test_worker_cursor_replay_evidence_and_restart_are_idempotent(self):
        result=self.store.ingest_batch('cel_worker',0,1,[self.observation()],now=200)
        self.assertEqual(result,dict(inserted=1,cursor=1));self.assertEqual(self.store.checkpoint('cel_worker'),1)
        reopened=Store(self.store.path,min_free_bytes=0)
        self.assertEqual(reopened.ingest_batch('cel_worker',1,1,[self.observation()])['inserted'],0)
        result=reopened.ingest_batch('cel_worker',1,2,[self.observation(2)],now=300)
        row=reopened.get('c'*64,self.scope);self.assertEqual(row['evidence_count'],2);self.assertEqual(len(row['evidence']),2)
        self.assertEqual((row['first_seen'],row['last_seen']),(101,102));self.assertEqual(row['confidence'],'suspected')
        self.assertEqual(row['status'],'needs_review')
        with self.assertRaises(Conflict):reopened.ingest_batch('cel_worker',1,2,[])
        with self.assertRaises(Conflict):reopened.ingest_batch('cel_worker',2,3,[self.observation(2,reason='unknown')])
        self.assertEqual(reopened.checkpoint('cel_worker'),2)

    def test_failed_batch_rolls_back_evidence_incident_and_checkpoint_together(self):
        self.store.ingest_batch('cel_worker',0,1,[self.observation()])
        with self.assertRaises(Conflict):
            self.store.ingest_batch('cel_worker',1,3,[self.observation(2),self.observation(3,queues=['8002'])])
        self.assertEqual(self.store.checkpoint('cel_worker'),1)
        row=self.store.get('c'*64,self.scope);self.assertEqual(row['evidence_count'],1);self.assertEqual(len(row['evidence']),1)
        self.assertEqual(self.store.ingest_batch('cel_worker',1,2,[self.observation(2)])['inserted'],1)

    def test_strict_payload_enums_limits_and_global_source_health(self):
        for changes in ({'raw_payload':{'phone':'09123456789'}},{'event_id':True},{'rule':'09123456789'}, {'kind':'sip-debug'},{'occurred_at':float('nan')},{'sip_status':999},{'q850_cause':0}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.store.ingest_batch('cel_worker',0,1,[self.observation(**changes)])
        for scope,kwargs in [(self.scope,{'limit':101}),(self.scope,{'before':[0,'not-id']}),(self.scope,{'status':'bad'})]:
            with self.assertRaises(ValueError):self.store.page(scope,**kwargs)
        with self.assertRaises(ValueError):self.manual(description='x'*1001)
        with self.assertRaises(ValueError):self.store.ingest_batch('cel_worker',0,101,[self.observation(n) for n in range(1,102)])
        with self.assertRaises(ValueError):self.store.create_manual('source_health',('8001',),self.actor,100)

    def test_pbx_isolation_no_http_ddl_and_wrong_database_refused(self):
        row=self.manual();other=Store(self.store.path,pbx='secondary',min_free_bytes=0);other.initialize()
        self.assertIsNone(other.get(row['id'],Scope(pbx_admin=True)))
        original=sqlite3.connect;commands=[]
        def connect(*args,**kwargs):
            db=original(*args,**kwargs);db.set_trace_callback(commands.append);return db
        with patch('sanequeue.diagnostics.store.sqlite3.connect',connect):
            self.store.get(row['id'],self.scope);self.store.page(self.scope)
        self.assertFalse(any(q.lstrip().upper().startswith(('CREATE','ALTER','INSERT','UPDATE','DELETE')) for q in commands))
        self.assertTrue(any('query_only=ON' in q for q in commands))
        wrong=self.root/'history.sqlite3'
        with closing(sqlite3.connect(wrong)) as db:db.execute('CREATE TABLE events(id INTEGER PRIMARY KEY)');db.commit()
        with self.assertRaises(Unavailable):Store(wrong,min_free_bytes=0).initialize()
        with closing(sqlite3.connect(wrong)) as db:self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='diagnostic_meta'").fetchone())

    def test_busy_writer_fails_bounded_and_does_not_drop_existing_incident(self):
        row=self.manual()
        with closing(sqlite3.connect(self.store.path)) as db:
            db.execute('BEGIN IMMEDIATE')
            with self.assertRaises(Unavailable):self.manual()
            db.rollback()
        self.assertEqual(self.store.get(row['id'],self.scope)['id'],row['id'])

    def test_own_only_action_cannot_impersonate_or_manage_case(self):
        row=self.manual();own=Scope(('8001',),self.actor,True)
        for actor,action in [(self.other,'comment'),(self.actor,'resolve'),(self.actor,'acknowledge')]:
            with self.subTest(actor=actor,action=action),self.assertRaises(PermissionError):self.store.add_action(row['id'],own,actor,action)
        changed=self.store.add_action(row['id'],own,self.actor,'comment',note='متن خصوصی')
        self.assertEqual(changed['status'],'open');self.assertEqual(changed['actions'][0]['note'],'متن خصوصی')

    def test_bound_worker_checkpoint_cannot_silently_follow_replaced_source(self):
        empty=self.store.worker_checkpoint('cel_worker');self.assertEqual(empty['cursor'],0);self.assertIsNone(empty['generation'])
        binding=dict(generation='archive_v1',archive_identity='d'*64,anchor='e'*64,projection_version=8)
        self.store.ingest_batch('cel_worker',0,1,[self.observation(visit_id='f'*64)],binding=binding)
        first=self.store.worker_checkpoint('cel_worker');self.assertEqual(first,{'cursor':1,**binding})
        second={**binding,'anchor':'f'*64}
        self.store.ingest_batch('cel_worker',1,2,[self.observation(2,visit_id='f'*64)],binding=second,expected_binding=first)
        self.assertEqual(self.store.worker_checkpoint('cel_worker'),{'cursor':2,**second})
        for mutation in ({'generation':'archive_v2'},{'archive_identity':'a'*64},{'projection_version':9}):
            with self.subTest(mutation=mutation),self.assertRaises(Conflict):
                self.store.ingest_batch('cel_worker',2,3,[self.observation(3,visit_id='f'*64)],binding={**second,**mutation},expected_binding=second)
        self.assertEqual(self.store.checkpoint('cel_worker'),2)
        self.assertEqual(self.store.get('c'*64,self.scope)['visit_id'],'f'*64)
        with self.assertRaises(Conflict):self.store.ingest_batch('cel_worker',2,3,[self.observation(3,visit_id='a'*64)],binding=second,expected_binding=second)
        with self.assertRaises(ValueError):self.store.ingest_batch('cel_worker',2,3,[self.observation(3,confidence='observed')],binding=second,expected_binding=second)

    def test_review_targets_are_atomic_and_cannot_change_manual_reports(self):
        self.store.ingest_batch('cel_worker',0,1,[self.observation()])
        # Only a manager's explicit resolution changed the initial needs-review.
        resolved=self.store.add_action('c'*64,self.scope,self.actor,'resolve')
        self.assertEqual(resolved['status'],'resolved')
        manual=self.manual()
        with self.assertRaises(Conflict):self.store.ingest_batch('cel_worker',1,1,[],review_incidents=['c'*64,manual['id']])
        self.assertEqual(self.store.get('c'*64,self.scope)['status'],'resolved')
        self.store.ingest_batch('cel_worker',1,1,[],review_incidents=['c'*64])
        result=self.store.get('c'*64,self.scope);self.assertEqual(result['status'],'needs_review')
        self.assertEqual(result['evidence_count'],1);self.assertEqual(result['actions'][0]['action'],'source_review')

    def test_read_deadline_and_disk_pressure_fail_without_deleting_history(self):
        for n in range(10):self.manual(now=100+n)
        ticks=iter([0])
        with patch('sanequeue.diagnostics.store.time.monotonic',side_effect=lambda:next(ticks,2)):
            with self.assertRaises(Unavailable):self.store.page(self.scope)
        self.assertEqual(len(self.store.page(self.scope)['rows']),10)
        with patch('sanequeue.diagnostics.store.shutil.disk_usage',return_value=type('Disk',(),{'free':0})()):
            protected=Store(self.store.path,min_free_bytes=1)
            with self.assertRaises(Unavailable):protected.create_manual('media_quality',('8001',),self.actor,100)
        self.assertEqual(len(self.store.page(self.scope)['rows']),10)

    def test_unicode_queue_ids_are_exact_scoped_values_and_controls_are_rejected(self):
        name='صف پشتیبانی فارسی'
        row=self.manual((name,))
        self.assertEqual(self.store.get(row['id'],Scope((name,)))['queues'],[name])
        self.assertIsNone(self.store.get(row['id'],Scope(('صف پشتيباني فارسي',))))
        for invalid in ('','a\n8001','صف\tپشتیبانی','a'*129):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):self.manual((invalid,))

    def test_rule_threshold_is_typed_persisted_and_immutable_per_incident(self):
        five=self.observation(rule_parameters={'threshold_seconds':5})
        ten=self.observation(2,incident_id='d'*64,rule_parameters={'threshold_seconds':10})
        self.store.ingest_batch('cel_worker',0,2,[five,ten])
        self.assertEqual(self.store.get('c'*64,self.scope)['rule_parameters'],{'threshold_seconds':5.0})
        reopened=Store(self.store.path,min_free_bytes=0);reopened.initialize()
        self.assertEqual(reopened.get('d'*64,self.scope)['rule_parameters'],{'threshold_seconds':10.0})
        policies={r['id']:r['rule_parameters'] for r in reopened.page(self.scope)['rows']}
        self.assertEqual(policies['d'*64]['threshold_seconds'],10)
        self.assertEqual(reopened.ingest_batch('cel_worker',2,2,[five])['inserted'],0)
        with self.assertRaises(Conflict):reopened.ingest_batch('cel_worker',2,3,[self.observation(3,rule_parameters={'threshold_seconds':10})])
        self.assertEqual(reopened.checkpoint('cel_worker'),2)
        with closing(sqlite3.connect(self.store.path)) as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('UPDATE diagnostic_policy SET threshold_seconds=60')
        for policy in ({'threshold_seconds':True},{'threshold_seconds':0},{'threshold_seconds':61},{'threshold_seconds':float('nan')},{'threshold_seconds':5,'payload':'raw'}):
            with self.subTest(policy=policy),self.assertRaises(ValueError):self.store.ingest_batch('cel_worker',2,3,[self.observation(3,rule_parameters=policy)])
        manual=self.manual()
        self.assertIsNone(self.store.get(manual['id'],self.scope)['rule_parameters'])

    def delayed_sqlite(self,sql_marker,elapsed):
        """Advance monotonic time during real SQLite work, not wall-clock sleep."""
        original=sqlite3.connect;clock=[0.0]
        def connect(*args,**kwargs):
            db=original(*args,**kwargs)
            def trace(sql):
                if sql_marker in sql:clock[0]=elapsed
            db.set_trace_callback(trace)
            return db
        return clock,connect

    def test_cold_start_schema_has_separate_bounded_budget_and_can_retry(self):
        for elapsed,succeeds in [(2.0,True),(6.0,False)]:
            target=Store(self.root/('cold-'+str(elapsed)+'.sqlite3'),min_free_bytes=0)
            clock,connect=self.delayed_sqlite('CREATE TABLE IF NOT EXISTS diagnostic_incidents',elapsed)
            with self.subTest(elapsed=elapsed),patch('sanequeue.diagnostics.store.time.monotonic',side_effect=lambda:clock[0]),patch('sanequeue.diagnostics.store.sqlite3.connect',connect):
                if succeeds:target.initialize()
                else:
                    with self.assertRaisesRegex(Unavailable,'^diagnostics_query_deadline$'):target.initialize()
            # A timed-out startup can be initialized again; it never needs reset
            # or deletion, and ordinary reads do not perform schema repair.
            target.initialize();self.assertEqual(target.page(self.scope)['rows'],[])

    def test_normal_write_keeps_short_budget_and_interrupt_has_safe_reason(self):
        row=self.manual()
        # Existing action history makes the real post-write detail query execute
        # enough SQLite VM steps for the bounded progress handler to run.
        for n in range(20):self.store.add_action(row['id'],self.scope,self.actor,'comment',note='Known action '+str(n))
        clock,connect=self.delayed_sqlite('INSERT INTO diagnostic_actions',2.0)
        with patch('sanequeue.diagnostics.store.time.monotonic',side_effect=lambda:clock[0]),patch('sanequeue.diagnostics.store.sqlite3.connect',connect):
            with self.assertRaisesRegex(Unavailable,'^diagnostics_query_deadline$'):
                self.store.add_action(row['id'],self.scope,self.actor,'comment',note='private /secret/path 09123456789')
        current=self.store.get(row['id'],self.scope)
        self.assertEqual(current['version'],21);self.assertEqual(len(current['actions']),21)
        self.assertNotIn('private',str(current['actions']))


if __name__=='__main__':unittest.main()
