import asyncio,io,json,tempfile,unittest
import struct,zlib
from pathlib import Path
from unittest.mock import AsyncMock,patch
from types import SimpleNamespace
from flask import Flask
from flask_login import LoginManager,UserMixin
from PIL import Image
from sanequeue.security.organization import Organization,install,disabled
from sanequeue.api.state import StateReader,StateUnavailable
from sanequeue.realtime.collector import Collector
from scripts.module_control import without_managed_access,remove_managed_ami,UNITS


class OrganizationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.flag=self.root/'module.disabled'
        environment=patch.dict('os.environ',SANEQUEUE_DISABLE_FILE=str(self.flag));environment.start();self.addCleanup(environment.stop)
        self.app=Flask('organization-test');self.app.secret_key='synthetic-only-key'
        class User(UserMixin):
            def __init__(self,ident):self.id=ident
        manager=LoginManager(self.app);manager.user_loader(lambda ident:User(ident))
        install(self.app,self.root,lambda:'admin')
        self.client=self.app.test_client()
        with self.client.session_transaction() as session:session.update(_user_id='admin',_fresh=True,csrf_token='synthetic-csrf')
        self.headers={'X-CSRF-Token':'synthetic-csrf'}

    def test_branding_is_bounded_and_logo_is_reencoded(self):
        image=io.BytesIO();Image.new('RGB',(300,150),'green').save(image,'PNG')
        response=self.client.post('/api/organization',data={'name':'Example Team','subtitle':'Support','logo':(io.BytesIO(image.getvalue()),'logo.png')},headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.get('/organization/logo').mimetype,'image/png')
        self.assertEqual(Image.open(io.BytesIO(self.client.get('/organization/logo').data)).size,(256,128))
        self.assertEqual(self.client.post('/api/organization',data={'name':'x'*66},headers=self.headers).status_code,400)
        self.assertEqual(self.client.post('/api/organization',data={'name':'Team','logo':(io.BytesIO(b'<svg onload="alert(1)"/>'),'logo.svg')},headers=self.headers).status_code,400)

    def test_module_pause_is_reversible_and_fails_closed_before_cache(self):
        self.assertEqual(self.client.post('/api/module',json={'enabled':False}).status_code,403)
        self.assertEqual(self.client.post('/api/module',json={'enabled':'false'},headers=self.headers).status_code,400)
        self.assertEqual(self.client.post('/api/module',json={'enabled':False},headers=self.headers).status_code,200)
        self.assertTrue(disabled())
        reader=StateReader(None,'primary');reader.cached=({'queues':{}},{});reader.until=float('inf')
        with self.assertRaises(StateUnavailable):reader.read()
        self.assertEqual(self.client.post('/api/module',json={'enabled':True},headers=self.headers).status_code,200)
        self.assertFalse(disabled())

    def test_web_disable_immediately_bypasses_telephone_features(self):
        spool=self.root/'pbx-spool';spool.mkdir()
        with patch.dict('os.environ',SANEQUEUE_PBX_SPOOL=str(spool)):
            self.assertEqual(self.client.post('/api/module',json={'enabled':False},headers=self.headers).status_code,200)
            self.assertTrue((spool/'disabled').is_file())
            self.assertEqual(self.client.post('/api/module',json={'enabled':False},headers=self.headers).status_code,200)
            self.assertEqual(self.client.post('/api/module',json={'enabled':True},headers=self.headers).status_code,200)
            self.assertFalse((spool/'disabled').exists())

    def test_organization_and_module_require_settings_permission(self):
        self.app.config['SANEQUEUE_MENU_PROVIDER']=lambda user,role:{'queues'}
        self.assertEqual(self.client.get('/api/organization').status_code,403)
        self.assertEqual(self.client.post('/api/module',json={'enabled':False},headers=self.headers).status_code,403)

    def test_corrupt_branding_structure_cannot_break_page_context(self):
        for value in (None,[],42,'text',{'name':None,'subtitle':[],'updated_at':float('nan')}):
            (self.root/'organization.json').write_text(json.dumps(value))
            response=self.client.get('/api/organization')
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json['name'],'SaneQueue')
            with self.app.test_request_context('/'):
                context={};self.app.update_template_context(context)
                self.assertEqual(context['organization']['name'],'SaneQueue')

    def test_decompression_bomb_header_returns_validation_error(self):
        buffer=io.BytesIO();Image.new('RGB',(1,1)).save(buffer,'PNG');data=bytearray(buffer.getvalue())
        data[16:24]=struct.pack('>II',100000,100000);data[29:33]=struct.pack('>I',zlib.crc32(data[12:29]) & 0xffffffff)
        response=self.client.post('/api/organization',data={'name':'Team','subtitle':'','logo':(io.BytesIO(data),'logo.png')},headers=self.headers)
        self.assertEqual(response.status_code,400)

    def test_removal_only_targets_our_managed_block_and_services(self):
        original='[other_monitor]\nsecret=retained\n; BEGIN SANEQUEUE MANAGED ACCESS\n[sanequeue_collector_auto]\nsecret=removed\n; END SANEQUEUE MANAGED ACCESS\n[other_user]\nsecret=also_retained\n'
        value=without_managed_access(original)
        self.assertIn('secret=retained',value);self.assertIn('secret=also_retained',value)
        self.assertNotIn('secret=removed',value)
        self.assertTrue(all(unit.startswith('sanequeue') for unit in UNITS))
        self.assertNotIn('asterisk.service',UNITS)

    def test_failed_manager_reload_restores_original_configuration(self):
        manager=self.root/'manager_custom.conf';backup=self.root/'backup';backup.mkdir()
        original='[other]\nsecret=retained\n; BEGIN SANEQUEUE MANAGED ACCESS\n[ours]\nsecret=removed\n; END SANEQUEUE MANAGED ACCESS\n'
        manager.write_text(original)
        with patch('scripts.module_control.os.chown',create=True),patch('scripts.module_control.os.chmod'):
            with self.assertRaisesRegex(RuntimeError,'original_configuration_restored'):
                remove_managed_ami(manager,backup,lambda:1)
        self.assertEqual(manager.read_text(),original)
        self.assertEqual((backup/manager.name).read_text(),original)


class DisabledCollectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_worker_never_connects_to_ami(self):
        collector=Collector(SimpleNamespace(),None)
        with patch('sanequeue.security.organization.disabled',return_value=True),patch('sanequeue.realtime.collector.AsyncAMI.connect',new_callable=AsyncMock) as connect:
            with self.assertRaisesRegex(ConnectionError,'module_disabled'):await collector.worker()
            connect.assert_not_awaited()

    async def test_runtime_pause_closes_worker_session(self):
        collector=Collector(SimpleNamespace(),None)
        with patch('sanequeue.security.organization.disabled',return_value=True):
            with self.assertRaisesRegex(ConnectionError,'module_disabled'):await collector.watch_enabled()
