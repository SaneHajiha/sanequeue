import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sanequeue.reporting.agent_metrics import report, _overlap_sql
from sanequeue.reporting.facts import project_batch
from sanequeue.reporting.queries import Scope
from sanequeue.reporting.store import Archive, Event, QueryDeadline


class AgentMetricsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.archive=Archive(Path(self.temp.name)/'archive.db',min_free_bytes=0)
        self.archive.initialize();project_batch(self.archive,inventory={})
        self.scope=Scope(('8001','8002'))
        self.counter=0
        self.heartbeat(220)

    def heartbeat(self,observed):
        self.archive.append([],checkpoint_source='activity_cache',checkpoint=dict(observed=observed,private_path='/never/expose'))

    def activity(self,start,end,state='available',queue='8001',agent='PJSIP/100',canonical=None,on_duty=1,coverage='observed',reason=''):
        self.counter+=1
        with self.archive.writer() as db:
            db.execute('INSERT INTO report_activity VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (self.archive.pbx,'a'+str(self.counter),0,queue,agent,state,reason,start,end,on_duty,coverage,canonical or agent))

    def visit(self,entered=105,answered=110,ended=140,talk=30,queue='8001',agent='PJSIP/100',coverage='observed'):
        self.counter+=1
        with self.archive.writer() as db:
            db.execute('INSERT INTO report_visits VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (self.archive.pbx,'v'+str(self.counter),'private-uid',queue,entered,answered,ended,
                 '09123456789',agent,'answered',answered-entered if answered is not None else None,talk,'caller',coverage))

    def valid(self,*,raw='PJSIP/100',canonical='PJSIP/100'):
        for start,end,state in [(100,110,'available'),(110,140,'on_call'),(140,150,'wrap_up'),(150,200,'available')]:
            self.activity(start,end,state,agent=raw,canonical=canonical)
        self.visit(agent=raw)

    def row(self,scope=None,start=100,end=200,now=220):
        return report(self.archive,scope or self.scope,start,end,now=now)['agents'][0]

    def test_full_evidence_has_explicit_queue_segment_denominators(self):
        self.valid();result=report(self.archive,self.scope,100,200,now=220);row=result['agents'][0]
        self.assertEqual(row['answered_queue_segments'],1);self.assertEqual(row['completed_queue_segments'],1)
        self.assertEqual(row['known_talk_segment_count'],1);self.assertEqual(row['known_talk_segment_seconds'],30)
        self.assertEqual(row['acw_seconds'],10);self.assertEqual(row['on_duty_seconds'],100)
        self.assertEqual(row['aht_seconds'],40);self.assertEqual(row['occupancy_percent'],40)
        self.assertTrue(row['coverage']['complete']);self.assertEqual(result['totals']['aht_seconds'],40)
        self.assertEqual(result['unit'],'queue_segment');self.assertFalse(result['complete_conversation'])
        payload=json.dumps(result)
        for secret in ('09123456789','private-uid','/never/expose'):self.assertNotIn(secret,payload)

    def test_missing_acw_is_unknown_not_inferred_from_gap_or_pause_reason(self):
        self.activity(100,110);self.activity(110,140,'on_call')
        self.activity(140,150,'paused',on_duty=0,reason='after_call_work');self.activity(150,200)
        self.visit();row=self.row()
        self.assertIsNone(row['acw_seconds']);self.assertIsNone(row['aht_seconds']);self.assertIsNone(row['occupancy_percent'])
        self.assertIn('explicit_acw_unavailable',row['coverage']['reasons'])

    def test_multiqueue_shared_time_is_union_not_membership_sum(self):
        self.valid();self.activity(100,200,queue='8002')
        row=self.row();self.assertEqual(row['observed_seconds'],100);self.assertEqual(row['on_duty_seconds'],100)
        self.assertEqual(row['unique_queue_talk_seconds'],30);self.assertEqual(row['occupancy_percent'],40)
        self.assertEqual(row['completed_queue_segments'],1)

    def test_frozen_alias_unifies_local_membership_without_current_inventory(self):
        self.valid(raw='Local/100@from-queue/n',canonical='PJSIP/100')
        self.activity(100,200,queue='8002')
        row=self.row();self.assertEqual(row['agent'],'PJSIP/100');self.assertEqual(row['on_duty_seconds'],100)
        self.assertEqual(row['aht_seconds'],40)

    def test_overlapping_queue_segments_never_double_credit_aht(self):
        self.valid();self.activity(100,200,queue='8002');self.visit(queue='8002')
        row=self.row();self.assertEqual(row['known_talk_segment_seconds'],60)
        self.assertEqual(row['unique_queue_talk_seconds'],30);self.assertIsNone(row['aht_seconds'])
        self.assertIn('overlapping_queue_segments',row['coverage']['reasons'])

    def test_missing_talk_and_bad_source_clock_keep_ratios_unknown(self):
        self.valid()
        with self.archive.writer() as db:db.execute('UPDATE report_visits SET talk_seconds=NULL')
        row=self.row();self.assertEqual(row['unknown_talk_segment_count'],1);self.assertIsNone(row['aht_seconds'])
        with self.archive.writer() as db:db.execute('UPDATE report_visits SET talk_seconds=0')
        row=self.row();self.assertEqual(row['known_talk_segment_count'],1)
        self.assertIn('queue_talk_clock_mismatch',row['coverage']['reasons']);self.assertIsNone(row['aht_seconds'])

    def test_unobserved_tail_and_unknown_states_are_not_absence(self):
        self.valid();self.heartbeat(180)
        row=self.row();self.assertEqual(row['observed_seconds'],80);self.assertIsNone(row['occupancy_percent'])
        self.assertIn('activity_coverage_incomplete',row['coverage']['reasons'])
        self.heartbeat(220)
        with self.archive.writer() as db:db.execute("UPDATE report_activity SET state='unknown' WHERE starts=150")
        self.assertIn('unknown_activity_state',self.row()['coverage']['reasons'])

    def test_self_assignment_cutoff_and_queue_scope_do_not_leak_old_or_foreign_visits(self):
        self.valid();self.activity(100,200,queue='8002',agent='PJSIP/200');self.visit(queue='8002',agent='PJSIP/200')
        scope=Scope(('8001',),('PJSIP/100',),True,150)
        result=report(self.archive,scope,100,200,now=220)
        self.assertEqual([r['agent'] for r in result['agents']],['PJSIP/100'])
        self.assertEqual(result['agents'][0]['answered_queue_segments'],0)
        self.assertEqual(result['agents'][0]['on_duty_seconds'],50)
        self.assertEqual(report(self.archive,Scope(()),100,200,now=220)['agents'],[])
        self.assertEqual(report(self.archive,Scope(('8001',),(),True),100,200,now=220)['agents'],[])

    def test_partial_report_censors_source_talk_without_rescaling_it(self):
        self.valid();row=self.row(start=120)
        self.assertEqual(row['known_talk_segment_seconds'],30);self.assertEqual(row['unique_queue_talk_seconds'],20)
        self.assertIsNone(row['aht_seconds']);self.assertIn('censored_queue_segment',row['coverage']['reasons'])

    def test_open_interval_stops_at_heartbeat_and_projection_lag_disables_ratio(self):
        self.activity(100,None);self.heartbeat(180)
        row=self.row();self.assertEqual(row['on_duty_seconds'],80);self.assertIsNone(row['occupancy_percent'])
        self.archive.append([Event('cel','late',170,'HANGUP',{})])
        self.assertIn('projection_incomplete',self.row()['coverage']['reasons'])

    def test_answer_at_exclusive_end_is_not_answered_in_this_period(self):
        self.activity(100,200);self.visit(entered=190,answered=200,ended=230)
        self.assertEqual(self.row()['answered_queue_segments'],0)

    def test_acw_must_match_exact_completed_queue_boundary(self):
        self.valid()
        with self.archive.writer() as db:db.execute("UPDATE report_activity SET starts=141 WHERE state='wrap_up'")
        row=self.row();self.assertEqual(row['acw_seconds'],9);self.assertIsNone(row['aht_seconds'])
        self.assertIn('acw_queue_boundary_unverified',row['coverage']['reasons'])

    def test_limits_and_total_deadline_fail_instead_of_truncate(self):
        self.valid()
        with patch('sanequeue.reporting.agent_metrics.MAX_INTERVALS',2):
            with self.assertRaises(QueryDeadline):self.row()
        with patch('sanequeue.reporting.agent_metrics.MAX_VISITS',0):
            with self.assertRaises(QueryDeadline):self.row()
        with patch('sanequeue.reporting.agent_metrics.time.monotonic',side_effect=[0,10]):
            with self.assertRaises(QueryDeadline):self.row()
        with self.assertRaises(ValueError):self.row(now=float('nan'))

    def test_overlap_queries_seek_closed_end_and_partial_open_indexes(self):
        # Regression for the old start<end plus COALESCE(end) predicate, which
        # forced scans of the entire historical prefix even for today's report.
        with self.archive.reader() as db:
            for table,prefix in [('report_visits','rv'),('report_activity','ra')]:
                sql=_overlap_sql(table,'queue','pbx=? AND queue IN (?)')
                args=('primary','8001',100,200,0,'primary','8001',200,0,10001)
                plan=' '.join(row[3] for row in db.execute('EXPLAIN QUERY PLAN '+sql,args))
                self.assertIn(prefix+'_queue_ended',plan);self.assertIn(prefix+'_queue_open',plan)
                self.assertIn('SEARCH',plan);self.assertNotIn('SCAN '+table,plan)
                self.assertNotIn('USE TEMP B-TREE',plan)

    def test_closed_and_open_carry_in_are_both_selected_without_old_completed_visits(self):
        self.activity(50,120);self.activity(120,None,'on_call')
        self.visit(entered=50,answered=60,ended=120,talk=60)
        self.visit(entered=130,answered=140,ended=None,talk=None)
        self.visit(entered=1,answered=2,ended=3,talk=1)
        row=self.row();self.assertEqual(row['answered_queue_segments'],2)
        self.assertEqual(row['completed_queue_segments'],1)
        self.assertEqual(row['unique_queue_talk_seconds'],80)
        self.assertEqual(row['observed_seconds'],100)


if __name__=='__main__':unittest.main()
