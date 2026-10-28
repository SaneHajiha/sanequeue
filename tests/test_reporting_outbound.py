from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import tempfile
import unittest
import json
from unittest.mock import patch
from sanequeue.reporting.store import Archive,Event
from sanequeue.reporting.facts import project_batch
from sanequeue.reporting.identity import parties
from sanequeue.reporting.outbound import page,summary
from sanequeue.reporting.store import QueryDeadline
from sanequeue.reporting.queries import Scope


class OutboundTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.archive=Archive(Path(self.temp.name)/'history.db',min_free_bytes=0);self.archive.initialize()
        self.inventory=dict(observed_at=100,endpoints=[
            dict(technology='PJSIP',endpoint='100',category='extension'),
            dict(technology='SIP',endpoint='200',category='extension'),
            dict(technology='PJSIP',endpoint='provider-main',category='trunk')])

    def activity(self,key,queue='8001',agent='Local/100@from-queue/n',start=100,end=200,state='paused'):
        return Event('activity',key,start,'ACTIVITY_INTERVAL',dict(queue=queue,agent=agent,
            starts=start,ends=end,state=state,reason='survey',on_duty=False))

    def cdr(self,key,stamp=150,source='PJSIP/100-000000ab',destination='PJSIP/provider-main-000000ac'):
        return Event('cdr',key,stamp,'CDR',dict(uniqueid=key,linkedid=key,channel=source,dstchannel=destination,
            dst='09123456789',duration=40,billsec=30,disposition='ANSWERED'))

    def seed(self):
        self.archive.append([self.activity('pause-a'),self.activity('pause-b',queue='8002'),
            self.cdr('call-a'),self.cdr('call-b',160),self.cdr('before-pause',90),
            self.cdr('after-pause',210),self.cdr('internal',155,destination='SIP/200-000000ad'),
            self.cdr('inbound',155,source='PJSIP/provider-main-000000ae',destination='PJSIP/100-000000af')],
            checkpoint_source='activity_cache',checkpoint=dict(observed=250))
        while project_batch(self.archive,inventory=self.inventory)['processed']:pass

    def test_direction_requires_explicit_known_channel_pairs(self):
        self.assertEqual(parties('PJSIP/100-000000ab','PJSIP/provider-main-000000ac',self.inventory)['direction'],'outbound')
        self.assertEqual(parties('PJSIP/100-000000ab','PJSIP/provider-main-other-000000ac',self.inventory)['direction'],'unknown')
        self.assertEqual(parties('Local/100@from-queue-000000ab;1','PJSIP/provider-main-000000ac',self.inventory)['direction'],'unknown')
        self.assertEqual(parties('PJSIP/100-000000ab','SIP/200-000000ac',self.inventory)['direction'],'internal')
        self.assertEqual(parties('PJSIP/100-000000ab','PJSIP/provider-main-000000ac',None)['direction'],'unknown')

    def test_multi_queue_pause_does_not_duplicate_a_cdr_segment(self):
        self.seed()
        result=page(self.archive,Scope(('8001','8002')),80,300)
        self.assertEqual([row['id'] for row in result['rows']],['call-b','call-a'])
        self.assertEqual(len(result['rows'][0]['memberships']),2)
        self.assertEqual(result['rows'][0]['agent'],'PJSIP/100')
        self.assertEqual(result['rows'][0]['billsec'],30)
        self.assertNotIn('linkedid',result['rows'][0])
        limited=page(self.archive,Scope(('8001',)),80,300)
        self.assertEqual({m['queue'] for row in limited['rows'] for m in row['memberships']},{'8001'})
        internal=page(self.archive,Scope(('8001',)),80,300,direction='internal')
        self.assertEqual([row['id'] for row in internal['rows']],['internal'])
        with self.assertRaises(ValueError):page(self.archive,Scope(('8001',)),80,300,direction='inbound')

    def test_scope_assignment_cutoff_and_keyset(self):
        self.seed()
        scope=Scope(('8001',),('Local/100@from-queue/n',),True,155)
        self.assertEqual([r['id'] for r in page(self.archive,scope,80,300)['rows']],['call-b'])
        self.assertEqual(page(self.archive,Scope(('8001',),('SIP/200',),True),80,300)['rows'],[])
        self.assertEqual(page(self.archive,Scope(()),80,300)['rows'],[])
        first=page(self.archive,Scope(('8001',)),80,300,limit=1)
        second=page(self.archive,Scope(('8001',)),80,300,limit=1,before=first['next'])
        self.assertEqual([first['rows'][0]['id'],second['rows'][0]['id']],['call-b','call-a'])
        with self.assertRaises(ValueError):page(self.archive,Scope(('8001',)),80,300,before=('NaN','a'))

    def test_reader_uses_consistent_snapshot_without_blocking_writer(self):
        self.archive.append([self.cdr('first')])
        with self.archive.reader() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0],1)
            self.archive.append([self.cdr('second')])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM events').fetchone()[0],1)
        self.assertEqual(len(self.archive.page()),2)

    def test_rebuild_preserves_identity_evidence_when_inventory_changes(self):
        self.seed()
        with self.archive.reader() as db:
            before=[tuple(row) for row in db.execute('SELECT * FROM report_cdr_parties ORDER BY source_key')]
            activity=[tuple(row) for row in db.execute('SELECT source_key,canonical_agent FROM report_activity ORDER BY source_key')]
        with self.archive.writer() as db:
            db.execute('DELETE FROM report_projection_version')
        # The same endpoint number is now a trunk; historical facts must not
        # become inbound or disappear from the agent report on replay.
        changed=dict(observed_at=999,endpoints=[dict(technology='PJSIP',endpoint='100',category='trunk')])
        while project_batch(self.archive,inventory=changed)['processed']:pass
        with self.archive.reader() as db:
            self.assertEqual([tuple(row) for row in db.execute('SELECT * FROM report_cdr_parties ORDER BY source_key')],before)
            self.assertEqual([tuple(row) for row in db.execute('SELECT source_key,canonical_agent FROM report_activity ORDER BY source_key')],activity)
            self.assertEqual(db.execute("SELECT DISTINCT provenance FROM report_identity_evidence").fetchone()[0],'first_projection_inventory')
        event=self.cdr('call-a')
        self.archive.append([Event(event.source,event.key,event.timestamp,event.kind,{**event.payload,'billsec':35,'recordingfile':'late.wav'})])
        while project_batch(self.archive,inventory=changed)['processed']:pass
        with self.archive.reader() as db:
            row=db.execute("SELECT agent,direction,inventory_observed FROM report_cdr_parties WHERE source_key='call-a'").fetchone()
            self.assertEqual(tuple(row),('PJSIP/100','outbound',100))
            self.assertEqual(db.execute("SELECT billsec,recording FROM report_cdr WHERE source_key='call-a'").fetchone()[0],35)

    def test_summary_counts_all_segments_once_and_unions_multi_queue_pauses(self):
        self.seed()
        result=summary(self.archive,Scope(('8001','8002')),80,300)
        self.assertEqual(result['totals']['segments_started'],2)
        self.assertEqual(result['totals']['answered_segments'],2)
        self.assertEqual(result['totals']['known_billsec_sum'],60)
        self.assertEqual(result['totals']['average_answered_billsec'],30)
        self.assertEqual(result['totals']['unique_pause_seconds'],100)
        self.assertEqual(result['agents'][0]['unique_pause_seconds'],100)
        self.assertEqual(sum(row['segments_started'] for row in result['queue_reasons']),4)
        self.assertTrue(result['queue_reasons_nonadditive'])
        self.assertEqual(result['end'],250)
        self.assertEqual(summary(self.archive,Scope(('8001',)),80,300,direction='internal')['totals']['segments_started'],1)
        with self.assertRaises(ValueError):summary(self.archive,Scope(('8001',)),80,300,direction='inbound')
        encoded=json.dumps(result)
        for private in ('09123456789','call-a','call-b','linkedid"','uniqueid"','source_key"','destination"'):
            self.assertNotIn(private,encoded)

    def test_answered_zero_unknown_billsec_and_shared_linkedid_are_distinct_metrics(self):
        events=[self.activity('pause')]
        specifications=[('a','ANSWERED',0),('b','ANSWERED',None),('c','NO ANSWER',0),
                        ('d','BUSY',0),('e','FAILED',None),('f','CONGESTION',0),('g','UNRECOGNIZED',None)]
        for index,(key,status,billsec) in enumerate(specifications):
            event=self.cdr(key,110+index)
            events.append(Event(event.source,event.key,event.timestamp,event.kind,
                                {**event.payload,'linkedid':'same-conversation-evidence','disposition':status,'billsec':billsec}))
        self.archive.append(events,checkpoint_source='activity_cache',checkpoint=dict(observed=250))
        while project_batch(self.archive,inventory=self.inventory)['processed']:pass
        totals=summary(self.archive,Scope(('8001',)),80,300)['totals']
        self.assertEqual(totals['segments_started'],7)
        self.assertEqual(totals['answered_segments'],2)
        self.assertEqual(totals['unanswered_segments'],4)
        self.assertEqual(totals['unknown_disposition_segments'],1)
        self.assertEqual((totals['busy_segments'],totals['no_answer_segments'],totals['failed_segments'],totals['other_unanswered_segments']),(1,1,1,1))
        self.assertEqual(totals['average_answered_billsec'],0)
        self.assertEqual(totals['answered_known_billsec_count'],1)
        self.assertEqual(totals['known_billsec_count'],4)
        self.assertEqual(totals['unknown_billsec_count'],3)
        self.assertEqual(totals['linkedid_groups'],1)

    def test_summary_clips_assignment_range_and_open_pause_to_observation(self):
        self.archive.append([self.activity('open',start=100,end=None),self.cdr('early',120),
                             self.cdr('valid',160),self.cdr('not-observed',190)],
                            checkpoint_source='activity_cache',checkpoint=dict(observed=180))
        while project_batch(self.archive,inventory=self.inventory)['processed']:pass
        result=summary(self.archive,Scope(('8001',),('Local/100@from-queue/n',),True,150),90,300)
        self.assertEqual((result['start'],result['end']),(150,180))
        self.assertEqual(result['totals']['segments_started'],1)
        self.assertEqual(result['totals']['unique_pause_seconds'],30)
        # Full billsec is retained, not clipped to the twenty remaining seconds.
        self.assertEqual(result['totals']['known_billsec_sum'],30)
        self.assertEqual(summary(self.archive,Scope(()),90,300)['totals']['segments_started'],0)
        self.assertEqual(summary(self.archive,Scope(('8001',),('SIP/200',),True),90,300)['agents'],[])

    def test_no_call_pause_and_overlapping_reason_intervals_are_not_lost(self):
        first=self.activity('first',start=100,end=160)
        second=self.activity('second',start=150,end=200)
        third=self.activity('different',queue='8002',start=140,end=180)
        self.archive.append([first,second,Event(third.source,third.key,third.timestamp,third.kind,{**third.payload,'reason':'training'})],
                            checkpoint_source='activity_cache',checkpoint=dict(observed=250))
        while project_batch(self.archive,inventory=self.inventory)['processed']:pass
        result=summary(self.archive,Scope(('8001','8002')),80,300)
        self.assertEqual(result['totals']['segments_started'],0)
        self.assertIsNone(result['totals']['average_answered_billsec'])
        self.assertEqual(result['totals']['unique_pause_seconds'],100)
        self.assertEqual({row['reason']:row['unique_pause_seconds'] for row in result['queue_reasons']},{'survey':100,'training':40})

    def test_summary_aggregates_beyond_first_page_and_respects_limits_and_deadline(self):
        events=[self.activity('pause'),self.activity('second-queue',queue='8002')]+[self.cdr('cdr-'+str(i),150+i/1000) for i in range(205)]
        self.archive.append(events,checkpoint_source='activity_cache',checkpoint=dict(observed=250))
        while project_batch(self.archive,inventory=self.inventory)['processed']:pass
        self.assertEqual(len(page(self.archive,Scope(('8001',)),80,300)['rows']),100)
        self.assertEqual(summary(self.archive,Scope(('8001',)),80,300)['totals']['segments_started'],205)
        with patch('sanequeue.reporting.outbound.MAX_SUMMARY_GROUPS',1):
            with self.assertRaises(QueryDeadline):summary(self.archive,Scope(('8001','8002')),80,300)
        with patch('sanequeue.reporting.outbound.MAX_PAUSE_INTERVALS',1):
            with self.assertRaises(QueryDeadline):summary(self.archive,Scope(('8001','8002')),80,300)
        # Exhaust the real SQLite VM progress budget during aggregate work.
        with patch('sanequeue.reporting.store.time.monotonic',side_effect=[0]+[10]*100):
            with self.assertRaises(QueryDeadline):summary(self.archive,Scope(('8001',)),80,300)

    def test_start_day_attribution_and_report_boundary_are_explicit(self):
        midnight=datetime(2026,10,25,tzinfo=ZoneInfo('Asia/Tehran')).timestamp()
        self.archive.append([self.activity('cross-midnight',start=midnight-20,end=midnight+20),
                             self.cdr('previous-day',midnight-1),self.cdr('next-day',midnight+1),self.cdr('end-boundary',midnight+10)],
                            checkpoint_source='activity_cache',checkpoint=dict(observed=midnight+30))
        while project_batch(self.archive,inventory=self.inventory)['processed']:pass
        result=summary(self.archive,Scope(('8001',)),midnight,midnight+10)
        self.assertEqual(result['totals']['segments_started'],1)
        self.assertEqual(result['totals']['known_billsec_sum'],30)
        self.assertEqual(result['totals']['unique_pause_seconds'],10)

    def test_unique_pause_total_is_agent_seconds_and_respects_self_scope(self):
        self.archive.append([self.activity('agent-100'),self.activity('agent-200',agent='SIP/200',start=120,end=160)],
                            checkpoint_source='activity_cache',checkpoint=dict(observed=250))
        while project_batch(self.archive,inventory=self.inventory)['processed']:pass
        result=summary(self.archive,Scope(('8001',)),80,300)
        self.assertEqual(result['totals']['unique_pause_seconds'],140)
        self.assertEqual(len(result['agents']),2)
        own=summary(self.archive,Scope(('8001',),('Local/100@from-queue/n',),True,150),80,300)
        self.assertEqual(own['totals']['unique_pause_seconds'],50)
        self.assertEqual([row['agent'] for row in own['agents']],['PJSIP/100'])

    def test_missing_activity_returns_explicit_unavailable_not_completed_history(self):
        project_batch(self.archive,inventory=self.inventory)
        result=summary(self.archive,Scope(('8001',)),80,300)
        self.assertEqual(result['coverage'],'activity_unavailable')
        self.assertIsNone(result['observed_until'])
        self.assertFalse(result['complete_history'])
        self.assertEqual(result['agents'],[])
        self.assertEqual(result['totals']['segments_started'],0)
