import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sanequeue.alerts.messaging import NotificationSettings, MessagingError, call, alert_text
from sanequeue.alerts.outbox import AlertOutbox
from qpanel.queue_policies import QueuePolicyStore
from flask import Flask
from flask_login import LoginManager, UserMixin
from qpanel.operations import install

TOKEN='123456789:'+'a'*35


class MessagingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.settings=NotificationSettings(self.root/'settings.json')

    def tearDown(self):self.temp.cleanup()

    def test_write_only_token_and_atomic_validation(self):
        public=self.settings.replace({'telegram':{'enabled':True,'token':TOKEN,'chat_id':'-100123'}})
        self.assertNotIn(TOKEN,json.dumps(public))
        self.settings.replace({'telegram':{'enabled':True,'token':'','chat_id':'123'}})
        self.assertEqual(json.loads(self.settings.path.read_text())['telegram']['token'],TOKEN)
        with self.assertRaises(ValueError):self.settings.replace({'telegram':{'enabled':True,'token':'bad'}})
        self.assertEqual(self.settings.enabled(),{'telegram'})
        if os.name!='nt':self.assertEqual(stat.S_IMODE(self.settings.path.stat().st_mode),0o600)

    def test_transport_never_exposes_secret_exception_url(self):
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.side_effect=ValueError('https://host/bot'+TOKEN)
            with self.assertRaises(MessagingError) as error:call('telegram',TOKEN,'sendMessage',{})
            self.assertNotIn(TOKEN,str(error.exception))
        with self.assertRaises(MessagingError):call('evil',TOKEN,'sendMessage',{})
        with self.assertRaises(MessagingError):call('telegram',TOKEN,'deleteWebhook',{})

    def test_no_caller_data_or_arbitrary_body_in_alert(self):
        text=alert_text(dict(label='Queue 8001',queue='8001',type='waiting_count',value=5,threshold=5,caller='sensitive-caller',text='untrusted-body'))
        self.assertNotIn('sensitive-caller',text)
        self.assertNotIn('untrusted-body',text)
        self.settings.replace({'bale':{'enabled':True,'token':TOKEN,'chat_id':'123'}})
        with patch('sanequeue.alerts.messaging.call',return_value={'message_id':1}) as send:
            self.assertTrue(self.settings.send('bale',test=True))
            self.assertNotIn('caller',send.call_args.args[3])

    def test_delivery_channels_are_independent_and_scoped(self):
        policies=QueuePolicyStore(self.root/'policies.json')
        policies.replace({'queues':{'8001':{'alerts':{'bale_enabled':True,'telegram_enabled':True,'cooldown_seconds':60}}}})
        now=[1000]
        box=AlertOutbox(self.root/'alerts.sqlite3',clock=lambda:now[0])
        alert=dict(queue='8001',type='waiting_count',label='Queue',value=5,threshold=5)
        box.observe([alert],policies,delivery_enabled={'bale','telegram'})
        bale=box.claim({'bale'});telegram=box.claim({'telegram'})
        self.assertEqual(bale['provider'],'bale');self.assertEqual(telegram['provider'],'telegram')
        box.finish(bale,False);box.finish(telegram,True)
        self.assertEqual(box.report(['8001'])['notification_status']['sent'],1)
        self.assertEqual(box.report(['other'])['notification_status']['sent'],0)
        now[0]+=3
        self.assertIsNone(box.claim({'telegram'}))
        self.assertEqual(box.claim({'bale'})['id'],bale['id'])
        box.observe([alert],policies,delivery_enabled={'bale','telegram'})
        self.assertIsNone(box.claim({'telegram'}))


class NotificationAPITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.app=Flask('notification-security');self.app.secret_key='test-only-session-key'
        self.settings=NotificationSettings(Path(self.temp.name)/'private.json')
        self.settings.replace({'telegram':{'enabled':True,'token':TOKEN,'chat_id':'123'}})
        self.app.config['SANEQUEUE_NOTIFICATIONS']=self.settings
        class Config:
            def has_users(self):return True
            def get_value_set_default(self,section,key,default):return key if section=='roles' else default
        class User(UserMixin):
            def __init__(self,ident):self.id=ident
        manager=LoginManager(self.app)
        manager.user_loader(lambda ident:User(ident))
        install(self.app,Config(),None,lambda:{},lambda *args,**kwargs:'')
        self.client=self.app.test_client()

    def login(self,role):
        with self.client.session_transaction() as session:
            session['_user_id']=role;session['_fresh']=True;session['csrf_token']='test-csrf'

    def test_private_configuration_requires_admin_and_csrf(self):
        self.assertIn(self.client.get('/api/notifications').status_code,(401,302))
        self.login('supervisor')
        self.assertEqual(self.client.get('/api/notifications').status_code,403)
        self.assertEqual(self.client.post('/api/notifications/test',json={'provider':'telegram'},headers={'X-CSRF-Token':'test-csrf'}).status_code,403)
        self.login('admin')
        self.assertNotIn(TOKEN,self.client.get('/api/notifications').get_data(as_text=True))
        self.assertEqual(self.client.post('/api/notifications',json={}).status_code,403)
        response=self.client.post('/api/notifications',json={'telegram':{'enabled':True,'token':'','chat_id':'456'}},headers={'X-CSRF-Token':'test-csrf'})
        self.assertEqual(response.status_code,200)
        self.assertNotIn(TOKEN,response.get_data(as_text=True))
        with patch('sanequeue.alerts.messaging.call',return_value={'message_id':1}):
            self.assertEqual(self.client.post('/api/notifications/test',json={'provider':'telegram'},headers={'X-CSRF-Token':'test-csrf'}).status_code,200)
            self.assertEqual(self.client.post('/api/notifications/test',json={'provider':'telegram'},headers={'X-CSRF-Token':'test-csrf'}).status_code,429)

    def test_hidden_section_is_also_denied_by_api(self):
        self.login('admin')
        self.app.config['SANEQUEUE_MENU_PROVIDER']=lambda username,role:{'queues'}
        self.assertEqual(self.client.get('/api/notifications').status_code,403)
        self.assertEqual(self.client.post('/api/notifications/test',json={'provider':'telegram'},headers={'X-CSRF-Token':'test-csrf'}).status_code,403)
