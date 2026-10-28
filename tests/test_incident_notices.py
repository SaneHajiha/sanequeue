"""Inbound notices never imply a route change or an observed playback."""
import io
import json
import tempfile
import os
from contextlib import contextmanager,ExitStack
from types import SimpleNamespace
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

    @contextmanager
    def root_sandbox(self):
        from sanequeue.pbx import root_adapter as adapter
        config=self.root/'etc';config.mkdir(exist_ok=True)
        (config/'extensions_custom.conf').write_text('; custom routes\n')
        (config/'extensions_voipiran_numberformatter.conf').write_text('[numberformatter]\nexten => s,1,Return()\n')
        (self.root/'pbx-features.json').write_text(json.dumps(validate({})))
        spool=self.root/'spool';spool.mkdir(exist_ok=True)
        (spool/'adapter-token').write_text('a'*64)
        runtime=dict(token='a'*64,settings=validate({}),phones={},directory={},incidents=snapshot(self.store,self.allowed))
        (spool/'runtime.json').write_text(json.dumps(runtime));os.chmod(spool/'runtime.json',0o600)
        mapping={'/var/lib/sanequeue':self.root,'/var/spool/asterisk/sanequeue':spool,'/etc/asterisk':config,
            '/var/lib/asterisk/sounds/custom/sanequeue':self.root/'sounds',
            '/var/backups/sanequeue/pbx-feature-originals':self.root/'backups',
            '/run/sanequeue/pbx-status.json':self.root/'run'/'status.json'}
        real_path=Path;original_read=adapter._read_root_json;owner=os.getuid()
        stream=io.BytesIO()
        with wave.open(stream,'wb') as sound:
            sound.setnchannels(1);sound.setsampwidth(2);sound.setframerate(8000);sound.writeframes(b'\0\0'*800)
        with ExitStack() as stack:
            def use(target,**kwargs):return stack.enter_context(patch.object(adapter,target,**kwargs))
            use('Path',side_effect=lambda value:mapping.get(str(value),real_path(value)))
            # Chown is mocked, so synthetic root-published fixtures retain the
            # runner UID. Production calls keep the helper's strict owner_uid=0.
            use('_read_root_json',side_effect=lambda path,**kwargs:original_read(path,**{**kwargs,'owner_uid':owner}))
            stack.enter_context(patch.object(adapter.os,'geteuid',return_value=0))
            stack.enter_context(patch.object(adapter.os,'chown'));stack.enter_context(patch.object(adapter.os,'chmod'))
            stack.enter_context(patch.object(adapter.grp,'getgrnam',return_value=SimpleNamespace(gr_gid=123)))
            stack.enter_context(patch.object(adapter.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=123,pw_gid=123)))
            use('read_snapshot',return_value={'endpoints':[]});use('bundled_prompt',return_value=(None,stream.getvalue()))
            use('incident_bindings',return_value=self.allowed)
            idle=use('require_idle')
            process=stack.enter_context(patch.object(adapter.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'ok')))
            yield SimpleNamespace(adapter=adapter,config=config,spool=spool,idle=idle,process=process)

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

    def test_disable_survives_missing_source_audio_and_never_resurrects_old_revision(self):
        enabled=self.store.save(self.notice,self.allowed,'alice')
        self.assertEqual(snapshot(self.store,self.allowed)['support']['revision'],enabled['revision'])
        source=self.store.sounds/(self.audio+'.wav');source.unlink()
        # An already published PBX copy is independent of the web source file.
        published=self.root/'root-published.wav';published.write_bytes(b'existing root-owned copy')
        with self.assertRaises(ValueError):
            self.store.save(dict(self.notice,expected_revision=enabled['revision']),self.allowed,'alice')
        disabled=self.store.save(dict(self.notice,enabled=False,expected_revision=enabled['revision']),self.allowed,'alice')
        self.assertGreater(disabled['revision'],enabled['revision'])
        self.assertFalse(self.store.current()[0]['enabled'])
        self.assertEqual(snapshot(self.store,self.allowed),{})
        self.assertTrue(published.exists())

    def test_disable_still_validates_binding_hash_and_revision(self):
        for changes in (dict(binding='unapproved'),dict(audio='../bad'),dict(expected_revision=True)):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                self.store.save(dict(self.notice,enabled=False,**changes),self.allowed,'alice')

    @unittest.skipIf(os.name=='nt','Privileged adapter is Linux-only; sandboxed Linux runner exercises this')
    def test_notice_only_root_publication_installs_audio_context_without_legacy_feature_changes(self):
        from sanequeue.pbx import root_adapter as adapter
        self.store.save(self.notice,self.allowed,'alice')
        config=self.root/'etc';config.mkdir()
        custom=config/'extensions_custom.conf';custom.write_text('; existing custom routes\n')
        macro=config/'extensions_override_issabelpbx.conf';macro.write_text('###CallWaiting And CallBack\nlegacy callback untouched\n')
        formatter=config/'extensions_voipiran_numberformatter.conf';formatter.write_text('[numberformatter]\nlegacy formatter untouched\n')
        old_macro=macro.read_bytes();old_formatter=formatter.read_bytes()
        mapped={'/var/lib/sanequeue':self.root,'/var/spool/asterisk/sanequeue':self.root/'spool',
            '/etc/asterisk':config,'/var/lib/asterisk/sounds/custom/sanequeue':self.root/'sounds',
            '/var/backups/sanequeue/pbx-feature-originals':self.root/'backups',
            '/run/sanequeue/pbx-status.json':self.root/'run'/'status.json'}
        real_path=Path
        def path(value):return mapped.get(str(value),real_path(value))
        audio=self.store.audio(self.audio)[1]
        with patch.object(adapter,'Path',side_effect=path),patch.object(adapter.os,'geteuid',return_value=0),\
             patch.object(adapter.os,'chown'),patch.object(adapter.os,'chmod'),\
             patch.object(adapter.grp,'getgrnam',return_value=SimpleNamespace(gr_gid=123)),\
             patch.object(adapter.pwd,'getpwnam',return_value=SimpleNamespace(pw_uid=123,pw_gid=123)),\
             patch.object(adapter,'read_snapshot',return_value={'endpoints':[]}),\
             patch.object(adapter,'bundled_prompt',return_value=(None,audio)),\
             patch.object(adapter,'incident_bindings',return_value=self.allowed),\
             patch.object(adapter,'require_idle') as idle,\
             patch.object(adapter,'patch_macro',side_effect=AssertionError('notice-only changed callback')),\
             patch.object(adapter.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'ok')):
            status=adapter.apply()
        self.assertTrue(status['applied']);idle.assert_called_once()
        self.assertIn('[sanequeue-inbound-notice]',(config/'sanequeue-features.conf').read_text())
        self.assertIn('#include sanequeue-features.conf',custom.read_text())
        self.assertEqual((self.root/'sounds'/(self.audio+'.wav')).read_bytes(),audio)
        self.assertEqual(macro.read_bytes(),old_macro);self.assertEqual(formatter.read_bytes(),old_formatter)
        self.assertFalse((self.root/'pbx-features.json').exists())
        runtime=json.loads((self.root/'spool'/'runtime.json').read_text())
        self.assertEqual(runtime['incidents']['support']['audio'],self.audio)
        manifest=json.loads((self.root/'backups'/'manifest.json').read_text())
        self.assertNotIn(macro.name,manifest);self.assertNotIn(formatter.name,manifest)

    @unittest.skipIf(os.name=='nt','Linux privileged adapter sandbox')
    def test_emergency_disable_is_asserted_before_bad_settings_and_cleared_only_after_success(self):
        with self.root_sandbox() as env:
            (self.root/'module.disabled').touch()
            settings=self.root/'pbx-features.json';settings.write_text('bad json')
            self.assertEqual(env.adapter.apply()['state'],'disabled')
            self.assertTrue((env.spool/'disabled').exists())
            (self.root/'module.disabled').unlink()
            with self.assertRaises(ValueError):env.adapter.apply()
            self.assertTrue((env.spool/'disabled').exists())
            settings.write_text(json.dumps(validate({})));env.adapter.apply()
            self.assertFalse((env.spool/'disabled').exists())

    @unittest.skipIf(os.name=='nt','Linux privileged adapter sandbox')
    def test_notice_disable_withdraws_before_unrelated_bad_formatter(self):
        enabled=self.store.save(self.notice,self.allowed,'alice')
        with self.root_sandbox() as env:
            self.store.save(dict(self.notice,enabled=False,expected_revision=enabled['revision']),self.allowed,'alice')
            (env.config/'extensions_voipiran_numberformatter.conf').write_text('[unsupported]\n')
            with self.assertRaisesRegex(ValueError,'unsupported_formatter_adapter'):env.adapter.apply()
            self.assertEqual(json.loads((env.spool/'runtime.json').read_text())['incidents'],{})
            status=json.loads((self.root/'run'/'status.json').read_text())
            self.assertEqual(status['notice_withdrawn'],1);self.assertEqual(status['notice_snapshot']['disabled'],1)

    @unittest.skipIf(os.name=='nt','Linux privileged adapter sandbox')
    def test_active_calls_block_new_activation_but_not_disabled_notice_withdrawal(self):
        enabled=self.store.save(self.notice,self.allowed,'alice')
        with self.root_sandbox() as env:
            self.store.save(dict(self.notice,enabled=False,expected_revision=enabled['revision']),self.allowed,'alice')
            self.allowed['new']=dict(context='from-other',queue='8002',label='Other')
            self.store.save(dict(self.notice,binding='new'),self.allowed,'alice')
            env.idle.side_effect=ValueError('active_calls_defer_dialplan_change')
            with self.assertRaisesRegex(ValueError,'active_calls_defer'):env.adapter.apply()
            self.assertEqual(json.loads((env.spool/'runtime.json').read_text())['incidents'],{})

    @unittest.skipIf(os.name=='nt','Linux privileged adapter sandbox')
    def test_bad_optional_notice_store_withdraws_with_visible_diagnostic(self):
        self.store.save(self.notice,self.allowed,'alice')
        with self.root_sandbox() as env:
            self.store.path.write_bytes(b'not sqlite')
            (self.root/'pbx-features.json').write_text('bad json')
            with self.assertRaises(ValueError):env.adapter.apply()
            self.assertEqual(json.loads((env.spool/'runtime.json').read_text())['incidents'],{})
            status=json.loads((self.root/'run'/'status.json').read_text())
            self.assertEqual(status['notice_snapshot']['state'],'unavailable')
            self.assertEqual(status['notice_snapshot']['error_codes'],['notice_store_unavailable'])

    @unittest.skipIf(os.name=='nt','Linux privileged adapter sandbox')
    def test_failed_install_rollback_cannot_restore_withdrawn_notice_or_clear_disable(self):
        enabled=self.store.save(self.notice,self.allowed,'alice')
        with self.root_sandbox() as env:
            self.store.save(dict(self.notice,enabled=False,expected_revision=enabled['revision']),self.allowed,'alice')
            (env.spool/'disabled').touch()
            env.process.return_value=SimpleNamespace(returncode=1,stdout=b'reload failed')
            with self.assertRaisesRegex(RuntimeError,'dialplan_reload_failed'):env.adapter.apply()
            self.assertEqual(json.loads((env.spool/'runtime.json').read_text())['incidents'],{})
            self.assertTrue((env.spool/'disabled').exists())

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
        audio=(self.store.sounds/(self.audio+'.wav')).read_bytes()
        with patch('sanequeue.pbx.features.convert_audio',return_value=(audio,.1)),patch('sanequeue.pbx.incidents.os.link',side_effect=OSError('disk failure')):
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


class IncidentDeploymentSafetyTests(unittest.TestCase):
    """Always-run safety contracts, independent of successful PBX installation."""
    setUp=IncidentTests.setUp
    root_sandbox=IncidentTests.root_sandbox

    def test_apply_unit_does_not_gate_the_disable_propagation_path(self):
        unit=Path(__file__).resolve().parents[1]/'deploy'/'sanequeue-pbx-apply.service'
        lines=[line.strip() for line in unit.read_text(encoding='utf-8').splitlines()
               if line.strip() and not line.lstrip().startswith('#')]
        self.assertTrue(any(line.startswith('ExecStart=') and 'sanequeue.pbx.root_adapter' in line for line in lines))
        self.assertEqual([line for line in lines if line.startswith('Condition') and 'module.disabled' in line],[])

    @unittest.skipIf(os.name=='nt','Linux privileged adapter sandbox')
    def test_global_disable_has_no_feature_audio_inventory_or_pbx_dependency(self):
        with self.root_sandbox() as env:
            (self.root/'module.disabled').touch()
            (self.root/'pbx-features.json').write_text('malformed settings')
            with patch.object(env.adapter.FeatureStore,'read',side_effect=AssertionError('disable read settings')) as settings,\
                 patch.object(env.adapter,'bundled_prompt',side_effect=AssertionError('disable read bundled audio')) as bundled,\
                 patch.object(env.adapter,'read_snapshot',side_effect=AssertionError('disable read inventory')) as inventory:
                result=env.adapter.apply()
                self.assertEqual(result['state'],'disabled')
                settings.assert_not_called();bundled.assert_not_called();inventory.assert_not_called()
            self.assertTrue((env.spool/'disabled').is_file())
            env.idle.assert_not_called();env.process.assert_not_called()


if __name__=='__main__':unittest.main()
