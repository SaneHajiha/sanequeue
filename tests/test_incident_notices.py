"""Inbound notices never imply a route change or an observed playback."""
import io
import json
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from flask import Flask
from flask_login import LoginManager, UserMixin
from sanequeue.pbx.incidents import IncidentStore, bindings, dialplan, select_notice, snapshot, validate_notice
from sanequeue.pbx.features import install, validate
from sanequeue.pbx.agi import dispatch


class IncidentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name);self.store = IncidentStore(self.root)
        self.allowed = {'support': dict(context='from-test', queue='8001', label='Support')}
        stream = io.BytesIO()
        with wave.open(stream, 'wb') as sound:
            sound.setnchannels(1);sound.setsampwidth(2);sound.setframerate(8000);sound.writeframes(b'\0\0' * 800)
        with patch('sanequeue.pbx.features.convert_audio', return_value=(stream.getvalue(), .1)):
            self.audio = self.store.upload(b'uploaded')['audio']
        self.notice = dict(binding='support', enabled=True, title='Incident', audio=self.audio, starts_at=100, expires_at=200, expected_revision=0)

    def test_unknown_scope_and_injected_identifiers_are_rejected(self):
        for binding in ['*', '8001\nHangup()', 'missing', '../support']:
            with self.subTest(binding=binding),self.assertRaises(ValueError):validate_notice(dict(self.notice,binding=binding),self.allowed)

    def test_times_and_enabled_are_strict(self):
        for changes in [dict(enabled='true'),dict(starts_at=True),dict(expires_at=float('inf')),dict(expires_at=float('nan')),dict(expires_at=100),dict(expires_at=100+7*86400+1),dict(title='a\nb'),dict(audio='../file')]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):validate_notice(dict(self.notice,**changes),self.allowed)

    def test_append_only_versions_and_stale_editor_conflict(self):
        one = self.store.save(self.notice,self.allowed,'alice')
        with self.assertRaisesRegex(ValueError,'notice_changed_reload'):self.store.save(self.notice,self.allowed,'bob')
        two = self.store.save(dict(self.notice,expected_revision=one['revision'],enabled=False),self.allowed,'bob')
        self.assertGreater(two['revision'],one['revision']);self.assertEqual(self.store.current()[0]['actor'],'bob')
        with self.store.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM notices').fetchone()[0],2)

    def test_audio_must_exist_and_match_hash(self):
        with self.assertRaises(ValueError):self.store.save(dict(self.notice,audio='f'*64),self.allowed,'alice')
        (self.store.sounds/(self.audio+'.wav')).write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError,'hash'):self.store.save(self.notice,self.allowed,'alice')

    def test_snapshot_drops_removed_binding(self):
        self.store.save(self.notice,self.allowed,'alice')
        self.assertEqual(snapshot(self.store,{}),{})

    def test_privileged_snapshot_never_initializes_missing_db(self):
        missing=IncidentStore(self.root/'not-created')
        self.assertEqual(snapshot(missing,self.allowed),{})
        self.assertFalse(missing.path.exists())

    def test_snapshot_fails_open_for_corrupt_store(self):
        self.store.path.write_bytes(b'not sqlite')
        self.assertEqual(snapshot(self.store,self.allowed),{})

    def test_registry_removal_hides_previous_setting_without_deleting_history(self):
        self.store.save(self.notice,self.allowed,'alice')
        self.assertEqual(self.store.current(allowed={}),[])
        self.assertEqual(len(self.store.current(allowed=self.allowed)),1)

    def test_interrupted_audio_publication_never_leaves_partial_wav(self):
        other=IncidentStore(self.root/'other')
        with patch('sanequeue.pbx.features.convert_audio',return_value=(b'new audio',1)),patch('sanequeue.pbx.incidents.os.link',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):other.upload(b'upload')
        self.assertEqual(list(other.sounds.iterdir()),[])

    def runtime(self):
        self.store.save(self.notice,self.allowed,'alice')
        return dict(token='a'*64, settings=validate({}), incidents=snapshot(self.store,self.allowed))

    def test_exact_scope_and_expiry_are_checked_at_each_call(self):
        cfg=self.runtime()
        self.assertIsNotNone(select_notice(cfg,'support','from-test','8001',100))
        for binding,context,queue,now in [('support','from-test','8001',99),('support','from-test','8001',200),('support','from-other','8001',150),('support','from-test','8002',150),('missing','from-test','8001',150)]:
            self.assertIsNone(select_notice(cfg,binding,context,queue,now))

    def test_agi_token_disable_and_returned_path_are_bounded(self):
        cfg=self.runtime();env=dict(agi_network_script='a'*64+'/incident',agi_arg_1='support',agi_arg_2='from-test',agi_arg_3='8001')
        result=dispatch(env,cfg,self.root,now=150)
        self.assertEqual(result['SQ_NOTICE_AUDIO'],'custom/sanequeue/'+self.audio)
        self.assertEqual(result['SQ_NOTICE_ENABLED'],'1')
        self.assertEqual(dispatch(dict(env,agi_arg_3='8002'),cfg,self.root,now=150),{'SQ_NOTICE_ENABLED':'0'})
        self.assertEqual(dispatch(dict(env,agi_network_script='b'*64+'/incident'),cfg,self.root,now=150),{})
        (self.root/'disabled').touch();self.assertEqual(dispatch(env,cfg,self.root,now=150),{})

    def test_render_is_subroutine_only_and_clears_stale_variables(self):
        text=dialplan('a'*64)
        self.assertIn('Set(SQ_NOTICE_ENABLED=0)',text);self.assertIn('Set(SQ_NOTICE_AUDIO=)',text)
        self.assertIn('Return()',text);self.assertIn('TryExec(Playback(${SQ_NOTICE_AUDIO},noanswer))',text)
        for command in ['Hangup(', 'Dial(', 'Answer(', '#include', '[from-test]']:self.assertNotIn(command,text)
        with self.assertRaises(ValueError):dialplan('bad\nHangup()')

    def test_registry_missing_malformed_and_nonfile_fail_closed(self):
        path=self.root/'bindings.json';self.assertEqual(bindings(path,require_root=False),{})
        path.write_text(json.dumps(self.allowed));self.assertEqual(bindings(path,require_root=False),self.allowed)
        path.write_text(json.dumps({'*':dict(context='bad\nDial',queue='8001')}));self.assertEqual(bindings(path,require_root=False),{})
        path.write_text('not json');self.assertEqual(bindings(path,require_root=False),{})
        self.assertEqual(bindings(self.root,require_root=False),{})

    def test_api_requires_admin_menu_and_csrf_and_does_not_apply_routes(self):
        app=Flask(__name__);app.secret_key='test';login=LoginManager(app)
        class User(UserMixin):id='owner'
        login.user_loader(lambda ident:User());role=['admin'];menus=[{'telephony'}]
        app.config['SANEQUEUE_MENU_PROVIDER']=lambda ident, role:menus[0]
        install(app,self.root,lambda:role[0]);client=app.test_client()
        self.assertEqual(client.get('/api/pbx/incidents').status_code,401)
        with client.session_transaction() as session:
            session['_user_id']='owner';session['_fresh']=True;session['csrf_token']='token'
        with patch('sanequeue.pbx.incidents.bindings',return_value=self.allowed):
            response=client.get('/api/pbx/incidents');self.assertEqual(response.status_code,200)
            self.assertEqual(response.json['integration'],'explicit_dialplan_hook_required')
            self.assertEqual(client.post('/api/pbx/incidents',json=self.notice).status_code,403)
            response=client.post('/api/pbx/incidents',json=self.notice,headers={'X-CSRF-Token':'token'})
            self.assertEqual(response.status_code,200)
            self.assertEqual(client.post('/api/pbx/incidents',json=self.notice,headers={'X-CSRF-Token':'token'}).status_code,409)
            menus[0]=set();self.assertEqual(client.get('/api/pbx/incidents').status_code,403)
            menus[0]={'telephony'};role[0]='supervisor';self.assertEqual(client.get('/api/pbx/incidents').status_code,403)
        self.assertFalse((self.root/'runtime.json').exists())

    def test_api_refuses_upload_without_operator_binding(self):
        app=Flask(__name__);app.secret_key='test';login=LoginManager(app)
        class User(UserMixin):id='owner'
        login.user_loader(lambda ident:User());install(app,self.root,lambda:'admin');client=app.test_client()
        with client.session_transaction() as session:
            session['_user_id']='owner';session['_fresh']=True;session['csrf_token']='token'
        with patch('sanequeue.pbx.incidents.bindings',return_value={}):
            response=client.post('/api/pbx/incidents/audio',data={'audio':(io.BytesIO(b'bad'),'x.wav')},headers={'X-CSRF-Token':'token'})
        self.assertEqual(response.status_code,409)


if __name__=='__main__':unittest.main()
