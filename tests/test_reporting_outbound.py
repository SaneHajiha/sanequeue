from pathlib import Path
import tempfile
import unittest
from sanequeue.reporting.store import Archive,Event
from sanequeue.reporting.facts import project_batch
from sanequeue.reporting.identity import parties
from sanequeue.reporting.outbound import page
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
