"""Fresh owner/audio/multi-queue grants for synthetic generative jobs."""
import copy
import unittest
from flask import Flask,abort
from flask_login import LoginManager,UserMixin
from sanequeue.api.generative import install
from sanequeue.reporting.generative_jobs import GenerativeJobs
from tests import test_reporting_generative as fixtures


class User(UserMixin):
    def __init__(self,name):self.id=name


class GenerativeAPITests(unittest.TestCase):
    setUp_data=fixtures.GenerativeTests.setUp
    final=fixtures.GenerativeTests.final
    def setUp(self):
        self.setUp_data();self.role='supervisor';self.grants={'8001'};self.proof=['8001'];self.active=True
        self.app=Flask(__name__);self.app.secret_key='synthetic-test-secret';self.app.testing=True
        login=LoginManager(self.app);login.user_loader(lambda ident:User(ident))
        def authorize(spec,deadline=None):
            if not self.proof:abort(403)
            return self.proof
        install(self.app,self.sources,self.archive,role=lambda:self.role,sections=lambda:['reports','audit'],
            can_queue=lambda queue,cap:queue in self.grants,authorize_source=authorize,enabled=lambda:self.active)
        self.jobs=GenerativeJobs(self.root/'generative-jobs.sqlite3')
        self.client=self.app.test_client()
        with self.client.session_transaction() as session:session['_user_id']='alice';session['_fresh']=True;session['csrf_token']='token'
        self.headers={'X-CSRF-Token':'token'};self.body=dict(source_job_id=self.source['id'],language='fa',request_key='request')
        self.path='/api/history/generative-jobs'
    def post(self,**extra):return self.client.post(self.path,json={**self.body,**extra},headers=self.headers)
    def test_opt_in_csrf_role_and_body_cannot_select_endpoint_or_arbitrary_text(self):
        self.assertEqual(self.client.post(self.path,json=self.body).status_code,403)
        self.active=False;self.assertEqual(self.post().status_code,503);self.active=True
        self.assertEqual(self.post(endpoint='http://example.invalid').status_code,400)
        self.assertEqual(self.post(text='Ignored private text').status_code,400)
        self.assertEqual(self.post().status_code,202)
        self.role='agent';self.assertEqual(self.client.get(self.path).status_code,403)
    def test_frozen_multi_queue_scope_rechecked_on_result_list_and_cancel(self):
        self.proof=['8001','8002'];self.assertEqual(self.post().status_code,403)
        self.grants.add('8002');made=self.post();self.assertEqual(made.status_code,202,made.json)
        ident=made.json['job']['id'];job=self.jobs.get(ident,'alice');self.assertEqual(job['spec']['queues'],['8001','8002'])
        self.jobs.claim('worker');self.jobs.complete(ident,'worker',self.final(job))
        self.assertEqual(self.client.get(self.path+'/'+ident).status_code,200)
        self.assertIsNone(self.client.get(self.path).json['jobs'][0]['result'])
        self.grants.remove('8002')
        self.assertEqual(self.client.get(self.path+'/'+ident).status_code,403)
        self.assertEqual(self.client.get(self.path).json['jobs'],[])
        self.assertEqual(self.client.post(self.path+'/'+ident,json={},headers=self.headers).status_code,403)
    def test_private_owner_and_pinned_source_changes_deny_later_reads(self):
        made=self.post();ident=made.json['job']['id']
        with self.client.session_transaction() as session:session['_user_id']='bob'
        self.assertEqual(self.client.get(self.path+'/'+ident).status_code,404)
        self.assertEqual(self.client.get(self.path).json['jobs'],[])
        with self.client.session_transaction() as session:session['_user_id']='alice'
        changed=copy.deepcopy(self.source['result']);changed['text']='New source';changed['segments']=[dict(start=1,end=3,text='New source')]
        from sanequeue.reporting.text_generation import canonical
        with self.sources._db(write=True) as db:db.execute('UPDATE ai_jobs SET result=? WHERE id=?',(canonical(changed),self.source['id']))
        self.assertEqual(self.client.get(self.path+'/'+ident).status_code,403)
    def test_privacy_headers_cover_success_error_and_unauthenticated(self):
        for response in (self.client.get(self.path),self.client.post(self.path,json={}),self.app.test_client().get(self.path)):
            self.assertEqual(response.headers.get('Cache-Control'),'private, no-store')
            self.assertEqual(response.headers.get('X-Content-Type-Options'),'nosniff')


if __name__=='__main__':unittest.main()
