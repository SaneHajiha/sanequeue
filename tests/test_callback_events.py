import unittest
import tempfile
import sqlite3
from contextlib import closing
from pathlib import Path
from sanequeue.pbx.events import CallbackEvents
from sanequeue.pbx.callbacks import CallbackWorker
from sanequeue.realtime.state import QueueState

class CallbackEvidenceTests(unittest.TestCase):
    def test_retained_history_migration_indexes_live_queries_and_latest_report(self):
        now=100*86400;old=now-40*86400
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);spool=root/'spool';spool.mkdir()
            # Start with the original eight-column schema to exercise upgrade,
            # with history far larger than the active callback capacity.
            with closing(sqlite3.connect(root/'callbacks.sqlite3')) as db:
                db.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,source TEXT,target TEXT,created REAL,expires REAL,state TEXT,action_id TEXT,updated REAL)')
                db.executemany('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)',[
                    ('old-'+str(n),'PJSIP/300','100',old+n/100,old+60,'completed','',old+20) for n in range(5000)])
                db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)',('active','PJSIP/300','100',now,now+60,'pending','',now))
                db.commit()
            worker=CallbackWorker(root,spool=spool)
            statements=[
                ("SELECT COUNT(*) FROM jobs WHERE state='pending'",(),('state_expiry','state_updated')),
                ("SELECT 1 FROM jobs WHERE source=? AND target=? AND state IN ('pending','dispatching','accepted') AND expires>?",('PJSIP/300','100',now),('pair_expiry',)),
                ("UPDATE jobs SET state='expired',updated=? WHERE state='pending' AND expires<=?",(now,now),('state_expiry',)),
                ("UPDATE jobs SET state='unknown',updated=? WHERE state='dispatching' AND updated<?",(now,now-30),('state_updated',)),
                ("SELECT id,action_id,updated,state,connected_at FROM jobs WHERE state IN ('accepted','caller_answered','connected')",(),('state_expiry','state_updated')),
                ('SELECT source,target,created,state FROM jobs ORDER BY created DESC LIMIT 100',(),('created',)),
            ]
            with worker.db() as db:
                for statement,args,indexes in statements:
                    with self.subTest(statement=statement):
                        plan=' '.join(str(row['detail']) for row in db.execute('EXPLAIN QUERY PLAN '+statement,args))
                        self.assertTrue(any('callback_jobs_'+name in plan for name in indexes),plan)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM jobs WHERE state='pending'").fetchone()[0],1)
            worker.ingest({},now)
            with worker.db() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],5001)
                self.assertEqual(db.execute('SELECT id FROM jobs ORDER BY created DESC LIMIT 1').fetchone()[0],'active')

    def test_expired_requests_stop_dialing_without_deleting_old_history(self):
        now=100*86400
        old=now-40*86400
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);spool=root/'spool';spool.mkdir()
            worker=CallbackWorker(root,spool=spool)
            with worker.db() as db:
                for ident,state in [('terminal','completed'),('pending','pending'),('uncertain','dispatching')]:
                    db.execute('INSERT INTO jobs(id,source,target,created,expires,state,action_id,updated) VALUES(?,?,?,?,?,?,?,?)',
                        (ident,'PJSIP/300','100',old,old+60,state,'action-'+ident,old+20))
                db.execute("UPDATE jobs SET connected_at=?,ended_at=?,talk_seconds=? WHERE id='terminal'",(old+5,old+20,15))
            worker.ingest({},now)
            with worker.db() as db:
                rows={row['id']:dict(row) for row in db.execute('SELECT * FROM jobs')}
            self.assertEqual(set(rows),{'terminal','pending','uncertain'})
            self.assertEqual(rows['terminal']['state'],'completed')
            self.assertEqual(rows['terminal']['talk_seconds'],15)
            self.assertEqual(rows['terminal']['updated'],old+20)
            self.assertEqual(rows['pending']['state'],'expired')
            self.assertEqual(rows['uncertain']['state'],'unknown')

    def test_actual_target_bridge_and_source_hangup_are_separate_from_acceptance(self):
        clock=[100];state=QueueState(clock=lambda:clock[0]);tracker=CallbackEvents()
        def send(kind,**values):
            packet=dict(Event=kind,**values);state.ingest(packet);tracker.observe(packet,state);clock[0]+=1
        send('Newchannel',Uniqueid='s',Channel='PJSIP/300-000abc',ChannelStateDesc='Up')
        send('OriginateResponse',ActionID='sq-cb-test',Response='Success',Uniqueid='s',Exten='100')
        self.assertNotIn('connected_at',state.action_events['sq-cb-test'])
        send('Newchannel',Uniqueid='t',Channel='PJSIP/100-000def',ChannelStateDesc='Up')
        send('BridgeEnter',Uniqueid='s',Channel='PJSIP/300-000abc',BridgeUniqueid='bridge')
        send('BridgeEnter',Uniqueid='t',Channel='PJSIP/100-000def',BridgeUniqueid='bridge')
        row=state.action_events['sq-cb-test'];self.assertEqual(row['connected_at'],104)
        send('Hangup',Uniqueid='s',Channel='PJSIP/300-000abc');self.assertEqual(row['ended_at'],105)
    def test_other_phone_bridge_is_not_proof_target_answered(self):
        state=QueueState();tracker=CallbackEvents()
        for event in (dict(Event='OriginateResponse',ActionID='sq-cb-test',Response='Success',Uniqueid='s',Exten='100'),dict(Event='Newchannel',Uniqueid='s',Channel='PJSIP/300-000abc'),dict(Event='Newchannel',Uniqueid='t',Channel='PJSIP/200-000def'),dict(Event='BridgeEnter',Uniqueid='s',BridgeUniqueid='b'),dict(Event='BridgeEnter',Uniqueid='t',BridgeUniqueid='b')):
            state.ingest(event);tracker.observe(event,state)
        self.assertNotIn('connected_at',state.action_events['sq-cb-test'])
