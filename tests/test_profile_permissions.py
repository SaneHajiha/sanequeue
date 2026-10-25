import io,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from flask import Flask
from flask_login import LoginManager,UserMixin
from PIL import Image,PngImagePlugin
from werkzeug.security import check_password_hash
from qpanel.local_accounts import set_account,read_accounts,delete_account,public_accounts
from sanequeue.security.permissions import sections_for,validate_sections
from sanequeue.security.profile import install,clean_avatar
from sanequeue.security.sessions import SessionRegistry

PASSWORD='Synthetic-original-password-123'


class ProfileTests(unittest.TestCase):
    def test_first_and_last_names_survive_account_updates_without_changing_grants(self):
        response=self.client.post('/api/profile',data={'first_name':'علی','last_name':'آزمایشی','role':'admin'},headers=self.headers)
        self.assertEqual(response.status_code,200)
        value=self.client.get('/api/profile').json
        self.assertEqual(value['display_name'],'علی آزمایشی')
        self.assertEqual(value['first_name'],'علی');self.assertEqual(value['last_name'],'آزمایشی')
        set_account(self.accounts,'alice','supervisor','PJSIP/100')
        self.assertEqual(read_accounts(self.accounts)['alice']['last_name'],'آزمایشی')
        self.assertEqual(read_accounts(self.accounts)['alice']['role'],'supervisor')
        self.assertEqual(self.client.post('/api/profile',data={'first_name':'x'*33},headers=self.headers).status_code,400)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.accounts=self.root/'accounts.json'
        set_account(self.accounts,'alice','supervisor','PJSIP/100',PASSWORD,menus=['queues','agents'])
        set_account(self.accounts,'other','admin','PJSIP/300',PASSWORD)
        self.inventory=self.root/'inventory.json'
        self.inventory.write_text(json.dumps({'observed_at':time.time(),'endpoints':[
            {'endpoint':str(x),'technology':'PJSIP','category':'extension'} for x in (100,200,300)]}))
        self.environment=patch.dict('os.environ',SANEQUEUE_LOCAL_INVENTORY=str(self.inventory));self.environment.start();self.addCleanup(self.environment.stop)
        self.app=Flask('profile-test');self.app.secret_key='test-only-session-key'
        self.registry=SessionRegistry(self.root/'sessions.sqlite3');self.app.config['SANEQUEUE_AUTH_SESSIONS']=self.registry
        class User(UserMixin):
            def __init__(self,ident):self.id=ident
        manager=LoginManager(self.app);manager.user_loader(lambda ident:User(ident))
        install(self.app,self.accounts,self.root,lambda:None)
        self.client=self.app.test_client()
        with self.client.session_transaction() as session:session.update(_user_id='alice',_fresh=True,csrf_token='test-csrf')
        self.headers={'X-CSRF-Token':'test-csrf'}

    def test_self_profile_does_not_leak_other_accounts_or_hash(self):
        value=self.client.get('/api/profile').json
        self.assertEqual(value['available_phones'],['PJSIP/100','PJSIP/200'])
        self.assertNotIn('password',json.dumps(value))
        self.assertNotIn('other',json.dumps(value))
        self.assertEqual(self.client.post('/api/profile',data={'display_name':'Alice'}).status_code,403)

    def test_password_and_extension_require_existing_password_and_revoke_sessions(self):
        self.assertEqual(self.client.post('/api/profile',data={'phone':'PJSIP/200'},headers=self.headers).status_code,403)
        self.assertEqual(self.client.post('/api/profile',data={'phone':'SIP/99999999','current_password':PASSWORD},headers=self.headers).status_code,409)
        token=self.registry.issue('alice','old');other=self.registry.issue('other','old')
        result=self.client.post('/api/profile',data={'phone':'PJSIP/200','current_password':PASSWORD,'new_password':'Synthetic-new-password-123','role':'admin','menus':'["settings"]'},headers=self.headers)
        self.assertEqual(result.status_code,200);self.assertTrue(result.json['login_required'])
        self.assertFalse(self.registry.active(token,'alice','old'));self.assertTrue(self.registry.active(other,'other','old'))
        account=read_accounts(self.accounts)['alice']
        self.assertEqual(account['role'],'supervisor');self.assertEqual(account['menus'],['agents','queues'])
        self.assertTrue(check_password_hash(account['password_hash'],'Synthetic-new-password-123'))

    def test_avatar_is_decoded_bounded_and_metadata_stripped(self):
        with self.assertRaises(Exception):clean_avatar(b'<svg onload="alert(1)"/>')
        image=Image.new('RGB',(320,200),'blue');buffer=io.BytesIO();metadata=PngImagePlugin.PngInfo();metadata.add_text('Comment','private-metadata')
        image.save(buffer,'PNG',pnginfo=metadata)
        cleaned=clean_avatar(buffer.getvalue())
        self.assertNotIn(b'private-metadata',cleaned)
        self.assertEqual(Image.open(io.BytesIO(cleaned)).size,(256,160))
        response=self.client.post('/api/profile',data={'display_name':'Alice','avatar':(io.BytesIO(buffer.getvalue()),'avatar.png')},headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.get('/api/profile/avatar').mimetype,'image/png')
        self.assertEqual(read_accounts(self.accounts)['alice']['display_name'],'Alice')

    def test_role_limits_and_profile_survive_admin_account_edits(self):
        self.assertNotIn('settings',sections_for('supervisor',{'menus':['settings','queues']}))
        with self.assertRaises(ValueError):validate_sections('viewer',['control'])
        self.client.post('/api/profile',data={'display_name':'Alice'},headers=self.headers)
        set_account(self.accounts,'alice','supervisor','PJSIP/100')
        self.assertEqual(read_accounts(self.accounts)['alice']['display_name'],'Alice')

    def test_clear_phone_does_not_require_available_inventory(self):
        self.inventory.unlink()
        response=self.client.post('/api/profile',data={'phone':'','current_password':PASSWORD},headers=self.headers)
        self.assertEqual(response.status_code,400)
        with self.client.session_transaction() as session:session['_user_id']='other'
        response=self.client.post('/api/profile',data={'phone':'','current_password':PASSWORD},headers=self.headers)
        self.assertEqual(response.status_code,200)
        self.assertEqual(read_accounts(self.accounts)['other']['phone'],'')

    def test_avatar_removal_and_account_reuse_do_not_expose_old_picture(self):
        image=io.BytesIO();Image.new('RGB',(10,10),'red').save(image,'PNG')
        self.client.post('/api/profile',data={'display_name':'Alice','avatar':(io.BytesIO(image.getvalue()),'avatar.png')},headers=self.headers)
        self.assertEqual(public_accounts(self.accounts)['alice']['display_name'],'Alice')
        self.assertEqual(self.client.post('/api/profile',data={'remove_avatar':'true'},headers=self.headers).status_code,200)
        self.assertEqual(self.client.get('/api/profile/avatar').status_code,404)
        self.client.post('/api/profile',data={'avatar':(io.BytesIO(image.getvalue()),'avatar.png')},headers=self.headers)
        delete_account(self.accounts,'alice','other')
        set_account(self.accounts,'alice','supervisor','PJSIP/100',PASSWORD)
        self.assertIsNone(self.client.get('/api/profile').json['avatar_url'])
