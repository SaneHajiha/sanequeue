"""Real isolated survey store/API/AGI flow, without dialing or modifying PBX."""
import asyncio
import copy
import hashlib
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
from sanequeue.surveys.store import SurveyStore,validate_form
from sanequeue.surveys.adapter import QueueEvidence,Runtime,Server,configuration,dialplan,verify_prompts
from sanequeue.surveys.api import install,access


class SurveysTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.store=SurveyStore(self.root);self.store.initialize();self.prompts={'rating':'custom/rating','followup':'custom/followup'}
        self.form=dict(title='Customer service',questions=[dict(id='q1',label='Rate service',prompt='rating',options={str(d):dict(label=str(d),next='end') for d in range(1,6)},timeout_seconds=5,attempts=2)],csat_question='q1',csat_satisfied=['4','5'])
        self.version=self.store.save_form(self.form,'owner',self.prompts)
        self.binding=dict(queue='8001',form_id=self.version['id'],form_version=1,prompts=self.prompts,enabled=True)
        self.evidence=dict(queue='8001',agent='Local/100@from-queue/n',caller_uniqueid='1793010000.1',visit_proof='a'*64,source='queue_log_completeagent',binding='support',prompt_map=self.prompts,checked_prompt_hashes={key:'b'*64 for key in self.prompts})
        self.soundroot=self.root/'sounds';(self.soundroot/'custom').mkdir(parents=True)
        stream=io.BytesIO()
        with wave.open(stream,'wb') as sound:sound.setnchannels(1);sound.setsampwidth(2);sound.setframerate(8000);sound.writeframes(b'\0\0'*800)
        self.audio=stream.getvalue()
        for filename in self.prompts.values():(self.soundroot/(filename+'.wav')).write_bytes(self.audio)
        self.config=dict(token='c'*64,bindings={'support':self.binding})

    def start(self,**kwargs):return self.store.start(self.binding,self.evidence,**kwargs)
    def answer(self,row,value,**kwargs):return self.store.answer(row['id'],row['sequence'],value,caller_uniqueid=self.evidence['caller_uniqueid'],**kwargs)

    def branching(self):
        form=copy.deepcopy(self.form);form['questions'][0]['options']['1']['next']='q2'
        form['questions'].append(dict(id='q2',label='Follow up',prompt='followup',options={'1':dict(label='Yes',next='end'),'2':dict(label='No',next='end')},timeout_seconds=3,attempts=1))
        return form

    def test_form_rejects_cycles_unknown_sound_invalid_digit_and_unreachable_question(self):
        for change in ('cycle','sound','digit','orphan'):
            form=self.branching()
            if change=='cycle':form['questions'][1]['options']['1']['next']='q1'
            if change=='sound':form['questions'][0]['prompt']='https://attacker'
            if change=='digit':form['questions'][0]['options']['*']={'label':'bad','next':'end'}
            if change=='orphan':form['questions'][0]['options']['1']['next']='end'
            with self.subTest(change=change),self.assertRaises(ValueError):validate_form(form,self.prompts)

    def test_immutable_versions_and_pinned_live_session(self):
        row=self.start();changed=dict(self.form,id=self.version['id'],expected_version=1,title='New title')
        self.store.save_form(changed,'owner',self.prompts)
        with self.assertRaises(ValueError):self.store.save_form(changed,'owner',self.prompts)
        detail=self.store.detail(row['id'],['8001']);self.assertEqual(detail['form']['title'],'Customer service');self.assertEqual(self.store.forms()[0]['version'],2)

    def test_answer_replay_idempotency_and_conflict(self):
        row=self.start();first=self.answer(row,'5');self.assertEqual(first['state'],'completed')
        self.assertEqual(self.answer(row,'5'),first)
        with self.assertRaisesRegex(ValueError,'replay_conflict'):self.answer(row,'1')
        now=time.time();self.assertEqual(self.store.report(['8001'],now-100,now+100)['summary']['csat_denominator'],1)

    def test_same_visit_single_session_and_multi_queue_visits_are_distinct(self):
        first=self.start();self.assertEqual(first['id'],self.start()['id'])
        second_evidence=dict(self.evidence,queue='8002',visit_proof='d'*64)
        second=self.store.start(dict(self.binding,queue='8002'),second_evidence)
        self.assertNotEqual(first['id'],second['id']);self.assertEqual(second['queue'],'8002')
        self.assertEqual(self.store.detail(first['id'],['8001'])['agent'],'Local/100@from-queue/n')
        with self.assertRaises(PermissionError):self.store.detail(second['id'],['8001'])

    def test_invalid_digit_no_response_and_hangup_are_not_answers(self):
        row=self.start();row=self.answer(row,'9');self.assertEqual(row['state'],'active')
        row=self.answer(row,'timeout');self.assertEqual(row['state'],'no_response')
        detail=self.store.detail(row['id'],['8001']);self.assertFalse(any(a['accepted'] for a in detail['answers']))
        other=dict(self.evidence,visit_proof='e'*64);row=self.store.start(self.binding,other)
        row=self.answer(row,'hangup');self.assertEqual(row['state'],'abandoned')

    def test_partial_and_csat_denominator_remain_explicit(self):
        version=self.store.save_form(dict(self.branching(),id=self.version['id'],expected_version=1),'owner',self.prompts)
        self.binding['form_version']=version['version'];row=self.start();row=self.answer(row,'1');self.assertEqual(row['question']['id'],'q2');row=self.answer(row,'hangup');self.assertEqual(row['state'],'partial')
        now=time.time();summary=self.store.report(['8001'],now-100,now+100)['summary']
        self.assertEqual((summary['offered'],summary['csat_numerator'],summary['csat_denominator']),(1,0,1));self.assertEqual(summary['csat_percent'],0)

    def test_decline_expiry_owner_and_sequence_guards(self):
        row=self.start()
        with self.assertRaises(PermissionError):self.store.answer(row['id'],0,'5',caller_uniqueid='different')
        with self.assertRaises(ValueError):self.store.answer(row['id'],1,'5',caller_uniqueid=self.evidence['caller_uniqueid'])
        self.assertEqual(self.answer(row,'*')['state'],'declined')
        row=self.store.start(self.binding,dict(self.evidence,visit_proof='f'*64),now=100)
        self.assertEqual(self.answer(row,'5',now=401)['state'],'expired')

    def log(self,event='COMPLETEAGENT',queue='8001',agent='Local/100@from-queue/n'):
        now=int(time.time());caller=self.evidence['caller_uniqueid'];return '\n'.join([f'{now-20}|{caller}|{queue}|NONE|ENTERQUEUE||200|1',f'{now-15}|{caller}|{queue}|{agent}|CONNECT|5|peer.1',f'{now}|{caller}|{queue}|{agent}|{event}|5|15|1'])+'\n'

    def test_queue_log_proves_agent_release_not_caller_transfer_or_other_queue(self):
        path=self.root/'queue_log'
        for event in ['COMPLETEAGENT','COMPLETECALLER','TRANSFER','ATTENDEDTRANSFER']:
            path.write_text(self.log(event));source=QueueEvidence(path)
            proof=source.prove(self.evidence['caller_uniqueid'],'8001',time.time())
            self.assertEqual(bool(proof),event=='COMPLETEAGENT')
            self.assertIsNone(source.prove(self.evidence['caller_uniqueid'],'8002',time.time()))
        path.write_text(self.log().splitlines()[-1]+'\n');self.assertIsNone(QueueEvidence(path).prove(self.evidence['caller_uniqueid'],'8001',time.time()))

    def test_log_visit_reentry_does_not_reuse_previous_agent_proof(self):
        path=self.root/'queue_log';path.write_text(self.log()+f'{int(time.time())}|{self.evidence["caller_uniqueid"]}|8001|NONE|ENTERQUEUE||200|1\n')
        self.assertIsNone(QueueEvidence(path).prove(self.evidence['caller_uniqueid'],'8001',time.time()))

    def test_incremental_tail_sees_immediate_append_but_not_partial_event(self):
        path=self.root/'queue_log';lines=self.log().splitlines(keepends=True)
        path.write_text(''.join(lines[:2]));source=QueueEvidence(path);caller=self.evidence['caller_uniqueid']
        self.assertIsNone(source.prove(caller,'8001',time.time()))
        with path.open('a') as stream:stream.write(lines[-1].rstrip('\n'))
        self.assertIsNone(source.prove(caller,'8001',time.time()))
        with path.open('a') as stream:stream.write('\n')
        self.assertIsNotNone(source.prove(caller,'8001',time.time()))
        path.write_text('')
        self.assertIsNone(source.prove(caller,'8001',time.time()))

    def test_later_transfer_complete_or_second_connect_invalidates_ambiguous_proof(self):
        path=self.root/'queue_log';caller=self.evidence['caller_uniqueid'];now=int(time.time())
        for event,agent in [('TRANSFER','Local/100@from-queue/n'),('COMPLETECALLER','Local/100@from-queue/n'),('COMPLETEAGENT','PJSIP/300'),('CONNECT','Local/100@from-queue/n')]:
            with self.subTest(event=event,agent=agent):
                path.write_text(self.log()+f'{now}|{caller}|8001|{agent}|{event}|data\n')
                self.assertIsNone(QueueEvidence(path).prove(caller,'8001',time.time()))
    def test_prompt_reader_rejects_truncated_pcm_and_unsafe_root_config(self):
        verify_prompts(self.binding,self.soundroot)
        (self.soundroot/'custom/rating.wav').write_bytes(self.audio[:-20])
        with self.assertRaises(ValueError):verify_prompts(self.binding,self.soundroot)
        path=self.root/'config.json';path.write_text(json.dumps(self.config));os.chmod(path,0o600)
        self.assertIsNotNone(configuration(path,owner_uid=os.getuid() if hasattr(os,'getuid') else 0))
        bad=copy.deepcopy(self.config);bad['bindings']['support']['prompts']['rating']='https://remote';path.write_text(json.dumps(bad));self.assertIsNone(configuration(path))

    def runtime(self):
        path=self.root/'queue_log';path.write_text(self.log());(self.root/'surveys.enabled').touch()
        return Runtime(self.root,self.root/'survey-bindings.json',evidence=QueueEvidence(path),sounds=self.soundroot)
    def test_emergency_disable_and_opt_in_marker_are_checked_each_request(self):
        runtime=self.runtime();env={'agi_network_script':'c'*64+'/start','agi_arg_1':'support','agi_uniqueid':self.evidence['caller_uniqueid']}
        with patch('sanequeue.surveys.adapter.configuration',return_value=self.config) as config:
            self.assertEqual(runtime.dispatch(env)['SQ_SURVEY_READY'],'1')
            runtime.enabled_marker.unlink();config.reset_mock()
            self.assertEqual(runtime.dispatch(env),{});config.assert_not_called()
            runtime.enabled_marker.touch();(self.root/'module.disabled').touch()
            self.assertEqual(runtime.dispatch(env),{});config.assert_not_called()
            (self.root/'module.disabled').unlink()
            self.assertEqual(runtime.dispatch(env)['SQ_SURVEY_READY'],'1')
    def test_real_runtime_start_answer_freezes_attribution_and_prompt_hash(self):
        runtime=self.runtime();env={'agi_network_script':'c'*64+'/start','agi_arg_1':'support','agi_uniqueid':self.evidence['caller_uniqueid']}
        with patch('sanequeue.surveys.adapter.configuration',return_value=self.config):
            first=runtime.dispatch(env);self.assertEqual(first['SQ_SURVEY_READY'],'1');self.assertEqual(first['SQ_SURVEY_AUDIO'],'custom/rating')
            result=runtime.dispatch(dict(env,agi_network_script='c'*64+'/answer',agi_arg_1=first['SQ_SURVEY_ID'],agi_arg_2='0',agi_arg_3='5'))
            self.assertEqual(result['SQ_SURVEY_STATE'],'completed')
            self.assertEqual(runtime.dispatch(dict(env,agi_network_script='b'*64+'/start')),{})

    def test_opt_in_adapter_cannot_route_dial_originate_or_answer_new_call(self):
        text=dialplan('c'*64)
        for forbidden in ['Dial(', 'Originate(', 'Answer(', 'Hangup(', '#include','[from-internal]']:self.assertNotIn(forbidden,text)
        self.assertIn('Return()',text);self.assertIn('SQ_SURVEY_STEPS}<10',text)
        with self.assertRaises(ValueError):dialplan('bad\nExec')

    def test_real_fastagi_protocol_without_ami_or_web_requests(self):
        runtime=self.runtime()
        async def run():
            server=await asyncio.start_server(Server(runtime).handle,'127.0.0.1',0)
            try:
                reader,writer=await asyncio.open_connection('127.0.0.1',server.sockets[0].getsockname()[1]);writer.write(('agi_network_script: '+'c'*64+'/start\nagi_arg_1: support\nagi_uniqueid: '+self.evidence['caller_uniqueid']+'\n\n').encode());await writer.drain();lines=[]
                while True:
                    line=await asyncio.wait_for(reader.readline(),3)
                    if not line:break
                    lines.append(line);writer.write(b'200 result=1\n');await writer.drain()
                writer.close();await writer.wait_closed();self.assertTrue(any(b'SQ_SURVEY_READY "1"' in line for line in lines));self.assertTrue(any(b'custom/rating' in line for line in lines))
            finally:server.close();await server.wait_closed()
        with patch('sanequeue.surveys.adapter.configuration',return_value=self.config):asyncio.run(run())

    def test_prompt_replacement_or_binding_withdrawal_stops_subsequent_question(self):
        version=self.store.save_form(dict(self.branching(),id=self.version['id'],expected_version=1),'owner',self.prompts);self.binding['form_version']=version['version']
        runtime=self.runtime();env={'agi_network_script':'c'*64+'/start','agi_arg_1':'support','agi_uniqueid':self.evidence['caller_uniqueid']}
        with patch('sanequeue.surveys.adapter.configuration',return_value=self.config):
            first=runtime.dispatch(env)
            self.binding['enabled']=False
            result=runtime.dispatch(dict(env,agi_network_script='c'*64+'/answer',agi_arg_1=first['SQ_SURVEY_ID'],agi_arg_2='0',agi_arg_3='1'))
            self.assertEqual(result,{})
            # The valid answer already supplied to the old question remains evidence.
            detail=self.store.detail(first['SQ_SURVEY_ID'],['8001']);self.assertTrue(detail['answers'][0]['accepted'])

    def account_files(self):
        accounts=self.root/'local_accounts.json';policies=self.root/'local_queue_policies.json'
        accounts.write_text(json.dumps({'owner':dict(role='admin',phone='',password_hash='pbkdf2:sha256:test',menus=['surveys']),'boss':dict(role='supervisor',phone='PJSIP/300',password_hash='pbkdf2:sha256:test',menus=['surveys'])}))
        policies.write_text(json.dumps(dict(version=1,queues={'8001':{},'8002':{}},supervisors={'boss':dict(queues=['8001'],actions=['view','survey_reports'])})))
        return accounts,policies
    def test_api_scopes_csrf_current_role_and_no_phone_data(self):
        accounts,policies=self.account_files();app=Flask(__name__);app.secret_key='test';login=LoginManager(app)
        class User(UserMixin):
            def __init__(self,ident):self.id=ident
        login.user_loader(User);install(app,self.root);client=app.test_client()
        row=self.start();self.answer(row,'5')
        with client.session_transaction() as session:session['_user_id']='boss';session['_fresh']=True;session['csrf_token']='test'
        with patch('sanequeue.surveys.api.configuration',return_value=self.config):
            response=client.get('/api/surveys/forms');self.assertEqual(response.status_code,200);self.assertEqual(response.json['forms'],[]);self.assertEqual(response.json['queues'],['8001']);self.assertNotIn('token',response.json)
            self.assertEqual(client.get('/api/surveys/report?queue=8002').status_code,403)
            self.assertEqual(client.post('/api/surveys/forms',json={}).status_code,403)
            detail=client.get('/api/surveys/sessions/'+row['id']);self.assertEqual(detail.status_code,200);self.assertNotIn('caller_number',detail.json['evidence'])
            accounts.write_text('{}');self.assertEqual(client.get('/api/surveys/forms').status_code,403)

    def test_admin_management_csrf_and_supervisor_revocation(self):
        accounts,policies=self.account_files();app=Flask(__name__);app.secret_key='test';login=LoginManager(app)
        class User(UserMixin):
            def __init__(self,ident):self.id=ident
        login.user_loader(User);install(app,self.root);client=app.test_client()
        with client.session_transaction() as session:session['_user_id']='owner';session['_fresh']=True;session['csrf_token']='test'
        body=dict(binding='support',form=dict(self.form,expected_version=1))
        with patch('sanequeue.surveys.api.configuration',return_value=self.config):
            self.assertEqual(client.post('/api/surveys/forms',json=body).status_code,403)
            response=client.post('/api/surveys/forms',json=body,headers={'X-CSRF-Token':'test'});self.assertEqual(response.status_code,200);self.assertEqual(response.json['forms'][0]['version'],2)
            with client.session_transaction() as session:session['_user_id']='boss'
            raw=json.loads(policies.read_text());raw['supervisors']['boss']['actions']=['view'];policies.write_text(json.dumps(raw))
            self.assertEqual(client.get('/api/surveys/report?queue=8001').status_code,403)


if __name__=='__main__':unittest.main()
