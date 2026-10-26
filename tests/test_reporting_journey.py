import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sanequeue.reporting.store import Archive,Event,QueryDeadline
from sanequeue.reporting.facts import project_batch
from sanequeue.reporting.queries import Scope,visits
from sanequeue.reporting.journey import explain


class JourneyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.archive=Archive(Path(self.temp.name)/'history.db',min_free_bytes=0);self.archive.initialize()
        self.serial=0;self.scope=Scope(('8001',))

    def event(self,source,uid,kind,stamp,**payload):
        self.serial+=1
        return Event(source,str(self.serial),stamp,kind,dict(uniqueid=uid,**payload))

    def visit(self,uid,queue='8001',stamp=100,caller='09123456789',peer=''):
        return [self.event('queue_log',uid,'ENTERQUEUE',stamp,callid=uid,queue=queue,agent='PJSIP/100',values=['',caller]),
                self.event('queue_log',uid,'CONNECT',stamp+1,callid=uid,queue=queue,agent='PJSIP/100',values=['1',peer,'0']),
                self.event('queue_log',uid,'COMPLETECALLER',stamp+20,callid=uid,queue=queue,agent='PJSIP/100',values=['1','19'])]

    def cel(self,uid,kind,stamp=105,**values):
        return self.event('cel',uid,kind,stamp,channame='PJSIP/private-endpoint-000001ab',**values)

    def seed(self,*events):
        self.archive.append(events)
        while project_batch(self.archive)['processed']:pass

    def ident(self,uid='private-root-uid',scope=None):
        return next(row['id'] for row in visits(self.archive,scope or self.scope,90,300)['rows'] if row['callid']==uid)

    def report(self,**kwargs):
        return explain(self.archive,kwargs.get('scope',self.scope),90,300,kwargs.get('ident') or self.ident())

    def test_scoped_entry_and_no_private_payload_or_numbers_outside_dictionary(self):
        self.seed(*self.visit('private-root-uid'),self.cel('private-root-uid','ANSWER',secret='/private/config'),
            self.event('cdr','private-root-uid','CDR',100,src='09123456789',dst='100',
                       channel='PJSIP/private-endpoint-000001ab',recordingfile='/private/audio.wav',duration=20))
        result=self.report()
        text=json.dumps({key:value for key,value in result.items() if key!='numbers'})
        for value in ('09123456789','private-root-uid','/private/','PJSIP/private-endpoint','recordingfile'):
            self.assertNotIn(value,text)
        self.assertIn('09123456789',result['numbers'].values())
        self.assertFalse(result['audio_granted']);self.assertIsNone(result['final_hangup'])
        self.assertFalse(result['coverage']['complete_conversation'])
        self.assertIsNone(explain(self.archive,Scope(('8002',)),90,300,self.ident()))

    def test_linkedid_does_not_merge_other_legs_or_leak_number(self):
        self.seed(*self.visit('private-root-uid'),self.cel('private-root-uid','ANSWER'),
            self.cel('private-hidden-uid','ANSWER',linkedid='private-root-uid'),
            self.event('cdr','private-hidden-uid','CDR',100,linkedid='private-root-uid',src='09999999999'))
        result=self.report()
        self.assertEqual(len([n for n in result['nodes'] if n['type']=='call_leg']),1)
        self.assertNotIn('09999999999',result['numbers'].values())

    def test_explicit_local_edge_expands_only_owned_peer(self):
        self.seed(*self.visit('private-root-uid'),*self.visit('private-peer-uid',stamp=102),
            self.cel('private-root-uid','CHAN_START',channame_override='ignored'),
            self.event('cel','private-peer-uid','CHAN_START',103,channame='Local/private-peer;2'),
            self.cel('private-root-uid','LOCAL_OPTIMIZE',104,eventextra=json.dumps(dict(local_two='Local/private-peer;2'))))
        result=self.report()
        self.assertEqual(len([n for n in result['nodes'] if n['type']=='call_leg']),2)
        self.assertTrue(any(e['relation']=='local_optimize' for e in result['edges']))

    def test_foreign_queue_or_unowned_uid_blocks_expansion(self):
        self.seed(*self.visit('private-root-uid'),*self.visit('private-peer-uid','8002',102),
            self.cel('private-root-uid','CHAN_START'),
            self.event('cel','private-peer-uid','CHAN_START',103,channame='Local/private-peer;2'),
            self.cel('private-root-uid','ATTENDEDTRANSFER',104,eventextra=json.dumps(dict(channel2_name='Local/private-peer;2'))))
        result=self.report()
        self.assertEqual(len([n for n in result['nodes'] if n['type']=='call_leg']),1)
        self.assertTrue(result['coverage']['restricted_or_unproven'])
        self.assertNotIn('8002',json.dumps(result))
        self.assertIsNone(result['final_hangup'])

    def test_same_uid_in_foreign_queue_suppresses_all_cel(self):
        self.seed(*self.visit('private-root-uid'),*self.visit('private-root-uid','8002',130),
                  self.cel('private-root-uid','ANSWER'))
        result=self.report()
        self.assertFalse(any(e['source']=='cel' for e in result['events']))
        self.assertTrue(result['coverage']['restricted_or_unproven'])

    def test_ivr_digits_and_origins_require_explicit_allowlisted_evidence(self):
        self.seed(*self.visit('private-root-uid'),self.cel('private-root-uid','CHAN_START'),
            self.cel('private-root-uid','APP_START',104,appname='Dial',context='ext-group'),
            self.cel('private-root-uid','APP_START',105,appname='Dial',context='private/context'),
            self.cel('private-root-uid','USER_DEFINED',106,userdeftype='IVRSelection',eventextra='{"digit":"2"}'),
            self.cel('private-root-uid','USER_DEFINED',107,userdeftype='Other',eventextra='{"digit":"9"}'),
            self.cel('private-root-uid','APP_START',108,appname='FollowMe',context='ext-findme'))
        result=self.report();events=result['events']
        self.assertEqual([e['digit'] for e in events if 'digit' in e],['2'])
        self.assertEqual({e['origin'] for e in events if 'origin' in e},{'ivr','ring_group','follow_me'})
        self.assertNotIn('private/context',json.dumps(result))

    def test_bridge_is_graph_not_conference_flattening_and_limits_deadline(self):
        self.seed(*self.visit('private-root-uid'),self.cel('private-root-uid','CHAN_START'),
            self.cel('private-root-uid','BRIDGE_ENTER',104,eventextra='{"bridge_id":"private-bridge"}'))
        result=self.report()
        self.assertTrue(any(n['type']=='bridge' for n in result['nodes']))
        self.assertNotIn('private-bridge',json.dumps(result))
        with patch('sanequeue.reporting.journey.MAX_EVENTS',1):
            self.assertTrue(self.report()['coverage']['limit_reached'])
        ident=self.ident();ticks=iter([0,6])
        with patch('sanequeue.reporting.journey.time.monotonic',side_effect=lambda:next(ticks,6)),self.assertRaises(QueryDeadline):
            self.report(ident=ident)

    def test_unprojected_foreign_evidence_never_bypasses_ownership(self):
        self.seed(*self.visit('private-root-uid'),self.cel('private-root-uid','ANSWER'))
        self.archive.append(self.visit('private-root-uid','8002',130))
        result=self.report()
        self.assertFalse(any(e['source']=='cel' for e in result['events']))
        self.assertTrue(result['coverage']['restricted_or_unproven'])

    def test_final_hangup_requires_two_consistent_direct_peer_causes(self):
        self.seed(*self.visit('private-root-uid'),*self.visit('private-peer-uid',stamp=102),
            self.cel('private-root-uid','CHAN_START'),self.cel('private-peer-uid','CHAN_START'),
            self.cel('private-root-uid','HANGUP',125,eventextra='{"hangupsource_uniqueid":"private-peer-uid"}'),
            self.cel('private-peer-uid','HANGUP',125,eventextra='{"hangupsource_uniqueid":"private-peer-uid"}'))
        with self.archive.writer() as db:
            event_id=db.execute("SELECT id FROM events WHERE source='cel' AND json_extract(payload,'$.uniqueid')='private-root-uid' ORDER BY id LIMIT 1").fetchone()[0]
            db.execute('INSERT INTO evidence_edges VALUES(?,?,?,?,?,?,?,?,?)',
                ('primary',event_id,'direct_peer','uniqueid','private-root-uid','uniqueid','private-peer-uid',110,'{}'))
        self.assertIsNotNone(self.report()['final_hangup'])
        with self.archive.writer() as db:
            db.execute("DELETE FROM evidence_edges WHERE relation='direct_peer'")
        self.assertIsNone(self.report()['final_hangup'])

    def test_explicit_connect_opens_actual_agent_leg_without_peer_queue_visit(self):
        self.seed(*self.visit('private-root-uid',peer='actual-agent-uid'),
                  self.cel('private-root-uid','CHAN_START',100),
                  self.cel('actual-agent-uid','CHAN_START',100),
                  self.cel('actual-agent-uid','ANSWER',101),
                  self.cel('actual-agent-uid','HANGUP',120,eventextra='{"hangupsource_uniqueid":"private-root-uid"}'),
                  self.cel('private-root-uid','HANGUP',120,eventextra='{"hangupsource_uniqueid":"private-root-uid"}'))
        result=self.report()
        self.assertEqual(len([n for n in result['nodes'] if n['type']=='call_leg']),2)
        self.assertTrue(any(e['relation']=='queue_connect_peer' and e['source']=='queue_log' for e in result['edges']))
        self.assertIsNotNone(result['final_hangup'])
        self.assertNotIn('actual-agent-uid',json.dumps(result))

    def test_connect_peer_foreign_visits_or_multiple_callers_are_not_grants(self):
        self.seed(*self.visit('private-root-uid',peer='actual-agent-uid'),
                  *self.visit('actual-agent-uid','8002',102),
                  self.cel('actual-agent-uid','ANSWER',110))
        self.assertEqual(len([n for n in self.report()['nodes'] if n['type']=='call_leg']),1)
        self.seed(*self.visit('other-caller-uid',peer='ambiguous-peer',stamp=150),
                  *self.visit('next-caller-uid',peer='ambiguous-peer',stamp=180),
                  self.cel('ambiguous-peer','ANSWER',151))
        result=explain(self.archive,self.scope,90,300,self.ident('other-caller-uid'))
        self.assertEqual(len([n for n in result['nodes'] if n['type']=='call_leg']),1)
        self.assertTrue(result['coverage']['restricted_or_unproven'])

    def test_connect_time_and_self_cutoff_must_match_the_owned_visit(self):
        self.seed(*self.visit('private-root-uid',peer='actual-agent-uid'),
                  self.cel('actual-agent-uid','CHAN_START',110))
        self.assertEqual(len([n for n in self.report()['nodes'] if n['type']=='call_leg']),1)
        self.assertIsNone(explain(self.archive,Scope(('8001',),('PJSIP/100',),True,101),90,300,self.ident()))

    def test_foreign_incoming_vetoes_uid_even_with_its_own_allowed_visit(self):
        self.seed(*self.visit('private-root-uid'),
                  *self.visit('foreign-caller','8002',stamp=130,peer='private-root-uid'),
                  self.cel('private-root-uid','ANSWER',131))
        result=self.report()
        self.assertFalse(any(event['source']=='cel' for event in result['events']))
        self.assertTrue(result['coverage']['restricted_or_unproven'])

    def test_connect_late_versions_and_version_six_are_conservative(self):
        events=self.visit('private-root-uid',peer='old-peer');connect=events[1]
        self.seed(*events,self.cel('old-peer','ANSWER',101),self.cel('new-peer','ANSWER',101))
        changed=dict(connect.payload,values=['1','new-peer','0'])
        self.seed(Event(connect.source,connect.key,connect.timestamp,connect.kind,changed))
        result=self.report()
        self.assertEqual(len([n for n in result['nodes'] if n['type']=='call_leg']),2)
        self.assertEqual(sum(e['relation']=='queue_connect_peer' for e in result['edges']),1)
        with self.archive.writer() as db:db.execute('UPDATE report_projection_version SET version=6')
        self.assertFalse(any(e['source']=='cel' for e in self.report()['events']))

    def test_version_seven_replay_rebuilds_legacy_connect_edges_without_http_writes(self):
        self.seed(*self.visit('private-root-uid',peer='actual-agent-uid'),self.cel('actual-agent-uid','ANSWER',101))
        with self.archive.writer() as db:
            db.execute("DELETE FROM evidence_edges WHERE relation='queue_connect_peer'")
            db.execute('UPDATE report_projection_version SET version=6')
        while project_batch(self.archive,limit=1)['processed']:pass
        self.assertTrue(any(e['relation']=='queue_connect_peer' for e in self.report()['edges']))
        with self.archive.reader() as db:
            before=tuple(db.execute('''SELECT (SELECT COUNT(*) FROM events),
                (SELECT COUNT(*) FROM evidence_edges),after_id FROM report_projection WHERE pbx='primary' ''').fetchone())
        self.report()
        with self.archive.reader() as db:
            after=tuple(db.execute('''SELECT (SELECT COUNT(*) FROM events),
                (SELECT COUNT(*) FROM evidence_edges),after_id FROM report_projection WHERE pbx='primary' ''').fetchone())
        self.assertEqual(after,before)

    def test_version_eight_replay_removes_legacy_second_channel_target(self):
        transfer=self.cel('private-root-uid','ATTENDEDTRANSFER',110,
            eventextra=json.dumps(dict(channel2_name='PJSIP/consulting-leg',app='Queue')))
        self.seed(*self.visit('private-root-uid'),transfer)
        with self.archive.writer() as db:
            event_id=db.execute("SELECT event_id FROM source_items WHERE source='cel' AND source_key=?",(transfer.key,)).fetchone()[0]
            db.execute('DELETE FROM evidence_edges WHERE event_id=? AND relation=?',(event_id,'transfer_second_channel'))
            db.execute('INSERT INTO evidence_edges VALUES(?,?,?,?,?,?,?,?,?)',
                (self.archive.pbx,event_id,'attendedtransfer','uniqueid','private-root-uid','channel','PJSIP/consulting-leg',110,'{}'))
            db.execute('UPDATE transfers SET target=? WHERE event_id=?',('PJSIP/consulting-leg',event_id))
            db.execute('UPDATE report_projection_version SET version=7')
        self.assertFalse(any(event['source']=='cel' for event in self.report()['events']))
        # Incremental replay performs the correction, never HTTP graph reads.
        while project_batch(self.archive,limit=1)['processed']:pass
        with self.archive.reader() as db:
            target=db.execute('SELECT target,consultation_duration FROM transfers WHERE event_id=?',(event_id,)).fetchone()
            self.assertEqual(tuple(target),('',None))
            edges=db.execute('SELECT relation FROM evidence_edges WHERE event_id=?',(event_id,)).fetchall()
            self.assertEqual([row[0] for row in edges],['transfer_second_channel'])
            self.assertEqual(db.execute('SELECT version FROM report_projection_version').fetchone()[0],8)

    def test_second_initiator_graph_is_not_transfer_target_or_audio_permission(self):
        self.seed(*self.visit('private-root-uid'),*self.visit('private-peer-uid',stamp=102),
            self.event('cel','private-peer-uid','CHAN_START',103,channame='PJSIP/consulting-leg'),
            self.cel('private-root-uid','ATTENDEDTRANSFER',110,eventextra=json.dumps(dict(
                channel2_name='PJSIP/consulting-leg',app='Queue',consultation_started=105,consultation_ended=109))))
        result=self.report()
        edge=next(edge for edge in result['edges'] if edge['relation']=='transfer_second_channel')
        self.assertNotIn('consultation_seconds',edge)
        self.assertFalse(any(edge['relation']=='attendedtransfer' for edge in result['edges']))
        self.assertFalse(result['audio_granted']);self.assertIsNone(result['final_hangup'])
        self.assertNotIn('PJSIP/consulting-leg',json.dumps(result))

    def test_large_cel_payload_is_sql_omitted_by_utf8_bytes(self):
        self.seed(*self.visit('private-root-uid'),self.cel('private-root-uid','CHAN_START',100),
                  self.cel('private-root-uid','ANSWER',105,private='س'*3000))
        result=self.report()
        self.assertTrue(result['coverage']['limit_reached'])
        self.assertTrue(result['coverage']['restricted_or_unproven'])
        self.assertFalse(any(event['source']=='cel' and event['kind']=='ANSWER' for event in result['events']))
        self.assertIn('CONNECT',[event['kind'] for event in result['events']])
        self.assertNotIn('س'*100,json.dumps(result,ensure_ascii=False))

    def test_oversized_edge_details_do_not_expand_the_peer(self):
        self.seed(*self.visit('private-root-uid'),*self.visit('peer-uid',stamp=102),
                  self.cel('private-root-uid','CHAN_START',100),
                  self.event('cel','peer-uid','CHAN_START',103,channame='Local/peer;2'),
                  self.cel('private-root-uid','ATTENDEDTRANSFER',104,
                    eventextra=json.dumps(dict(transfer_target_channel_name='Local/peer;2',private='x'*3000))))
        result=self.report()
        self.assertTrue(result['coverage']['limit_reached'])
        self.assertEqual(len([node for node in result['nodes'] if node['type']=='call_leg']),1)
        self.assertNotIn('x'*100,json.dumps(result))

    def test_oversized_incoming_connect_proof_is_not_an_ownership_grant(self):
        self.seed(*self.visit('private-root-uid',peer='actual-agent-uid'),
                  self.event('cel','actual-agent-uid','ANSWER',101,channame='PJSIP/agent-only-000000ab'))
        with self.archive.writer() as db:
            db.execute("UPDATE evidence_edges SET details=? WHERE relation='queue_connect_peer'",
                (json.dumps(dict(queue='8001',agent='PJSIP/100',padding='x'*3000)),))
        # Exercise incoming validation via an independent allowed Local edge;
        # oversized outgoing CONNECT cannot itself expand the agent.
        self.seed(self.cel('private-root-uid','LOCAL_OPTIMIZE',105,
            eventextra=json.dumps(dict(local_two='PJSIP/agent-only-000000ab'))))
        result=self.report()
        self.assertTrue(result['coverage']['limit_reached'])
        self.assertEqual(len([node for node in result['nodes'] if node['type']=='call_leg']),1)

    def test_aggregate_evidence_byte_budget_returns_partial_not_fabricated_empty(self):
        self.seed(*self.visit('private-root-uid'),self.cel('private-root-uid','CHAN_START',100),
                  self.cel('private-root-uid','ANSWER',105))
        with patch('sanequeue.reporting.journey.MAX_EVIDENCE_BYTES',1):result=self.report()
        self.assertTrue(result['coverage']['limit_reached'])
        self.assertTrue(result['events'])
        self.assertTrue(all(event['source']=='queue_log' for event in result['events']))


if __name__=='__main__':unittest.main()
