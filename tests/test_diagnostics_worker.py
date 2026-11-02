"""Synthetic archive-only worker; no AMI, PBX SQL, media or commands."""
from contextlib import redirect_stdout,redirect_stderr
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from sanequeue.diagnostics.store import Store,Scope,Conflict
from sanequeue.diagnostics.worker import Worker,SourceUnavailable,main
from sanequeue.reporting.facts import project_batch
from sanequeue.reporting.store import Archive,Event


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.archive=Archive(self.root/'history.db',min_free_bytes=0);self.archive.initialize()
        self.store=Store(self.root/'diagnostics.db',min_free_bytes=0);self.store.initialize()
        self.generation='archive_'+'a'*32
        self.worker=Worker(self.archive,self.store,generation=self.generation)
        self.admin=Scope(pbx_admin=True)

    def call(self,uid='private-caller-uid',queue='8001',*,start=100,talk=2,key='call'):
        return [
            Event('queue_log',key+'enter',start,'ENTERQUEUE',dict(callid=uid,queue=queue,agent='NONE',values=['','09999999999'])),
            Event('queue_log',key+'answer',start+1,'CONNECT',dict(callid=uid,queue=queue,agent='Local/100@from-queue/n',values=['1','private-peer-uid','0'])),
            Event('queue_log',key+'end',start+1+talk,'COMPLETECALLER',dict(callid=uid,queue=queue,agent='Local/100@from-queue/n',values=['1',str(talk)]))]

    def seed(self,events):
        self.archive.append(events)
        while project_batch(self.archive)['processed']:pass

    def test_restart_replay_is_idempotent_private_and_requires_human_review(self):
        self.seed(self.call())
        result=self.worker.run_batch(now=200)
        self.assertEqual((result['processed'],result['inserted'],result['cursor']),(3,1,3))
        self.assertTrue(result['findings_require_review']);self.assertFalse(result['current_state_verified'])
        restarted=Worker(self.archive,Store(self.store.path,min_free_bytes=0),generation=self.generation)
        self.assertEqual(restarted.run_batch(now=201)['inserted'],0)
        row=self.store.page(self.admin)['rows'][0]
        self.assertEqual((row['status'],row['confidence'],row['kind']),('needs_review','suspected','short_after_answer'))
        self.assertEqual(row['description'],'');self.assertEqual(len(row['visit_id']),64)
        detail=self.store.get(row['id'],self.admin);self.assertEqual(detail['evidence_count'],1)
        self.assertEqual(detail['evidence'][0]['reason'],'short_duration')
        with self.store._db() as db:
            all_values=' '.join(str(tuple(row)) for table in ('diagnostic_incidents','diagnostic_queues','diagnostic_evidence','diagnostic_worker_bindings') for row in db.execute('SELECT * FROM '+table))
        for private in ('09999999999','private-caller-uid','private-peer-uid','Local/100','hangupsource','agent_hangup','root_cause','human_intent'):
            self.assertNotIn(private,all_values)

    def test_event_and_observation_caps_resume_without_skipping(self):
        events=[]
        for number in range(125):events+=self.call(str(number),start=number*10+100,key=str(number))
        self.seed(events)
        first=self.worker.run_batch(limit=1000,now=2000)
        self.assertEqual((first['processed'],first['inserted'],first['cursor']),(300,100,300))
        second=self.worker.run_batch(limit=1000,now=2001)
        self.assertEqual((second['processed'],second['inserted'],second['cursor']),(75,25,375))
        self.assertEqual(self.worker.run_batch(limit=2)['processed'],0)
        self.assertEqual(len(self.store.page(self.admin,limit=100)['rows']),100)
        for limit in (0,1001,True):
            with self.subTest(limit=limit),self.assertRaises(ValueError):self.worker.run_batch(limit=limit)

    def test_custom_threshold_policy_is_reproducible_after_restart_and_isolated_from_default(self):
        self.seed(self.call(talk=8))
        self.assertEqual(self.worker.run_batch()['inserted'],0)
        custom=Worker(self.archive,self.store,generation=self.generation,threshold_seconds=10)
        self.assertNotEqual(custom.name,self.worker.name)
        self.assertEqual(custom.run_batch()['inserted'],1)
        row=self.store.page(self.admin)['rows'][0]
        self.assertEqual(row['rule_parameters'],{'threshold_seconds':10.0})
        reopened=Store(self.store.path,min_free_bytes=0)
        self.assertEqual(reopened.get(row['id'],self.admin)['rule_parameters'],{'threshold_seconds':10.0})
        same=Worker(self.archive,reopened,generation=self.generation,threshold_seconds=10.0)
        self.assertEqual(same.run_batch()['inserted'],0)
        self.assertEqual(reopened.get(row['id'],self.admin)['evidence_count'],1)

    def test_projection_lag_does_not_publish_or_advance(self):
        project_batch(self.archive)
        self.archive.append(self.call())
        result=self.worker.run_batch()
        self.assertEqual(result['state'],'projection_lag')
        self.assertEqual(self.store.worker_checkpoint(self.worker.name)['cursor'],0)
        self.assertEqual(self.store.page(self.admin)['rows'],[])
        while project_batch(self.archive)['processed']:pass
        self.assertEqual(self.worker.run_batch()['inserted'],1)

    def test_all_current_queues_are_required_not_just_the_completing_queue(self):
        self.seed(self.call()+self.call(queue='8002',start=200,key='foreign'))
        self.worker.run_batch()
        self.assertEqual(self.store.page(Scope(('8001',)))['rows'],[])
        rows=self.store.page(Scope(('8001','8002')))['rows']
        self.assertEqual(len(rows),2)
        self.assertTrue(all(row['queues']==['8001','8002'] for row in rows))

    def test_unrepresentable_foreign_queue_scope_suppresses_entire_identity(self):
        self.seed(self.call()+self.call(queue='x'*129,start=200,key='unsupported'))
        result=self.worker.run_batch()
        self.assertEqual(result['inserted'],0)
        self.assertEqual(self.store.page(self.admin)['rows'],[])

    def test_persian_queue_scope_is_preserved_without_normalization(self):
        name='پشتیبانی_۱'
        self.seed(self.call(queue=name))
        self.assertEqual(self.worker.run_batch()['inserted'],1)
        rows=self.store.page(Scope((name,)))['rows']
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['queues'],[name])
        self.assertEqual(self.store.page(Scope(('8001',)))['rows'],[])

    def test_generation_archive_replacement_and_anchor_change_never_reuse_cursor(self):
        self.seed(self.call());self.worker.run_batch()
        checkpoint=self.store.worker_checkpoint(self.worker.name)
        different=Worker(self.archive,self.store,generation='archive_'+'b'*32)
        with self.assertRaises(Conflict):different.run_batch()
        other=Archive(self.root/'other.db',min_free_bytes=0);other.initialize()
        with self.assertRaises(Conflict):Worker(other,self.store,generation=self.generation).run_batch()
        with self.archive.writer() as db:db.execute('UPDATE events SET event_key=? WHERE id=?',('f'*64,checkpoint['cursor']))
        with self.assertRaisesRegex(Conflict,'anchor_changed'):self.worker.run_batch()
        self.assertEqual(self.store.worker_checkpoint(self.worker.name),checkpoint)

    def test_late_corrected_completion_keeps_original_provenance_and_withdraws_active_state(self):
        self.seed(self.call());self.worker.run_batch()
        row=self.store.page(self.admin)['rows'][0]
        self.store.add_action(row['id'],self.admin,'a'*32,'acknowledge')
        # Correct the old source record to a long completed segment. The visit
        # retains its entry identity; the old evidence is kept, not rewritten.
        corrected=self.call(talk=2)[-1]
        payload=dict(corrected.payload,values=['1','20'])
        self.seed([Event(corrected.source,corrected.key,corrected.timestamp,corrected.kind,payload)])
        self.assertEqual(self.worker.run_batch()['inserted'],0)
        updated=self.store.get(row['id'],self.admin)
        self.assertEqual(updated['status'],'needs_review');self.assertEqual(updated['evidence_count'],1)
        self.assertEqual(updated['evidence'][0]['event_id'],3)

    def test_known_scope_expansion_is_not_silently_written_to_old_incident(self):
        self.seed(self.call());self.worker.run_batch()
        old=self.store.page(self.admin)['rows'][0]
        self.seed(self.call(queue='8002',start=200,key='foreign'))
        self.worker.run_batch()
        # Reimport a new version of the original completion to re-evaluate it.
        event=self.call()[-1];payload=dict(event.payload,diagnostic_private_metadata='not copied')
        self.seed([Event(event.source,event.key,event.timestamp,event.kind,payload)])
        self.worker.run_batch()
        prior=self.store.get(old['id'],self.admin)
        self.assertEqual(prior['queues'],['8001']);self.assertEqual(prior['status'],'needs_review')

    def test_projection_version_change_requires_explicit_review_and_disabled_marker_writes_nothing(self):
        self.seed(self.call());self.worker.run_batch()
        with self.archive.writer() as db:db.execute('UPDATE report_projection_version SET version=version+1')
        with self.assertRaisesRegex(Conflict,'projection_changed'):self.worker.run_batch()
        marker=self.root/'disabled';marker.touch()
        disabled=Worker(self.archive,self.store,generation=self.generation,disabled_file=marker)
        with patch.object(Archive,'reader',side_effect=AssertionError('disabled worker read archive')):
            self.assertEqual(disabled.run_batch()['state'],'disabled')

    def test_source_is_read_only_missing_archive_not_created_and_explicit_generation_required(self):
        for generation in ('','archive_primary','archive_'+'a'*31):
            with self.subTest(generation=generation),self.assertRaises(ValueError):Worker(self.archive,self.store,generation=generation)
        with self.assertRaises(ValueError):Worker(self.archive,Store(self.archive.path),generation=self.generation)
        absent=Archive(self.root/'missing.db')
        with self.assertRaises(SourceUnavailable):Worker(absent,self.store,generation=self.generation).run_batch()
        self.assertFalse(absent.path.exists())
        self.seed(self.call());commands=[];real=sqlite3.connect
        def connect(*args,**kwargs):
            db=real(*args,**kwargs)
            if 'history.db' in str(args[0]):db.set_trace_callback(commands.append)
            return db
        with patch('sanequeue.reporting.store.sqlite3.connect',connect):self.worker.run_batch()
        self.assertTrue(commands)
        self.assertFalse(any(sql.lstrip().upper().startswith(('INSERT','UPDATE','DELETE','CREATE','ALTER','REPLACE')) for sql in commands))
        self.assertEqual(Worker(self.archive,self.store,generation=self.generation,threshold_seconds=5.0).name,self.worker.name)

    def test_cli_requires_explicit_once_and_disable_prevents_even_private_store_creation(self):
        self.seed(self.call())
        database=self.root/'cli-diagnostics.db'
        args=['--archive',str(self.archive.path),'--database',str(database),'--archive-generation',self.generation]
        with redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):main(args)
        self.assertFalse(database.exists())
        marker=self.root/'disabled';marker.touch();output=io.StringIO()
        with redirect_stdout(output):self.assertEqual(main(args+['--once','--disabled-file',str(marker)]),0)
        self.assertEqual(json.loads(output.getvalue())['state'],'disabled');self.assertFalse(database.exists())
        output=io.StringIO()
        with redirect_stdout(output):result=main(args+['--once'])
        self.assertEqual(result,0,output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['inserted'],1)
        self.assertTrue(database.exists())
