"""Evidence-only rankings; no invented scores or current-inventory aliases."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from sanequeue.reporting.agent_rankings import rank_agents
from sanequeue.reporting.facts import project_batch
from sanequeue.reporting.queries import Scope
from sanequeue.reporting.store import Archive,Event


class AgentRankingsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.archive=Archive(Path(self.temp.name)/'history.db',min_free_bytes=0);self.archive.initialize()
        project_batch(self.archive,inventory={});self.serial=0
        self.scope=Scope(('8001','8002'))

    def visit(self,agent='PJSIP/100',queue='8001',talk=10,entered=100,**changes):
        self.serial+=1;answered=entered+1
        value=dict(pbx='primary',id=format(self.serial,'064x'),callid='private-uid-'+str(self.serial),queue=queue,
                   entered=entered,answered=answered,ended=answered+(talk if talk is not None else 10),
                   caller='09999999999',agent=agent,outcome='answered',wait_seconds=1,talk_seconds=talk,
                   segment_ended_by='caller',coverage='observed')
        value.update(changes)
        with self.archive.writer() as db:
            db.execute('INSERT INTO report_visits VALUES('+','.join('?' for _ in value)+')',tuple(value.values()))
        return value

    def activity(self,queue='8001',alias='Local/100@from-queue/n',canonical='PJSIP/100',starts=90,ends=200,coverage='observed'):
        self.serial+=1
        with self.archive.writer() as db:
            db.execute('INSERT INTO report_activity VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                ('primary',str(self.serial),self.serial,queue,alias,'available','',starts,ends,1,coverage,canonical))

    def ranking(self,**kwargs):return rank_agents(self.archive,self.scope,90,300,min_samples=kwargs.pop('min_samples',1),**kwargs)

    def test_answered_count_aggregates_endpoint_across_queues_and_ties_are_equal(self):
        for queue in ('8001','8001','8002'):self.visit(queue=queue)
        for _ in range(2):self.visit('PJSIP/200')
        for _ in range(2):self.visit('PJSIP/300')
        result=self.ranking(min_samples=2)
        self.assertEqual(result['state'],'available')
        self.assertEqual([(row['agent'],row['value'],row['rank']) for row in result['rows']],
            [('PJSIP/100',3,1),('PJSIP/200',2,2),('PJSIP/300',2,2)])
        self.assertEqual(result['unit'],'queue_visit');self.assertFalse(result['conversation_unique'])
        self.assertIsNone(result['quality_score'])
        self.assertNotIn('09999999999',json.dumps(result));self.assertNotIn('private-uid',json.dumps(result))

    def test_average_uses_known_completed_denominator_and_shorter_is_not_quality(self):
        for talk in (10,20,None):self.visit(talk=talk)
        for talk in (15,15):self.visit('PJSIP/200',talk=talk)
        for talk in (20,20):self.visit('PJSIP/300',talk=talk)
        result=self.ranking(metric='avg_queue_talk_seconds',min_samples=2)
        self.assertEqual([(row['agent'],row['value'],row['rank']) for row in result['rows']],
            [('PJSIP/100',15,1),('PJSIP/200',15,1),('PJSIP/300',20,3)])
        first=result['rows'][0]
        self.assertEqual((first['answered_count'],first['talk_known_count'],first['talk_unknown_count']),(3,2,1))
        self.assertTrue(result['lower_talk_is_not_quality'])
        self.assertEqual(result['sample_unit'],'completed_segments_with_known_talk')

    def test_unknown_talk_stays_null_but_an_observed_zero_remains_zero(self):
        self.visit(talk=None)
        counted=self.ranking()['rows'][0]
        self.assertIsNone(counted['avg_queue_talk_seconds']);self.assertEqual(counted['talk_known_count'],0)
        self.assertEqual(self.ranking(metric='avg_queue_talk_seconds')['rows'],[])
        self.visit('PJSIP/200',talk=0)
        result=self.ranking(metric='avg_queue_talk_seconds')
        self.assertEqual([(row['agent'],row['value']) for row in result['rows']],[('PJSIP/200',0)])

    def test_canonical_historical_activity_merges_local_aliases_without_current_inventory(self):
        self.visit(agent='Local/100@from-queue/n')
        self.visit(agent='100',queue='8002')
        self.visit(agent='PJSIP/100')
        self.activity();self.activity(queue='8002',alias='100')
        result=self.ranking()
        self.assertEqual([(row['agent'],row['answered_count']) for row in result['rows']],[('PJSIP/100',3)])

    def test_unproven_or_conflicting_alias_prevents_publishing_a_false_winner(self):
        self.visit(agent='Local/100@from-queue/n');self.visit(agent='PJSIP/200')
        self.assertEqual(self.ranking()['state'],'unavailable')
        self.activity(canonical='PJSIP/100');self.activity(canonical='SIP/100')
        result=self.ranking()
        self.assertEqual(result['reason'],'agent_identity_unresolved');self.assertEqual(result['rows'],[])

    def test_alias_from_wrong_queue_old_time_or_incomplete_coverage_is_not_proof(self):
        self.visit(agent='Local/100@from-queue/n')
        self.activity(queue='8002');self.activity(starts=1,ends=90);self.activity(coverage='source_replaced')
        self.assertEqual(self.ranking()['state'],'unavailable')

    def test_scope_assignment_cutoff_and_entered_period_are_enforced(self):
        self.visit('PJSIP/100',entered=100);self.visit('PJSIP/100',entered=160)
        self.visit('PJSIP/200',entered=160);self.visit('PJSIP/100',queue='hidden',entered=160)
        result=rank_agents(self.archive,Scope(('8001',),('PJSIP/100',),True,150),90,300,min_samples=1)
        self.assertEqual([(row['agent'],row['answered_count']) for row in result['rows']],[('PJSIP/100',1)])
        self.assertEqual(result['effective_start'],150)
        self.assertEqual(result['known_endpoint_count'],1)

    def test_minimum_samples_default_and_deterministic_top_tie_boundary(self):
        for agent in ('PJSIP/300','PJSIP/200','PJSIP/100'):self.visit(agent)
        self.assertEqual(rank_agents(self.archive,self.scope,90,300)['rows'],[])
        first=self.ranking(top=2);second=self.ranking(top=2)
        self.assertEqual(first,second)
        self.assertEqual([row['agent'] for row in first['rows']],['PJSIP/100','PJSIP/200'])
        self.assertTrue(first['top_truncated']);self.assertTrue(first['tie_at_boundary'])
        self.assertEqual([row['rank'] for row in first['rows']],[1,1])

    def test_censored_or_invalid_completed_talk_never_improves_average(self):
        self.visit(talk=2,ended=None,coverage='missing_end')
        self.visit(talk=2,ended=400)
        self.visit(talk=2,ended=130)
        self.visit(talk=2,coverage='missing_entry')
        result=self.ranking(metric='avg_queue_talk_seconds')
        self.assertEqual(result['rows'],[])
        count=self.ranking()['rows'][0]
        self.assertEqual(count['answered_count'],3);self.assertIsNone(count['avg_queue_talk_seconds'])

    def test_caps_and_projection_lag_return_no_partial_ranking(self):
        for _ in range(3):self.visit()
        with patch('sanequeue.reporting.agent_rankings.MAX_VISITS',2):
            result=self.ranking();self.assertEqual(result['state'],'limited');self.assertEqual(result['rows'],[])
        self.archive.append([Event('test','new',100,'UNKNOWN',{})])
        result=self.ranking();self.assertEqual(result['state'],'unavailable');self.assertEqual(result['rows'],[])

    def test_interval_limit_deadline_and_old_projection_never_return_fake_best(self):
        self.visit(agent='Local/100@from-queue/n');self.activity();self.activity()
        with patch('sanequeue.reporting.agent_rankings.MAX_INTERVALS',1):
            self.assertEqual(self.ranking()['state'],'limited')
        ticks=iter([0,3])
        with patch('sanequeue.reporting.agent_rankings.time.monotonic',side_effect=lambda:next(ticks,3)):
            result=self.ranking();self.assertEqual(result['rows'],[]);self.assertEqual(result['state'],'limited')
        with self.archive.writer() as db:db.execute('UPDATE report_projection_version SET version=9')
        self.assertEqual(self.ranking()['reason'],'projection_unavailable')

    def test_validation_and_read_only_archive_contract(self):
        self.visit()
        for kwargs in (dict(metric='quality_score'),dict(metric=[]),dict(min_samples=True),dict(min_samples=0),dict(min_samples=101),dict(top=21)):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):rank_agents(self.archive,self.scope,90,300,**kwargs)
        commands=[];original=sqlite3.connect
        def connect(*args,**kwargs):
            db=original(*args,**kwargs);db.set_trace_callback(commands.append);return db
        with patch('sanequeue.reporting.store.sqlite3.connect',connect):self.ranking()
        self.assertTrue(any('query_only=ON' in query for query in commands))
        self.assertFalse(any(query.lstrip().upper().startswith(('CREATE','INSERT','UPDATE','ALTER','DELETE')) for query in commands))
