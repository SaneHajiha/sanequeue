import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from sanequeue.reporting.work_sessions import (WorkSessions,SessionConflict,SessionAccessDenied,
    SessionUnavailable,calls,summary)
from sanequeue.reporting.store import Archive,Event,QueryDeadline
from sanequeue.reporting.facts import project_batch
from sanequeue.reporting.queries import Scope


class WorkSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.store=WorkSessions(self.root/'sessions.db');self.store.initialize()
        self.archive=Archive(self.root/'history.db',min_free_bytes=0);self.archive.initialize()
        self.scope=Scope(('8001','8002'))
        self.inventory=dict(observed_at=100,endpoints=[
            dict(technology='PJSIP',endpoint='100',category='extension'),
            dict(technology='SIP',endpoint='200',category='extension'),
            dict(technology='PJSIP',endpoint='provider',category='trunk')])

    def open(self,*,actor='alice',agent='PJSIP/100',queues=('8001','8002'),key='request',stamp=100,purpose='happy_call'):
        with patch('sanequeue.reporting.work_sessions.time.time',return_value=stamp):
            return self.store.open(actor,agent,purpose,'Customer follow-up',queues,key)

    def close(self,session,stamp=200):
        with patch('sanequeue.reporting.work_sessions.time.time',return_value=stamp):
            return self.store.close(session['id'],'supervisor')

    def seed_calls(self,specifications):
        events=[]
        for key,stamp,dst,status,billsec in specifications:
            events.append(Event('cdr',key,stamp,'CDR',dict(uniqueid=key,linkedid='shared-linkedid',
                channel='PJSIP/100-000000ab',dstchannel=dst,dst='09123456789',duration=40,
                disposition=status,billsec=billsec,recordingfile='private-recording.wav')))
        self.archive.append(events)
        while project_batch(self.archive,inventory=self.inventory)['processed']:pass

    def test_explicit_session_survives_complete_queue_removal_without_activity(self):
        session=self.close(self.open())
        self.seed_calls([('first',110,'PJSIP/provider-000000ac','ANSWERED',30),
                         ('second',120,'PJSIP/provider-000000ad','ANSWERED',20)])
        with self.archive.reader() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM report_activity').fetchone()[0],0)
        result=summary(self.archive,session,self.scope,90,300)
        self.assertEqual(result['totals']['segments_started'],2)
        self.assertEqual(result['totals']['known_billsec_sum'],50)
        self.assertEqual(result['declared_seconds'],100)
        self.assertEqual(len(calls(self.archive,session,self.scope,90,300)['rows']),2)
        self.assertNotIn('linkedid',json.dumps(result))
        self.assertNotIn('09123456789',json.dumps(result))
        self.assertEqual(session['queues'],['8001','8002'])

    def test_same_cdr_is_not_duplicated_by_multi_queue_scope_and_directions_are_separate(self):
        session=self.close(self.open())
        self.seed_calls([('out',150,'PJSIP/provider-000000ac','ANSWERED',30),
                         ('internal',160,'SIP/200-000000ad','ANSWERED',0),
                         ('unknown',170,'Local/200@from-queue-000000ae;1','ANSWERED',10)])
        self.assertEqual(summary(self.archive,session,self.scope,90,300)['totals']['segments_started'],1)
        internal=summary(self.archive,session,self.scope,90,300,direction='internal')
        self.assertEqual(internal['totals']['answered_segments'],1)
        self.assertEqual(internal['totals']['average_answered_billsec'],0)
        for direction in ('inbound','all','unknown'):
            with self.assertRaises(ValueError):calls(self.archive,session,self.scope,90,300,direction)

    def test_all_queue_authorization_and_self_assignment_are_checked_before_archive(self):
        session=self.close(self.open())
        self.assertIsNone(self.store.get(session['id'],Scope(('8001',))))
        self.assertEqual(self.store.list(Scope(('8001',)))['rows'],[])
        self.assertEqual(self.store.list(Scope(()))['rows'],[])
        self.assertIsNotNone(self.store.get(session['id'],self.scope))
        for scope in (Scope(('8001',)),Scope(('8001','8002'),('SIP/200',),True),
                      Scope(('8001','8002'),('PJSIP/100',),True,101)):
            self.assertIsNone(self.store.get(session['id'],scope))
            self.assertEqual(self.store.list(scope)['rows'],[])
            missing=Archive(self.root/'does-not-exist.db')
            with self.assertRaises(SessionAccessDenied):calls(missing,session,scope,90,300)
            with self.assertRaises(SessionAccessDenied):summary(missing,session,scope,90,300)
        own=Scope(('8001','8002'),('PJSIP/100',),True,100)
        self.assertIsNotNone(self.store.get(session['id'],own))

    def test_scope_and_time_boundaries_do_not_clip_full_segment_billsec(self):
        session=self.close(self.open(),stamp=180)
        self.seed_calls([('before',99,'PJSIP/provider-ab','ANSWERED',10),
                         ('first',100,'PJSIP/provider-ac','ANSWERED',30),
                         ('included',150,'PJSIP/provider-ad','ANSWERED',60),
                         ('end',160,'PJSIP/provider-ae','ANSWERED',20),
                         ('session-end',180,'PJSIP/provider-af','ANSWERED',5)])
        result=summary(self.archive,session,self.scope,140,160)
        self.assertEqual(result['totals']['segments_started'],1)
        self.assertEqual(result['totals']['known_billsec_sum'],60)
        self.assertEqual(result['declared_seconds'],20)
        self.assertEqual([row['id'] for row in calls(self.archive,session,self.scope,140,160)['rows']],['included'])
        self.assertEqual(summary(self.archive,session,self.scope,200,250)['declared_seconds'],0)

    def test_open_session_uses_server_now_and_close_accepts_no_supplied_timestamp(self):
        session=self.open()
        self.seed_calls([('known',130,'PJSIP/provider-ab','ANSWERED',10),
                         ('future',160,'PJSIP/provider-ac','ANSWERED',10)])
        with patch('sanequeue.reporting.work_sessions.time.time',return_value=150):
            result=summary(self.archive,session,self.scope,90,300)
        self.assertEqual(result['declared_seconds'],50)
        self.assertEqual(result['totals']['segments_started'],1)
        with self.assertRaises(TypeError):self.store.close(session['id'],'alice',now=120)
        with self.assertRaises(TypeError):self.store.open('alice','PJSIP/100','survey','Title',['8001'],'key',now=1)
        self.assertEqual(self.store.get(session['id'],self.scope)['state'],'open')

    def test_idempotent_actor_key_single_open_and_non_overlapping_server_intervals(self):
        first=self.open()
        retry=self.open(queues=('8002','8001'),stamp=150)
        self.assertEqual(retry['id'],first['id']);self.assertEqual(retry['started_at'],100)
        with self.assertRaisesRegex(SessionConflict,'request_key_reused'):self.open(purpose='survey')
        with self.assertRaisesRegex(SessionConflict,'already_open'):self.open(key='another-key')
        second_actor=self.open(actor='bob',agent='SIP/200',queues=('8001',),stamp=100)
        self.assertNotEqual(first['id'],second_actor['id'])
        closed=self.close(first,stamp=200)
        self.assertEqual(self.close(first,stamp=300)['ended_at'],200)
        self.assertEqual(self.open(stamp=300)['state'],'closed')
        with self.assertRaisesRegex(SessionConflict,'clock_regressed'):self.open(key='next',stamp=199)
        next_session=self.open(key='next',stamp=200)
        self.assertEqual(next_session['started_at'],closed['ended_at'])
        with self.assertRaisesRegex(SessionConflict,'clock_regressed'):self.close(next_session,stamp=199)

    def test_session_cursor_filters_before_pagination_and_does_not_leak_other_queues(self):
        expected=[]
        for index in range(4):
            session=self.open(key='key-'+str(index),stamp=100+index*20,queues=('8001',))
            expected.append(session['id']);self.close(session,stamp=110+index*20)
        hidden=self.open(agent='SIP/200',actor='bob',key='hidden',queues=('8002',),stamp=180)
        visible=Scope(('8001',))
        first=self.store.list(visible,limit=2)
        second=self.store.list(visible,before=first['next'],limit=2)
        self.assertEqual([row['id'] for row in first['rows']+second['rows']],expected[::-1])
        self.assertIsNone(second['next'])
        self.assertNotIn(hidden['id'],json.dumps(first))
        self.assertEqual(self.store.list(visible,state='open')['rows'],[])
        self.assertEqual(len(self.store.list(visible,state='closed',purpose='happy_call')['rows']),4)
        for cursor in ('',1,'A'*12):
            with self.assertRaises(ValueError):self.store.list(visible,before=cursor)

    def test_cdr_keyset_unknown_billsec_and_summary_covers_more_than_one_page(self):
        session=self.close(self.open())
        entries=[('call-'+str(index),150,'PJSIP/provider-ab','ANSWERED',None if index==0 else 0) for index in range(205)]
        entries.append(('busy',160,'PJSIP/provider-ac','BUSY',0))
        entries.append(('unknown',170,'PJSIP/provider-ad','UNRECOGNIZED',None))
        self.seed_calls(entries)
        first=calls(self.archive,session,self.scope,90,300,limit=10000)
        second=calls(self.archive,session,self.scope,90,300,before=first['next'])
        third=calls(self.archive,session,self.scope,90,300,before=second['next'])
        all_rows=first['rows']+second['rows']+third['rows']
        self.assertEqual(len(all_rows),207);self.assertEqual(len({row['id'] for row in all_rows}),207)
        self.assertEqual(set(all_rows[0]),{'id','ts','destination','duration','billsec','disposition','agent','has_recording'})
        self.assertFalse(first['audio_granted'])
        self.assertNotIn('call-0',[row['id'] for row in first['rows']])
        exact=calls(self.archive,session,self.scope,90,300,ident='call-0')
        self.assertEqual([row['id'] for row in exact['rows']],['call-0'])
        self.assertEqual(calls(self.archive,session,self.scope,90,300,ident='absent')['rows'],[])
        result=summary(self.archive,session,self.scope,90,300)
        self.assertEqual(result['totals']['segments_started'],207)
        self.assertEqual(result['totals']['answered_segments'],205)
        self.assertEqual(result['totals']['unanswered_segments'],1)
        self.assertEqual(result['totals']['unknown_disposition_segments'],1)
        self.assertEqual(result['totals']['unknown_billsec_count'],2)
        self.assertEqual(result['totals']['average_answered_billsec'],0)
        with patch('sanequeue.reporting.store.time.monotonic',side_effect=[0]+[10]*100):
            with self.assertRaises(QueryDeadline):summary(self.archive,session,self.scope,90,300)

    def test_missing_startup_private_file_busy_writer_and_bad_input(self):
        missing=WorkSessions(self.root/'missing.db')
        with self.assertRaises(SessionUnavailable):missing.open('a','PJSIP/100','survey','Title',['8001'],'key')
        self.assertFalse(missing.path.exists())
        if os.name!='nt':self.assertEqual(self.store.path.stat().st_mode&0o777,0o600)
        blocker=sqlite3.connect(self.store.path)
        try:
            blocker.execute('BEGIN IMMEDIATE')
            with self.assertRaises(SessionUnavailable):self.open()
        finally:blocker.rollback();blocker.close()
        for queues in ([],['8001']*257,'8001'):
            with self.assertRaises(ValueError):self.open(queues=queues)
        with self.assertRaises(ValueError):self.open(purpose='break')
        with self.assertRaises(ValueError):self.store.get('../sessions.db',self.scope)

    def test_summary_redacts_health_and_marks_stale_or_unprojected_zero_unknown(self):
        session=self.close(self.open())
        project_batch(self.archive,inventory=self.inventory)
        result=summary(self.archive,session,self.scope,90,300)
        self.assertEqual(result['coverage'],'unknown_sql_coverage')
        self.assertTrue(result['stale']);self.assertFalse(result['complete_history'])
        raw=dict(ok=True,checked=250,private_path='/private/password-token',token='never-expose',
                 progress=dict(cdr_caught_up=True,cel_caught_up=True,path='/secret/source'))
        self.archive.append([],checkpoint_source='health:sql',checkpoint=raw)
        with patch('sanequeue.reporting.work_sessions.time.time',return_value=300):
            result=summary(self.archive,session,self.scope,90,300)
        self.assertEqual(result['coverage'],'observed_sql_snapshot')
        self.assertEqual(set(result['sql_health']),{'ok','checked','progress','source_gap'})
        self.assertEqual(set(result['sql_health']['progress']),{'cdr_caught_up','cel_caught_up'})
        for private in ('/private/','/secret/','password-token','never-expose','private_path'):
            self.assertNotIn(private,json.dumps(result))
        self.archive.append([Event('cdr','pending',150,'CDR',dict(uniqueid='pending'))])
        with patch('sanequeue.reporting.work_sessions.time.time',return_value=300):
            result=summary(self.archive,session,self.scope,90,300)
        self.assertFalse(result['projection']['caught_up'])
        self.assertEqual(result['coverage'],'unknown_sql_coverage')
        with patch('sanequeue.reporting.work_sessions.time.time',return_value=341):
            self.assertTrue(summary(self.archive,session,self.scope,90,300)['stale'])
