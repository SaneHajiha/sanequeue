"""Typed number rules, private prompts, AGI authorization and bounded callbacks."""
import asyncio,io,json,os,tempfile,unittest,wave
from pathlib import Path
from flask import Flask
from flask_login import LoginManager,UserMixin
from sanequeue.pbx.features import bundled_prompt,validate,normalize_number,FeatureStore,convert_audio,install
from sanequeue.pbx.agi import dispatch,FastAGI

class FeaturesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.config=validate({})
    def test_standard_number_rules_keep_foreign_and_private_numbers(self):
        cfg=self.config['caller_id']
        samples={'+989121234567':'09121234567','00989121234567':'09121234567','989121234567':'09121234567','9121234567':'09121234567','2123456789':'02123456789','09121234567':'09121234567','100':'100','anonymous':'anonymous','+442012345678':'+442012345678','00442012345678':'00442012345678','23456789':'23456789'}
        for value,expected in samples.items():
            with self.subTest(value=value):self.assertEqual(normalize_number(value,cfg),expected)
        cfg['expand_local']=True;self.assertEqual(normalize_number('23456789',cfg),'02123456789')
    def test_iran_provider_anomalies_are_explicit(self):
        cfg=self.config['caller_id'];cfg['provider_prefixes']=True
        samples={'0000989121234567':'09121234567','0021989121234567':'09121234567','2109121234567':'09121234567','219121234567':'09121234567','210989121234567':'09121234567','0989121234567':'09121234567','234567':'0234567','023456':'023456'}
        for value,expected in samples.items():
            with self.subTest(value=value):self.assertEqual(normalize_number(value,cfg),expected)
    def test_typed_config_rejects_shell_and_truthy_strings(self):
        for value in ({'callback':{'enabled':'false'}},{'caller_id':{'country_code':'98\nEXEC'}},{'audio':{'menu':'../../file'}},{'callback':{'retry_seconds':True}},{'callback':{'expiry_seconds':999999}}):
            with self.subTest(value=value),self.assertRaises(ValueError):validate(value)
    def runtime(self):
        return dict(token='a'*64,settings=self.config,phones={'PJSIP/100':'100','SIP/200':'200'},directory={'8001':{'09121234567':'Contact'}})
    def test_agi_token_scope_and_deduplicated_internal_jobs(self):
        self.config['callback']['enabled']=True;cfg=self.runtime()
        env={'agi_network_script':'a'*64+'/enqueue','agi_channel':'PJSIP/100-000abc','agi_arg_1':'200'}
        self.assertEqual(dispatch(env,cfg,self.root,now=100)['SQ_JOB_ACCEPTED'],'1')
        self.assertEqual(dispatch(env,cfg,self.root,now=101)['SQ_JOB_ACCEPTED'],'1');self.assertEqual(len(list(self.root.glob('job-*.json'))),1)
        for change in ({'agi_arg_1':'09121234567'},{'agi_channel':'SIP/trunk-000abc'},{'agi_network_script':'b'*64+'/enqueue'}):
            result=dispatch(dict(env,**change),cfg,self.root,now=102);self.assertNotEqual(result.get('SQ_JOB_ACCEPTED'),'1')
        (self.root/'disabled').touch();self.assertEqual(dispatch(env,cfg,self.root),{})
    def test_directory_lookup_is_queue_scoped(self):
        cfg=self.runtime();env={'agi_network_script':'a'*64+'/name','agi_callerid':'09121234567','agi_arg_1':'8001'}
        self.assertEqual(dispatch(env,cfg,self.root)['SQ_CONTACT_NAME'],'Contact')
        self.assertEqual(dispatch(dict(env,agi_arg_1='8002'),cfg,self.root)['SQ_CONTACT_FOUND'],'0')
    def test_bundled_prompt_integrity_and_telephone_format(self):
        path,content=bundled_prompt();self.assertEqual(len(content),240156)
        with wave.open(str(path),'rb') as sound:self.assertEqual(sound.getframerate(),8000);self.assertAlmostEqual(sound.getnframes()/8000,14.838625)
    def test_callback_phone_name_is_not_lost_to_internal_caller_lookup(self):
        cfg=self.runtime();env={'agi_network_script':'a'*64+'/name','agi_callerid':'300','agi_arg_2':'1'}
        cfg['phones']['PJSIP/300']='300';self.assertEqual(dispatch(env,cfg,self.root)['SQ_CONTACT_NAME'],'Callback 300')
        env['agi_callerid']='09121234567';self.assertEqual(dispatch(env,cfg,self.root)['SQ_CONTACT_FOUND'],'0')
    def test_originate_response_survives_collector_action_prefix_filter(self):
        from sanequeue.realtime.protocol import AsyncAMI
        class Writer:
            def close(self):pass
        async def run():
            reader=asyncio.StreamReader();seen=[];client=AsyncAMI(reader,Writer(),seen.append)
            reader.feed_data(b'Event: QueueParams\r\nActionID: sq-expired\r\nQueue: 8001\r\n\r\nEvent: OriginateResponse\r\nActionID: sq-callback\r\nResponse: Success\r\n\r\n');reader.feed_eof();await client._read_loop();return seen
        events=asyncio.run(run());self.assertEqual(len(events),1);self.assertEqual(events[0]['event'],'OriginateResponse')
    def test_audio_conversion_is_real_and_metadata_free(self):
        stream=io.BytesIO()
        with wave.open(stream,'wb') as sound:sound.setnchannels(1);sound.setsampwidth(2);sound.setframerate(16000);sound.writeframes(b'\0\0'*1600)
        result,seconds=convert_audio(stream.getvalue());self.assertAlmostEqual(seconds,.1,places=2)
        with wave.open(io.BytesIO(result),'rb') as sound:self.assertEqual((sound.getnchannels(),sound.getframerate(),sound.getsampwidth()),(1,8000,2))
        with self.assertRaises(ValueError):convert_audio(b'<html>not audio</html>')
    def test_api_requires_admin_csrf_and_rejects_bad_config(self):
        app=Flask(__name__);app.secret_key='test';login=LoginManager(app)
        class User(UserMixin):id='owner'
        login.user_loader(lambda ident:User());role=['admin'];install(app,self.root,lambda:role[0]);client=app.test_client()
        self.assertEqual(client.get('/api/pbx/features').status_code,401)
        with client.session_transaction() as session:session['_user_id']='owner';session['_fresh']=True;session['csrf_token']='token'
        self.assertEqual(client.get('/api/pbx/features').status_code,200)
        self.assertEqual(client.post('/api/pbx/features',json={}).status_code,403)
        self.assertEqual(client.post('/api/pbx/features',json={},headers={'X-CSRF-Token':'token'}).status_code,200)
        role[0]='supervisor';self.assertEqual(client.get('/api/pbx/features').status_code,403)
    def test_fastagi_protocol_closes_after_bounded_variable_exchange(self):
        cfg=self.runtime();cfg['settings']['caller_id']['enabled']=True
        class Runtime:
            def read(self):return cfg
        async def run():
            service=FastAGI(Runtime(),self.root);server=await asyncio.start_server(service.handle,'127.0.0.1',0)
            try:
                reader,writer=await asyncio.open_connection('127.0.0.1',server.sockets[0].getsockname()[1]);writer.write(('agi_network_script: '+'a'*64+'/normalize\nagi_callerid: +989121234567\n\n').encode());await writer.drain()
                first=await asyncio.wait_for(reader.readline(),2);writer.write(b'200 result=1\n');await writer.drain();second=await asyncio.wait_for(reader.readline(),2);writer.write(b'200 result=1\n');await writer.drain();await asyncio.wait_for(reader.read(),2);writer.close();await writer.wait_closed()
                self.assertIn(b'SQ_CID_CHANGED "1"',first);self.assertIn(b'09121234567',second)
            finally:server.close();await server.wait_closed()
        asyncio.run(run())
