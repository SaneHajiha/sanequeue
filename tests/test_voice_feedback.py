"""Actual private SQLite and synthetic WAV; no PBX or external services."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import wave

from flask import Flask
from flask_login import LoginManager,UserMixin
from sanequeue.surveys.voice_feedback import VoiceFeedback,Conflict,Unavailable,pcm,MAX_BYTES
from sanequeue.surveys.voice_feedback_api import install

def wav(*,channels=1,rate=8000,frames=800):
    output=io.BytesIO()
    with wave.open(output,'wb') as sound:
        sound.setnchannels(channels);sound.setsampwidth(2);sound.setframerate(rate);sound.writeframes(b'\0\0'*frames*channels)
    return output.getvalue()

class VoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.store=VoiceFeedback(self.root);self.store.initialize();self.audio=wav()
    def intake(self,**kwargs):return self.store.intake(self.audio,'8001','admin','test',**kwargs)[0]
    def test_pcm_format_duration_truncation_and_size_fail_closed(self):
        self.assertEqual(pcm(self.audio),.1)
        invalid=[b'not audio',wav(channels=2),wav(rate=16000),wav(frames=480001),self.audio[:-1],self.audio+b'junk',b'x'*(MAX_BYTES+1)]
        truncated=bytearray(self.audio);truncated[40:44]=(len(self.audio)*2).to_bytes(4,'little');invalid.append(bytes(truncated))
        for data in invalid:
            with self.subTest(size=len(data)),self.assertRaises(ValueError):pcm(data)
    def test_manual_attribution_replay_and_conflict_are_explicit(self):
        row=self.intake();again,created=self.store.intake(self.audio,'8001','admin','test')
        self.assertFalse(created);self.assertEqual(row['id'],again['id']);self.assertFalse(row['evidence']['caller_ownership_verified'])
        with self.assertRaises(Conflict):self.store.intake(wav(frames=900),'8001','admin','test')
        with self.assertRaises(Conflict):self.store.intake(self.audio,'8002','admin','test')
        with self.assertRaises(PermissionError):self.store.intake(self.audio,'8001','admin','survey',survey=dict(id='a'*32,queue='8002',agent='100'))
        linked=self.store.intake(self.audio,'8001','admin','survey',survey=dict(id='a'*32,queue='8001',agent='Local/100@from-queue/n'))[0]
        self.assertEqual(linked['evidence']['agent'],'Local/100@from-queue/n');self.assertFalse(linked['evidence']['caller_ownership_verified'])
    def test_two_concurrent_same_intakes_have_one_audio_and_one_audit(self):
        def upload(_):return self.store.intake(self.audio,'8001','admin','racing')
        with ThreadPoolExecutor(max_workers=2) as pool:rows=list(pool.map(upload,range(2)))
        self.assertEqual(len({row[0]['id'] for row in rows}),1);self.assertEqual(sum(row[1] for row in rows),1)
        with self.store.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM voice_audit').fetchone()[0],1)
    def test_scoped_reports_keyset_audio_integrity_and_audit(self):
        first=self.intake();self.store.intake(self.audio,'8002','other','other')
        report=self.store.report(('8001',));self.assertEqual(len(report['rows']),1);self.assertNotIn('audio',report['rows'][0])
        with self.assertRaises(FileNotFoundError):self.store.audio(first['id'],('8002',),'boss','play_request')
        self.assertEqual(self.store.audio(first['id'],('8001',),'boss','play_request'),self.audio)
        self.assertEqual(self.store.history(first['id'],('8001',))[0]['action'],'play_request')
        with self.assertRaises(FileNotFoundError):self.store.detail('../feedback.sqlite3',('8001',))
        with self.store.db(True) as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('UPDATE feedback SET queue=? WHERE id=?',('8002',first['id']))
    def test_review_version_fence_preserves_evidence_and_resolves_without_delete(self):
        row=self.intake();changed=self.store.update(row['id'],('8001',),'boss',version=1,status='followup',assignee='boss',note='<script>unsafe</script>')
        self.assertEqual(changed['version'],2);self.assertEqual(changed['evidence'],row['evidence'])
        with self.assertRaises(Conflict):self.store.update(row['id'],('8001',),'admin',version=1,status='resolved')
        self.store.update(row['id'],('8001',),'admin',version=2,status='discarded')
        self.assertEqual(self.store.audio(row['id'],('8001',),'admin','download_request'),self.audio)
    def test_concurrent_review_only_one_version_can_win(self):
        row=self.intake()
        def update(status):
            try:self.store.update(row['id'],('8001',),'boss',version=1,status=status);return 'won'
            except Conflict:return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(update,['reviewing','resolved']))
        self.assertEqual(sorted(results),['conflict','won'])
    def test_audio_is_denied_if_audit_write_fails(self):
        row=self.intake()
        with patch.object(self.store,'audit',side_effect=Unavailable('audit failed')):
            with self.assertRaises(Unavailable):self.store.audio(row['id'],('8001',),'admin','play_request')
    def test_low_disk_and_symlink_storage_fail_before_media_write(self):
        with patch('sanequeue.surveys.voice_feedback.shutil.disk_usage',return_value=type('Disk',(),{'free':1})()):
            with self.assertRaises(Unavailable):self.intake()
        if os.name!='nt':
            linked=self.root/'linked';linked.mkdir();(linked/'voice-feedback').symlink_to(self.store.directory,target_is_directory=True)
            with self.assertRaises(Unavailable):VoiceFeedback(linked).initialize()

class VoiceAPITests(unittest.TestCase):
    def setUp(self):
        VoiceTests.setUp(self);self.accounts=self.root/'local_accounts.json';self.policies=self.root/'local_queue_policies.json'
        self.account_data={name:dict(role=role,phone='',password_hash='pbkdf2:sha256:test',menus=['surveys']) for name,role in [('admin','admin'),('boss','supervisor'),('other','supervisor')]}
        self.account_data['boss']['phone']='PJSIP/300';self.account_data['other']['phone']='PJSIP/200'
        self.policy_data=dict(version=1,queues={'8001':{},'8002':{}},supervisors={'boss':dict(queues=['8001'],actions=['view','survey_reports','recording_play']),'other':dict(queues=['8002'],actions=['view','survey_reports'])})
        self.write_policy();app=Flask(__name__);app.secret_key='test';manager=LoginManager(app)
        class User(UserMixin):
            def __init__(self,ident):self.id=ident
        manager.user_loader(User);install(app,self.root);self.client=app.test_client();self.login('boss');self.headers={'X-CSRF-Token':'token','Idempotency-Key':'upload'}
    def write_policy(self):self.accounts.write_text(json.dumps(self.account_data));self.policies.write_text(json.dumps(self.policy_data))
    def login(self,user):
        with self.client.session_transaction() as session:session['_user_id']=user;session['_fresh']=True;session['csrf_token']='token'
    def upload(self,queue='8001',headers=None,data=None):return self.client.post('/api/voice-feedback?queue='+queue,data=self.audio if data is None else data,content_type='audio/wav',headers=headers or self.headers)
    def test_current_scope_and_audio_permissions_are_separate(self):
        response=self.upload();self.assertEqual(response.status_code,201,response.json);ident=response.json['feedback']['id']
        self.assertEqual(self.client.get('/api/voice-feedback/'+ident+'/audio/play').status_code,200)
        self.assertEqual(self.client.get('/api/voice-feedback/'+ident+'/audio/download').status_code,403)
        self.assertEqual(self.upload('8002').status_code,403)
        self.policy_data['supervisors']['boss']['actions'].remove('recording_play');self.write_policy()
        self.assertEqual(self.client.get('/api/voice-feedback/'+ident+'/audio/play').status_code,403)
        self.policy_data['supervisors']['boss']['queues']=[];self.write_policy()
        self.assertEqual(self.client.get('/api/voice-feedback/'+ident).status_code,404)
        self.login('other');self.assertEqual(self.client.get('/api/voice-feedback/'+ident+'/audit').status_code,404)
    def test_csrf_replay_bad_media_and_fresh_account_revocation(self):
        self.assertEqual(self.upload(headers={'Idempotency-Key':'x'}).status_code,403)
        first=self.upload();self.assertEqual(first.status_code,201)
        again=self.upload();self.assertEqual(again.status_code,200);self.assertEqual(first.json['feedback']['id'],again.json['feedback']['id'])
        self.assertEqual(self.upload(data=b'../../etc/passwd').status_code,400)
        self.assertEqual(self.upload(data=b'X'*(MAX_BYTES+1)).status_code,413)
        self.assertIn('no-store',first.headers['Cache-Control'])
        self.account_data.pop('boss');self.write_policy();self.assertEqual(self.client.get('/api/voice-feedback').status_code,403)
    def test_assignment_requires_current_same_queue_reviewer_and_cas(self):
        row=self.upload().json['feedback'];url='/api/voice-feedback/'+row['id'];body=dict(version=1,status='reviewing',assignee='other',note='note')
        self.assertEqual(self.client.post(url,json=body,headers=self.headers).status_code,400)
        body['assignee']='boss';response=self.client.post(url,json=body,headers=self.headers)
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(self.client.post(url,json=body,headers=self.headers).status_code,409)
        self.assertEqual(self.client.get(url+'/audit').json['events'][0]['action'],'review_update')
    def test_survey_association_requires_actual_same_queue_session(self):
        self.assertEqual(self.client.post('/api/voice-feedback?queue=8001&survey_session='+'a'*32,data=self.audio,content_type='audio/wav',headers=self.headers).status_code,404)
        from sanequeue.surveys.store import SurveyStore
        surveys=SurveyStore(self.root);surveys.initialize();prompts={'rating':'custom/rating'}
        form=dict(title='Rating',questions=[dict(id='q1',label='Rate',prompt='rating',options={'1':dict(label='No',next='end'),'2':dict(label='Yes',next='end')},timeout_seconds=3,attempts=1)],csat_question='q1',csat_satisfied=['2'])
        saved=surveys.save_form(form,'admin',prompts)
        binding=dict(queue='8001',form_id=saved['id'],form_version=1,prompts=prompts,enabled=True)
        evidence=dict(queue='8001',agent='Local/100@from-queue/n',caller_uniqueid='123.4',visit_proof='a'*64,source='queue_log_completeagent',binding='support',prompt_map=prompts,checked_prompt_hashes={'rating':'b'*64})
        survey=surveys.start(binding,evidence)
        response=self.client.post('/api/voice-feedback?queue=8001&survey_session='+survey['id'],data=self.audio,content_type='audio/wav',headers=self.headers)
        self.assertEqual(response.status_code,201,response.json)
        self.assertEqual(response.json['feedback']['evidence']['survey_session'],survey['id'])
        self.assertEqual(response.json['feedback']['evidence']['agent'],'Local/100@from-queue/n')
        self.assertNotIn('caller_uniqueid',response.json['feedback']['evidence'])

if __name__=='__main__':unittest.main()
