"""Observed work intervals, reconnect gaps, retention boundaries and API scope."""
import asyncio
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask
from flask_login import LoginManager,UserMixin
from sanequeue.realtime.activity import ActivityStore,ActivityRecorder
from sanequeue.api.activity import install


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=ActivityStore(Path(self.tmp.name)/'activity.sqlite3')
        self.stamp=datetime.fromisoformat('2026-10-25T08:00:00+03:30').timestamp()

    def observe(self, recorder, offset, *, paused=False, status='1', reason=''):
        recorder.observe({'8001':{'members':{'PJSIP/100':{'status':status,'paused':str(int(paused)),'pausedreason':reason}}}},self.stamp+offset)

    def test_event_transitions_and_independent_reason_totals(self):
        recorder=ActivityRecorder(self.store);recorder.reset('g1')
        self.observe(recorder,0);self.observe(recorder,60,paused=True,reason='lunch')
        self.observe(recorder,90,paused=True,reason='meeting');self.observe(recorder,150)
        self.observe(recorder,200);asyncio.run(recorder.flush())
        result=self.store.daily(['8001'],'2026-10-25',now=self.stamp+210)
        rows=result['rows'];self.assertEqual(sum(r['seconds'] for r in rows),200)
        self.assertEqual(sum(r['seconds'] for r in rows if r['on_duty']),110)
        self.assertEqual({r['reason']:r['seconds'] for r in rows if r['state']=='paused'},{'lunch':30,'meeting':60})

    def test_restart_closes_old_interval_at_last_confirmed_heartbeat(self):
        self.store.write([('8001','SIP/100','available','',self.stamp,True)],self.stamp+10,'old')
        self.store.write([('8001','SIP/100','available','',self.stamp+100,True)],self.stamp+120,'new')
        rows=self.store.daily(['8001'],'2026-10-25',now=self.stamp+1000)['rows']
        self.assertEqual(sum(r['seconds'] for r in rows),30)

    def test_removal_and_return_are_separate_from_pause(self):
        recorder=ActivityRecorder(self.store);recorder.reset('g')
        self.observe(recorder,0);recorder.observe({'8001':{'members':{}}},self.stamp+40)
        self.observe(recorder,100);self.observe(recorder,120);asyncio.run(recorder.flush())
        rows=self.store.daily(['8001'],'2026-10-25',now=self.stamp+120)['rows']
        self.assertEqual(next(r['seconds'] for r in rows if r['state']=='removed'),60)
        self.assertEqual(sum(r['seconds'] for r in rows if r['on_duty']),60)

    def test_midnight_splits_interval_in_tehran_not_utc(self):
        before=datetime.fromisoformat('2026-10-24T23:59:30+03:30').timestamp()
        self.store.write([('8001','SIP/100','available','',before,True)],before+90,'g')
        self.assertEqual(self.store.daily(['8001'],'2026-10-24',now=before+100)['rows'][0]['seconds'],30)
        self.assertEqual(self.store.daily(['8001'],'2026-10-25',now=before+100)['rows'][0]['seconds'],60)

    def test_late_old_generation_cannot_overwrite_new_observation(self):
        self.store.write([('8001','SIP/100','available','',self.stamp,True)],self.stamp+10,'old')
        self.store.write([('8001','SIP/100','paused','meeting',self.stamp+100,False)],self.stamp+120,'new')
        self.store.write([('8001','SIP/100','offline','',self.stamp+20,False)],self.stamp+30,'old')
        result=self.store.daily(['8001'],'2026-10-25',now=self.stamp+130)
        self.assertEqual(result['observed_until'],self.stamp+120)
        self.assertFalse(any(row['state']=='offline' for row in result['rows']))

    def test_new_phone_owner_does_not_inherit_previous_owners_activity(self):
        self.store.write([('8001','SIP/100','available','',self.stamp,True)],self.stamp+100,'g')
        rows=self.store.daily(['8001'],'2026-10-25',not_before=self.stamp+80,now=self.stamp+100)['rows']
        self.assertEqual(sum(row['seconds'] for row in rows),20)
        self.assertEqual(rows[0]['first'],self.stamp+80)

    def test_disk_failure_is_bounded_and_does_not_block_collector(self):
        recorder=ActivityRecorder(self.store,max_pending=3);recorder.reset('g')
        for index in range(20):self.observe(recorder,index,paused=index%2==0)
        self.assertLessEqual(len(recorder.pending),3);self.assertGreater(recorder.dropped,0)
        with patch.object(self.store,'write',side_effect=OSError('synthetic disk failure')):asyncio.run(recorder.flush())
        self.assertLessEqual(len(recorder.pending),3)

    def test_api_own_and_supervisor_scope(self):
        clock=patch('sanequeue.api.activity.datetime').start();self.addCleanup(patch.stopall)
        clock.now.return_value=datetime.fromisoformat('2026-10-25T09:00:00+03:30')
        clock.strptime.side_effect=datetime.strptime
        self.store.write([('8001','PJSIP/100','available','',self.stamp,True),('8001','PJSIP/200','available','',self.stamp,True),('8002','PJSIP/100','available','',self.stamp,True)],self.stamp+10,'g')
        app=Flask('activity-test');app.secret_key='test-only'
        manager=LoginManager(app)
        class User(UserMixin):id='test-agent'
        manager.user_loader(lambda _:User())
        current_role=['agent']
        assigned=[0]
        install(app,self.store.path,lambda:{'8001':{}},lambda:current_role[0],lambda:['PJSIP/100'],lambda q:{'pause_reasons':[]},lambda:assigned[0])
        client=app.test_client()
        with client.session_transaction() as session:session['_user_id']='test-agent'
        self.assertEqual(client.get('/api/activity/daily?day=2026-10-25').status_code,403)
        own=client.get('/api/profile/activity?day=2026-10-25').json
        self.assertEqual({(r['queue'],r['agent']) for r in own['rows']},{('8001','PJSIP/100')})
        assigned[0]=self.stamp+5
        own=client.get('/api/profile/activity?day=2026-10-25').json
        self.assertEqual(sum(row['seconds'] for row in own['rows']),5)
        self.assertEqual(client.get('/api/profile/activity?queue=8002').status_code,403)
        current_role[0]='supervisor'
        self.assertEqual(len(client.get('/api/activity/daily?day=2026-10-25').json['rows']),2)


if __name__=='__main__':unittest.main()
