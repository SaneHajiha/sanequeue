from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sanequeue.reporting.adherence import report
from sanequeue.reporting.store import Archive,Event,QueryDeadline
from sanequeue.reporting.facts import project_batch
from sanequeue.reporting.queries import Scope


class AdherenceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.archive=Archive(Path(self.temp.name)/'history.db',min_free_bytes=0);self.archive.initialize()
        self.scope=Scope(('8001','8002'))

    def shift(self,ident=1,queue='8001',agent='PJSIP/100',start=100,end=200):
        return dict(id=ident,queue=queue,agent=agent,starts=start,ends=end,note='not exposed')

    def activity(self,key,start=100,end=200,queue='8001',agent='PJSIP/100',state='available',reason='',on_duty=True,coverage='observed'):
        return Event('activity',key,start,'ACTIVITY_INTERVAL',dict(queue=queue,agent=agent,canonical_agent=agent,
            state=state,reason=reason,starts=start,ends=end,on_duty=on_duty,coverage=coverage))

    def seed(self,events,observed=250,gaps=0):
        self.archive.append(events,checkpoint_source='activity_cache',checkpoint=dict(observed=observed,gaps=gaps))
        while project_batch(self.archive,inventory={})['processed']:pass

    def test_multiqueue_overlap_unions_agent_totals_without_crediting_wrong_queue(self):
        self.seed([self.activity('ready'),
                   self.activity('pause',queue='8002',end=150,state='paused',reason='survey',on_duty=False),
                   self.activity('ready-two',queue='8002',start=150)])
        result=report(self.archive,self.scope,90,300,[self.shift(),self.shift(2,queue='8002')],now=250)
        first,second=result['shifts'];agent=result['agents'][0]
        self.assertEqual(first['on_duty_seconds'],100)
        self.assertEqual(second['on_duty_seconds'],50)
        self.assertEqual(second['tardiness_seconds'],50)
        self.assertEqual(agent['scheduled_seconds'],100)
        self.assertEqual(agent['observed_seconds'],100)
        self.assertEqual(agent['on_duty_seconds'],100)
        self.assertEqual(agent['adherence_percent'],100)
        self.assertEqual(agent['paused_seconds'],50)
        self.assertEqual(agent['exclusive_paused_seconds'],0)
        self.assertEqual(agent['pause_reasons'][0]['seconds'],50)
        self.assertTrue(result['per_shift_nonadditive'])
        wrong_queue=report(self.archive,self.scope,90,300,[self.shift(queue='8002')],now=250)
        self.assertEqual(wrong_queue['shifts'][0]['adherence_percent'],50)

    def test_later_gap_keeps_tardiness_known_but_full_adherence_unknown(self):
        self.seed([self.activity('offline',end=110,state='offline',on_duty=False),
                   self.activity('first-login',start=110,end=130),self.activity('after-gap',start=150)],gaps=1)
        result=report(self.archive,self.scope,90,300,[self.shift()],now=250)
        row=result['shifts'][0]
        self.assertEqual(row['scheduled_seconds'],100)
        self.assertEqual(row['observed_seconds'],80)
        self.assertEqual(row['uncovered_seconds'],20)
        self.assertEqual(row['on_duty_seconds'],70)
        self.assertIsNone(row['adherence_percent'])
        self.assertEqual(row['on_duty_observed_percent'],87.5)
        self.assertEqual(row['tardiness_seconds'],10)
        self.assertEqual(row['first_login_at'],110)

    def test_missing_prefix_never_invents_login_or_tardiness(self):
        self.seed([self.activity('seen-ready',start=110)])
        row=report(self.archive,self.scope,90,300,[self.shift()],now=250)['shifts'][0]
        self.assertIsNone(row['first_login_at']);self.assertIsNone(row['tardiness_seconds'])
        self.assertEqual(row['first_on_duty_observed_at'],110)
        self.assertEqual(row['uncovered_seconds'],10)
        self.assertIsNone(row['adherence_percent'])

    def test_observed_offline_is_known_zero_but_uncovered_time_is_not_absence(self):
        self.seed([self.activity('known-offline',state='offline',on_duty=False)])
        row=report(self.archive,self.scope,90,300,[self.shift()],now=250)['shifts'][0]
        self.assertEqual(row['coverage_percent'],100)
        self.assertEqual(row['adherence_percent'],0)
        self.assertEqual(row['observed_not_on_duty_seconds'],100)
        self.assertIsNone(row['tardiness_seconds'])

    def test_cross_midnight_partial_report_and_self_cutoff_clip_before_calculation(self):
        midnight=datetime(2026,10,25,tzinfo=ZoneInfo('Asia/Tehran')).timestamp()
        self.seed([self.activity('overnight',start=midnight-600,end=midnight+600)],observed=midnight+700)
        shift=self.shift(start=midnight-600,end=midnight+600)
        result=report(self.archive,self.scope,midnight,midnight+900,[shift],now=midnight+700)
        row=result['shifts'][0]
        self.assertEqual(row['scheduled_seconds'],600);self.assertEqual(row['on_duty_seconds'],600)
        self.assertIsNone(row['tardiness_seconds']);self.assertEqual(row['tardiness_status'],'partial_report_start')
        scope=Scope(('8001','8002'),('PJSIP/100',),True,midnight+300)
        row=report(self.archive,scope,midnight,midnight+900,[shift],now=midnight+700)['shifts'][0]
        self.assertEqual(row['scheduled_seconds'],300);self.assertEqual(row['on_duty_seconds'],300)

    def test_unknown_identity_is_unknown_not_zero_and_self_scope_does_not_leak_it(self):
        self.seed([self.activity('ready')])
        shifts=[self.shift(agent='employee-name'),self.shift(2,agent='100')]
        result=report(self.archive,self.scope,90,300,shifts,now=250)
        self.assertEqual(result['unknown_identity_shifts'],2)
        self.assertEqual(result['agents'],[])
        for row in result['shifts']:
            self.assertIsNone(row['adherence_percent']);self.assertIsNone(row['on_duty_seconds'])
            self.assertIsNone(row['observed_seconds']);self.assertEqual(row['uncovered_seconds'],100)
        own=Scope(('8001','8002'),('PJSIP/100',),True)
        self.assertEqual(report(self.archive,own,90,300,shifts,now=250)['shifts'],[])

    def test_as_of_proof_must_cover_window_and_unifies_explicit_aliases(self):
        self.seed([self.activity('ready')])
        proof=dict(agent='employee-id',aliases=['PJSIP/100'],valid_from=100,valid_until=200)
        resolver=lambda agent,start,end:proof
        result=report(self.archive,self.scope,90,300,[self.shift(agent='employee-name')],agent_aliases=resolver,now=250)
        self.assertEqual(result['agents'][0]['agent'],'employee-id')
        self.assertEqual(result['agents'][0]['adherence_percent'],100)
        partial={**proof,'valid_until':150}
        row=report(self.archive,self.scope,90,300,[self.shift(agent='employee-name')],agent_aliases={'employee-name':partial},now=250)['shifts'][0]
        self.assertEqual(row['identity_status'],'unknown');self.assertIsNone(row['adherence_percent'])
        scoped=Scope(('8001',),('PJSIP/100',),True,150)
        later={**proof,'valid_from':150}
        row=report(self.archive,scoped,90,300,[self.shift(agent='employee-name')],agent_aliases={'employee-name':later},now=250)['shifts'][0]
        self.assertEqual(row['scheduled_seconds'],50);self.assertEqual(row['adherence_percent'],100)
        self.assertIsNone(row['tardiness_seconds'])

    def test_open_heartbeat_does_not_hide_unobserved_schedule_tail(self):
        self.seed([self.activity('open',end=None)],observed=150)
        row=report(self.archive,self.scope,90,300,[self.shift()],now=200)['shifts'][0]
        self.assertEqual(row['scheduled_seconds'],100);self.assertEqual(row['observed_seconds'],50)
        self.assertEqual(row['uncovered_seconds'],50);self.assertEqual(row['coverage_percent'],50)
        self.assertIsNone(row['adherence_percent'])
        future=report(self.archive,self.scope,90,400,[self.shift(start=300,end=400)],now=200)['shifts'][0]
        self.assertEqual(future['scheduled_seconds'],0);self.assertEqual(future['planned_seconds'],100)
        self.assertIsNone(future['adherence_percent'])

    def test_truncated_source_prefix_counts_but_gap_and_untrusted_coverage_do_not(self):
        self.seed([self.activity('old',end=130,coverage='source_replaced'),
                   self.activity('new',start=160),
                   self.activity('untrusted',start=130,end=160,coverage='unknown')],gaps=1)
        row=report(self.archive,self.scope,90,300,[self.shift()],now=250)['shifts'][0]
        self.assertEqual(row['observed_seconds'],70);self.assertEqual(row['uncovered_seconds'],30)
        self.assertIsNone(row['adherence_percent'])

    def test_queue_scope_caps_and_deadline_fail_explicitly_without_writes(self):
        self.seed([self.activity('first',end=150),self.activity('second',start=150)])
        before=self.archive.status()['counters']['events']
        self.assertEqual(report(self.archive,Scope(()),90,300,[self.shift()],now=250)['shifts'],[])
        with patch('sanequeue.reporting.adherence.MAX_INTERVALS',1):
            with self.assertRaises(QueryDeadline):report(self.archive,self.scope,90,300,[self.shift()],now=250)
        with patch('sanequeue.reporting.adherence.MAX_GROUPS',1):
            with self.assertRaises(QueryDeadline):report(self.archive,self.scope,90,300,[self.shift()],now=250)
        with self.assertRaises(ValueError):report(self.archive,self.scope,90,300,[self.shift()]*2001,now=250)
        with patch('sanequeue.reporting.adherence.time.monotonic',side_effect=[0]+[10]*100):
            with self.assertRaises(QueryDeadline):report(self.archive,self.scope,90,300,[self.shift()],now=250)
        self.assertEqual(self.archive.status()['counters']['events'],before)

    def test_self_scope_uses_archived_canonical_identity_without_guessing_other_members(self):
        source=self.activity('local',agent='Local/100@queue-special/n')
        self.seed([Event(source.source,source.key,source.timestamp,source.kind,{**source.payload,'canonical_agent':'PJSIP/100'}),
                   self.activity('other',agent='PJSIP/200',state='offline',on_duty=False)])
        scope=Scope(('8001',),('PJSIP/100',),True)
        row=report(self.archive,scope,90,300,[self.shift()],now=250)['shifts'][0]
        self.assertEqual(row['on_duty_seconds'],100)
        self.assertEqual(row['adherence_percent'],100)
