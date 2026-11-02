"""Durable conversion is private, bounded, recoverable and never runs in HTTP."""
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import wave

from flask import Flask
from flask_login import LoginManager,UserMixin
from sanequeue.pbx.incident_media import MediaJobs,MediaWorker,local_authorizer,MAX_INPUT
from sanequeue.pbx.features import install


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.jobs=MediaJobs(self.root);self.jobs.initialize();self.allowed={'support':dict(context='from-test',queue='8001',label='Support')}
        output=io.BytesIO()
        with wave.open(output,'wb') as sound:
            sound.setnchannels(1);sound.setsampwidth(2);sound.setframerate(8000);sound.writeframes(b'\0\0'*800)
        self.audio=output.getvalue();self.grant=True
        self.auth=lambda owner:self.grant and owner=='owner'
    def enqueue(self,**kwargs):return self.jobs.enqueue('owner','support',b'input',authorize=self.auth,**kwargs)
    def worker(self,**kwargs):return MediaWorker(self.jobs,authorize=self.auth,allowed=lambda:self.allowed,ready=lambda:True,convert=lambda content:(self.audio,.1),**kwargs)

    def test_default_deny_and_owner_scoped_status(self):
        with self.assertRaises(PermissionError):self.jobs.enqueue('owner','support',b'input')
        job=self.enqueue()
        with self.assertRaises(LookupError):self.jobs.status(job['id'],'other',lambda owner:True)
        self.grant=False
        with self.assertRaises(PermissionError):self.jobs.status(job['id'],'owner',self.auth)

    def test_input_limit_capacity_and_low_disk(self):
        with self.assertRaises(ValueError):self.jobs.enqueue('owner','support',b'x'*(MAX_INPUT+1),authorize=self.auth)
        self.enqueue();self.jobs.enqueue('owner','support',b'input2',authorize=self.auth)
        with self.assertRaisesRegex(ValueError,'owner_queue_full'):self.jobs.enqueue('owner','support',b'input3',authorize=self.auth)
        other=MediaJobs(self.root/'other');other.initialize()
        with patch('sanequeue.pbx.incident_media.shutil.disk_usage',return_value=type('Space',(),{'free':1})()):
            with self.assertRaisesRegex(ValueError,'low_disk'):other.enqueue('owner','support',b'a',authorize=self.auth)

    def test_completed_job_has_real_validated_audio_and_is_not_reexecuted(self):
        job=self.enqueue();worker=self.worker();self.assertTrue(worker.tick())
        row=self.jobs.status(job['id'],'owner',self.auth);self.assertEqual(row['state'],'completed');self.assertEqual(row['seconds'],.1)
        self.assertEqual((self.root/'incident-sounds'/(row['audio']+'.wav')).read_bytes(),self.audio)
        self.assertFalse((self.jobs.inputs/(job['id']+'.input')).exists());self.assertFalse(worker.tick())

    def test_duplicate_http_retry_reuses_active_job_without_extra_input(self):
        first=self.enqueue();second=self.enqueue()
        self.assertEqual(first['id'],second['id']);self.assertEqual(len(list(self.jobs.inputs.glob('*.input'))),1)

    def test_revocation_before_execution_and_after_conversion(self):
        first=self.enqueue();self.grant=False;self.worker().tick()
        self.assertEqual(self.jobs.status(first['id'],'owner',lambda owner:True)['error'],'media_not_authorized')
        self.grant=True;second=self.enqueue()
        worker=self.worker()
        def convert(content):self.grant=False;return self.audio,.1
        worker.convert=convert;worker.tick()
        self.assertEqual(self.jobs.status(second['id'],'owner',lambda owner:True)['state'],'failed')
        self.assertFalse((self.root/'incident-sounds').exists())

    def test_disabled_or_overload_does_not_claim_or_convert(self):
        job=self.enqueue();worker=self.worker();worker.ready=lambda:False
        self.assertFalse(worker.tick());self.assertEqual(self.jobs.status(job['id'],'owner',self.auth)['state'],'queued')
        worker.ready=lambda:True;(self.root/'module.disabled').touch()
        self.assertFalse(worker.tick());self.assertEqual(self.jobs.status(job['id'],'owner',self.auth)['state'],'queued')

    def test_changed_input_and_removed_binding_fail_closed(self):
        job=self.enqueue();(self.jobs.inputs/(job['id']+'.input')).write_bytes(b'changed');self.worker().tick()
        self.assertEqual(self.jobs.status(job['id'],'owner',self.auth)['error'],'media_input_changed')
        job=self.enqueue();self.allowed={};self.worker().tick()
        self.assertEqual(self.jobs.status(job['id'],'owner',self.auth)['error'],'media_not_authorized')

    def test_worker_rejects_truncated_pcm_even_if_converter_claims_success(self):
        job=self.enqueue();worker=self.worker();worker.convert=lambda content:(self.audio[:-100],.1)
        worker.tick();row=self.jobs.status(job['id'],'owner',self.auth)
        self.assertEqual(row['state'],'failed');self.assertEqual(row['error'],'invalid_notice_audio')
        self.assertFalse((self.root/'incident-sounds').exists())

    def test_reader_and_publisher_reject_forged_frame_count(self):
        import hashlib
        from sanequeue.pbx.incidents import IncidentStore
        store=IncidentStore(self.root);store.sounds.mkdir()
        content=self.audio[:-100];ident=hashlib.sha256(content).hexdigest()
        (store.sounds/(ident+'.wav')).write_bytes(content)
        with self.assertRaisesRegex(ValueError,'invalid_notice_audio'):store.audio(ident)
        with self.assertRaisesRegex(ValueError,'invalid_notice_audio'):store.publish(content,.1)

    def test_crashed_lease_is_reclaimed_once_without_parallel_claim(self):
        job=self.enqueue();now=time.time();first=self.jobs.claim(now)
        self.assertIsNone(self.jobs.claim(now+1))
        second=self.jobs.claim(now+91);self.assertEqual(first['id'],second['id']);self.assertNotEqual(first['lease'],second['lease'])
        self.assertFalse(self.jobs.finish(first,'failed',error='old_worker'))
        self.assertTrue((self.jobs.inputs/(job['id']+'.input')).exists())
        self.jobs.claim(now+182)
        self.assertEqual(self.jobs.status(job['id'],'owner',self.auth)['state'],'failed')

    def test_crash_after_file_publication_reuses_identical_content(self):
        job=self.enqueue()
        from sanequeue.pbx.incidents import IncidentStore
        original=IncidentStore.publish
        class Crash(BaseException):pass
        def crashed(store,audio,seconds):original(store,audio,seconds);raise Crash()
        with patch.object(IncidentStore,'publish',crashed):
            with self.assertRaises(Crash):self.worker().tick()
        with self.jobs.db() as db:db.execute('UPDATE jobs SET lease_until=?',(time.time()-1,))
        self.worker().tick();self.assertEqual(self.jobs.status(job['id'],'owner',self.auth)['state'],'completed')
        self.assertEqual(len(list((self.root/'incident-sounds').glob('*.wav'))),1)

    def test_terminal_raw_input_cleanup_keeps_job_metadata(self):
        job=self.enqueue();path=self.jobs.inputs/(job['id']+'.input')
        with self.jobs.db() as db:db.execute("UPDATE jobs SET state='failed' WHERE id=?",(job['id'],))
        os.utime(path,(0,0));self.jobs.cleanup()
        self.assertFalse(path.exists());self.assertEqual(self.jobs.status(job['id'],'owner',self.auth)['state'],'failed')

    def test_cleanup_never_materializes_more_than_100_directory_entries(self):
        count=[]
        def entries():
            for index in range(101):
                count.append(index)
                if index>=100:raise AssertionError('unbounded directory enumeration')
                yield type('Entry',(),{'name':'unmanaged-'+str(index)})()
        with patch.object(Path,'iterdir',return_value=entries()):self.jobs.cleanup()
        self.assertEqual(len(count),100)

    def test_fresh_local_authorizer_revokes_role_menu_and_missing_file(self):
        path=self.root/'accounts.json';authorize=local_authorizer(path);self.assertFalse(authorize('owner'))
        value={'owner':dict(role='admin',phone='',password_hash='pbkdf2:sha256:test',menus=['telephony'])}
        path.write_text(json.dumps(value));self.assertTrue(authorize('owner'))
        value['owner']['menus']=[];path.write_text(json.dumps(value));self.assertFalse(authorize('owner'))
        path.write_text('bad json');self.assertFalse(authorize('owner'))

    def test_http_returns_202_and_never_calls_converter(self):
        path=self.root/'local_accounts.json';path.write_text(json.dumps({'owner':dict(role='admin',phone='',password_hash='pbkdf2:sha256:test',menus=['telephony'])}))
        app=Flask(__name__);app.secret_key='test';login=LoginManager(app)
        class User(UserMixin):id='owner'
        login.user_loader(lambda ident:User());install(app,self.root,lambda:'admin');client=app.test_client()
        with client.session_transaction() as session:session['_user_id']='owner';session['_fresh']=True;session['csrf_token']='test'
        with patch('sanequeue.pbx.incidents.bindings',return_value=self.allowed),patch('sanequeue.pbx.features.convert_audio',side_effect=AssertionError('HTTP must not convert')):
            response=client.post('/api/pbx/incidents/audio',data={'binding':'support','audio':(io.BytesIO(b'input'),'x.wav')},headers={'X-CSRF-Token':'test'})
            self.assertEqual(response.status_code,202);self.assertEqual(response.json['state'],'queued')
            status=client.get('/api/pbx/incidents/media/'+response.json['id']);self.assertEqual(status.json['state'],'queued')
            path.write_text('{}');self.assertEqual(client.get('/api/pbx/incidents/media/'+response.json['id']).status_code,403)


if __name__=='__main__':unittest.main()
