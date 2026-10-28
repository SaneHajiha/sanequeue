"""Synthetic queue_log evidence only; no telephony/network integration."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from sanequeue.reporting.store import Archive,Event,QueryDeadline
from sanequeue.reporting.facts import project_batch
from sanequeue.reporting.queries import Scope
from sanequeue.reporting import ring_attempts as module


class RingAttemptTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.archive=Archive(Path(self.temp.name)/'history.sqlite3',min_free_bytes=0)
        self.archive.initialize();project_batch(self.archive);self.scope=Scope(('8001',));self.seq=0
    def tearDown(self):self.temp.cleanup()
    def event(self,kind,ts,*,queue='8001',callid='synthetic-private-call',agent='PJSIP/100-abcdef',values=None,key=None,archive=None):
        self.seq+=1;archive=archive or self.archive
        archive.append([Event('queue_log',key or str(self.seq),ts,kind,dict(queue=queue,callid=callid,agent=agent,values=values or []))])
    def project(self):
        while project_batch(self.archive)['processed']:pass
    def report(self,**kw):return module.report(self.archive,self.scope,100,200,now=300,**kw)
    def test_repeated_attempts_are_not_unique_missed_callers_and_ms_are_seconds(self):
        self.event('ENTERQUEUE',90,values=['','caller-private-number']);self.event('RINGNOANSWER',110,values=['1250']);self.event('RINGNOANSWER',120,values=['0']);self.event('CONNECT',130,values=['40','peer','1']);self.event('COMPLETECALLER',150,values=['40','20']);self.project()
        result=self.report();self.assertEqual(result['totals']['attempts'],2);self.assertEqual(result['totals']['known_ring_seconds'],1.25);self.assertEqual(result['totals']['average_known_ring_seconds'],.625)
        self.assertEqual(result['groups'][0]['agent'],'100');self.assertEqual(result['totals']['matched_visit_attempts'],2)
        self.assertTrue(all(row['visit_id'] for row in result['rows']));self.assertFalse(result['coverage']['complete'])
        serialized=json.dumps(result);self.assertNotIn('caller-private-number',serialized);self.assertNotIn('synthetic-private-call',serialized);self.assertNotIn('PJSIP/',serialized)
    def test_unknown_and_zero_duration_are_distinct_and_unnamed_endpoint_is_unknown(self):
        for i,value in enumerate(['0','bad','-1','nan','86400001']):self.event('RINGNOANSWER',110+i,values=[value],agent='Display Name')
        self.project();result=self.report();self.assertEqual(result['totals']['known_duration_attempts'],1);self.assertEqual(result['totals']['unknown_duration_attempts'],4);self.assertEqual(result['totals']['average_known_ring_seconds'],0)
        self.assertIsNone(result['groups'][0]['agent']);self.assertEqual(result['coverage']['unknown_agent_attempts'],5)
    def test_page_ties_full_aggregate_and_current_source_versions(self):
        self.event('RINGNOANSWER',120,values=['1000'],key='corrected');self.event('RINGNOANSWER',120,values=['2500'],key='corrected');self.event('RINGNOANSWER',120,values=['500']);self.project()
        result=self.report(limit=1);other=self.report(limit=1,before=result['next']);self.assertEqual(result['totals'],other['totals']);self.assertEqual(result['totals']['attempts'],2)
        self.assertNotEqual(result['rows'][0]['id'],other['rows'][0]['id']);self.assertIsNone(other['next']);self.assertEqual(result['totals']['known_ring_seconds'],3)
    def test_foreign_queue_and_pbx_and_non_ring_events_excluded(self):
        self.event('RINGNOANSWER',120,values=['1000']);self.event('RINGNOANSWER',120,queue='8002',values=['1000']);self.event('RINGCANCELED',120,values=['1000'])
        other=Archive(self.archive.path,pbx='foreign',min_free_bytes=0);self.event('RINGNOANSWER',120,values=['1000'],archive=other)
        self.project();self.assertEqual(self.report()['totals']['attempts'],1)
    def test_open_visit_can_correlate_but_ambiguous_reentry_never_guessed(self):
        self.event('ENTERQUEUE',90,callid='open');self.event('RINGNOANSWER',110,callid='open',values=['1000'])
        self.event('ENTERQUEUE',90,callid='reentry');self.event('ENTERQUEUE',100,callid='reentry');self.event('RINGNOANSWER',110,callid='reentry',values=['1000']);self.project()
        rows=self.report()['rows'];self.assertEqual({r['correlation'] for r in rows},{'explicit_queue_visit_interval','ambiguous_queue_visit'});self.assertEqual(sum(r['visit_id'] is not None for r in rows),1)
    def test_entry_after_attempt_missing_entry_or_answer_tie_not_proven(self):
        self.event('RINGNOANSWER',110,callid='late',values=['1000']);self.event('ENTERQUEUE',120,callid='late')
        self.event('CONNECT',100,callid='missing',values=['1','peer','1']);self.event('RINGNOANSWER',110,callid='missing',values=['1000'])
        self.event('ENTERQUEUE',100,callid='tie');self.event('CONNECT',110,callid='tie',values=['10','peer','1']);self.event('RINGNOANSWER',110,callid='tie',values=['1000']);self.project()
        rows=self.report()['rows'];self.assertTrue(all(r['visit_id'] is None for r in rows));self.assertEqual({r['correlation'] for r in rows},{'queue_visit_unproven','queue_entry_unproven','attempt_after_answer_or_timestamp_tie'})
    def test_cutoff_and_future_events_and_agent_self_fail_closed(self):
        self.event('ENTERQUEUE',90);self.event('RINGNOANSWER',110,values=['1000']);self.event('RINGNOANSWER',150,values=['1000']);self.project()
        scoped=Scope(('8001',),not_before=105);result=module.report(self.archive,scoped,100,200,now=120)
        self.assertEqual(result['totals']['attempts'],1);self.assertEqual(result['rows'][0]['correlation'],'visit_before_assignment_cutoff')
        with self.assertRaises(ValueError):module.report(self.archive,Scope(('8001',),('PJSIP/100',),True,0),100,200)
    def test_projection_lag_prevents_visit_link_but_preserves_archived_attempt(self):
        self.event('ENTERQUEUE',90);self.project();self.event('RINGNOANSWER',110,values=['1000']);result=self.report()
        self.assertEqual(result['totals']['attempts'],1);self.assertIsNone(result['rows'][0]['visit_id']);self.assertFalse(result['coverage']['projection_caught_up'])
    def test_existing_event_index_and_cap_counts_unrelated_rows(self):
        self.archive.append([Event('cel',str(i),110+i,'SYNTHETIC',{}) for i in range(4)])
        with self.archive.reader() as db:
            plan=' '.join(row[3] for row in db.execute('EXPLAIN QUERY PLAN '+module.EVENT_SQL,('primary',100,200,10)))
        self.assertIn('event_time (pbx=? AND ts>? AND ts<?)',plan);self.assertNotIn('SCAN e',plan)
        with patch.object(module,'MAX_EVENTS',3),self.assertRaisesRegex(QueryDeadline,'source_event_limit'):self.report()
    def test_payload_groups_and_global_correlation_caps_fail_explicit(self):
        self.event('RINGNOANSWER',110,values=['1','x'*5000])
        with self.assertRaisesRegex(QueryDeadline,'payload_limit'):self.report()
        with self.archive.writer() as db:db.execute('DELETE FROM source_items')
        self.event('RINGNOANSWER',120,agent='100');self.event('RINGNOANSWER',130,agent='200');self.project()
        with patch.object(module,'MAX_GROUPS',1),self.assertRaisesRegex(QueryDeadline,'group_limit'):self.report()
    def test_health_redacts_private_paths_and_reports_gap_not_complete(self):
        self.archive.append([],checkpoint_source='health:queue_log',checkpoint={'ok':True,'checked':290,'path':'PRIVATE','progress':{'caught_up':True,'password':'SECRET'}})
        self.archive.append([],checkpoint_source='queue_log',checkpoint={'path':'PRIVATE','coverage_gaps':[[105,115]],'source_time':120})
        result=self.report();self.assertTrue(result['coverage']['source_gap']);self.assertTrue(result['coverage']['queue_log']['fresh']);self.assertFalse(result['coverage']['complete']);self.assertNotIn('PRIVATE',json.dumps(result));self.assertNotIn('SECRET',json.dumps(result))
    def test_range_cursor_and_empty_scope(self):
        for before in ('bad!','WzEsIngiXQ','W10'):
            with self.assertRaises(ValueError):self.report(before=before)
        with self.assertRaises(ValueError):module.report(self.archive,self.scope,0,32*86400)
        self.assertEqual(module.report(self.archive,Scope(()),100,200,now=300)['totals']['attempts'],0)

if __name__=='__main__':unittest.main()
