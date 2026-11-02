import unittest
from unittest.mock import patch
from flask import Flask
from flask_login import LoginManager,UserMixin
from sanequeue.api.ring_attempts import install
from sanequeue.reporting.queries import Scope
from sanequeue.reporting.store import QueryDeadline
from tests import test_reporting_ring_attempts as fixtures


class User(UserMixin):id='synthetic-user'


class RingAttemptAPITests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.RingAttemptTests();self.fixture.setUp();self.archive=self.fixture.archive
        self.role='supervisor';self.sections=['reports'];self.queues={'8001'};self.export=True;self.scope=Scope(('8001',))
        self.app=Flask(__name__);self.app.secret_key='synthetic-secret';self.app.testing=True
        login=LoginManager(self.app);login.user_loader(lambda ident:User())
        install(self.app,self.archive,lambda:(self.scope,100,200),role=lambda:self.role,sections=lambda:self.sections,can_queue=lambda q,c:q in self.queues and (c!='report_export' or self.export))
        self.client=self.app.test_client();self.path='/api/history/ring-attempts'
        with self.client.session_transaction() as session:session['_user_id']=User.id;session['_fresh']=True
    def tearDown(self):self.fixture.tearDown()
    def test_current_role_reports_and_queue_grants(self):
        self.assertEqual(self.client.get(self.path).status_code,200)
        self.queues.clear();self.assertEqual(self.client.get(self.path).status_code,403)
        self.queues.add('8001');self.role='agent';self.assertEqual(self.client.get(self.path).status_code,403)
        self.role='admin';self.sections=[];self.assertEqual(self.client.get(self.path).status_code,403)
    def test_headers_all_responses_and_limits_safe_errors(self):
        for path,code in ((self.path,200),(self.path+'?limit=101',400),(self.path+'?limit=abc',400)):
            response=self.client.get(path);self.assertEqual(response.status_code,code);self.assertEqual(response.headers['Cache-Control'],'private, no-store');self.assertEqual(response.headers['X-Content-Type-Options'],'nosniff')
        with patch('sanequeue.api.ring_attempts.report',side_effect=QueryDeadline('PRIVATE')):
            response=self.client.get(self.path);self.assertEqual(response.status_code,422);self.assertNotIn('PRIVATE',response.get_data(as_text=True))
        with self.client.session_transaction() as session:session.clear()
        response=self.client.get(self.path);self.assertEqual(response.status_code,401);self.assertEqual(response.headers['Cache-Control'],'private, no-store')
    def test_readonly_request_never_initializes_archive_and_agent_scope_rejected(self):
        with patch.object(self.archive,'initialize',side_effect=AssertionError('No request DDL')):
            self.assertEqual(self.client.get(self.path).status_code,200)
        self.scope=Scope(('8001',),('100',),True,0);self.assertEqual(self.client.get(self.path).status_code,403)

    def test_csv_uses_full_groups_and_separate_current_export_permission(self):
        import csv,io
        for at in (110,120,130):self.fixture.event('RINGNOANSWER',at,values=['1000'])
        response=self.client.get(self.path+'.csv?limit=1&lang=fa')
        self.assertEqual(response.status_code,200);self.assertIn('text/csv',response.content_type)
        rows=list(csv.reader(io.StringIO(response.data.decode('utf-8-sig'))))
        self.assertEqual(len(rows),3);self.assertEqual(rows[2][2],'3','CSV totals cover all events, not one detail row')
        self.assertEqual(self.client.get(self.path).json['can_export'],True)
        self.export=False;self.assertEqual(self.client.get(self.path).status_code,200)
        self.assertEqual(self.client.get(self.path).json['can_export'],False)
        denied=self.client.get(self.path+'.csv');self.assertEqual(denied.status_code,403)
        self.assertEqual(denied.headers['Cache-Control'],'private, no-store')

    def test_csv_neutralizes_formula_like_queue_labels(self):
        import csv,io
        self.scope=Scope(('=1+1',));self.queues={'=1+1'}
        self.fixture.event('RINGNOANSWER',120,queue='=1+1',values=['1000'])
        response=self.client.get(self.path+'.csv')
        self.assertEqual(response.status_code,200)
        rows=list(csv.reader(io.StringIO(response.data.decode('utf-8-sig'))))
        self.assertEqual(rows[2][0],"'=1+1")

    def test_real_report_installer_exposes_scope_protected_route(self):
        from tests import test_reporting_queries as real
        case=real.ReportTests();case.setUp();self.addCleanup(case.doCleanups);case.seed()
        client=case.client(role='admin');response=client.get(self.path+case.dates)
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(case.client(role='agent').get(self.path+case.dates).status_code,403)

if __name__=='__main__':unittest.main()
