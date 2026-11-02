"""Builder API current scope, CSRF and masking against real archive fixtures."""
import unittest
from unittest.mock import patch
from tests import test_reporting_queries as fixtures
from sanequeue.api.report_builder import install
from sanequeue.reporting.queries import Scope


class BuilderAPITests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.ReportTests();self.case.setUp();self.addCleanup(self.case.doCleanups);self.case.seed()
        with patch('sanequeue.api.report_builder.install'):
            self.client=self.case.client(role='admin',menus=('reports',),details=True)
        self.scope=Scope(('8001',));self.full=False;self.role='supervisor'
        install(self.client.application,self.case.archive,context=lambda **kw:(self.scope,self.case.stamp,self.case.stamp+100),
            role=lambda:self.role,sections=lambda:['reports'],can_queue=lambda q,action:q in self.scope.queues and (action!='caller_details' or self.full))
        with self.client.session_transaction() as state:state['csrf_token']='token'
        self.headers={'X-CSRF-Token':'token'};self.spec=dict(dataset='queue_visits',columns=['queue','caller','agent'],group_by=[],filters={},queues=['8001'])
    def test_preview_csrf_masking_then_current_revocation(self):
        path='/api/history/builder/preview';body={'definition':self.spec}
        self.assertEqual(self.client.post(path,json=body).status_code,403)
        response=self.client.post(path,json=body,headers=self.headers)
        self.assertEqual(response.status_code,200,response.json);self.assertEqual(response.json['rows'][0]['caller'],'0912***6789')
        self.full=True
        self.assertEqual(self.client.post(path,json=body,headers=self.headers).json['rows'][0]['caller'],'09123456789')
        self.scope=Scope(('8002',))
        self.assertEqual(self.client.post(path,json=body,headers=self.headers).status_code,403)
    def test_private_headers_cover_success_csrf_and_unauthenticated_responses(self):
        path='/api/history/builder/templates'
        for response in (self.client.get(path),self.client.post(path,json={}),self.client.application.test_client().get(path)):
            self.assertEqual(response.headers.get('Cache-Control'),'private, no-store')
            self.assertEqual(response.headers.get('X-Content-Type-Options'),'nosniff')
    def test_private_template_revision_scope_and_no_arbitrary_owner(self):
        path='/api/history/builder/templates';body={'name':'My template','definition':self.spec,'owner':'other'}
        made=self.client.post(path,json=body,headers=self.headers);self.assertEqual(made.status_code,201,made.json)
        ident=made.json['template']['id'];url=path+'/'+ident
        revised=self.client.post(url,json={**body,'expected_version':1},headers=self.headers)
        self.assertEqual(revised.json['template']['version'],2)
        self.assertEqual(self.client.post(url,json={**body,'expected_version':1},headers=self.headers).status_code,409)
        self.scope=Scope(('8002',))
        self.assertEqual(self.client.get(path).json['templates'],[])
        self.assertEqual(self.client.get(url).status_code,403)
    def test_agent_own_scope_and_bad_payload_role(self):
        self.role='agent';self.scope=Scope(('8001',),('200',),True)
        response=self.client.post('/api/history/builder/preview',json={'definition':self.spec},headers=self.headers)
        self.assertEqual(response.json['rows'],[])
        self.assertEqual(self.client.post('/api/history/builder/templates',json=[],headers=self.headers).status_code,400)
        self.assertEqual(self.client.post('/api/history/builder/templates',data='X'*16385,content_type='application/json',headers=self.headers).status_code,413)
        self.assertEqual(self.client.post('/api/history/builder/templates',data='not JSON',content_type='text/plain',headers=self.headers).status_code,415)
        self.role='viewer';self.assertEqual(self.client.get('/api/history/builder/templates').status_code,403)
    def test_safe_limit_codes_explain_actual_source_and_range_failures(self):
        with self.case.archive.writer() as db:
            db.execute('UPDATE report_visits SET caller=? WHERE queue=?',('X'*2049,'8001'))
        response=self.client.post('/api/history/builder/preview',json={'definition':self.spec},headers=self.headers)
        self.assertEqual(response.status_code,400)
        self.assertEqual(response.json,{'error':'builder_field_limit'})
        self.assertNotIn('X'*50,response.text)
        client=self.case.client(role='supervisor',menus=('reports',),details=False)
        with client.session_transaction() as state:state['csrf_token']='token'
        response=client.post('/api/history/builder/preview?from=2026-10-01&to=2026-11-15',json={'definition':self.spec},headers=self.headers)
        self.assertEqual(response.status_code,400)
        self.assertEqual(response.json,{'error':'builder_range_limit'})

    def test_existing_report_installer_wires_real_builder_with_current_grants(self):
        client=self.case.client(role='supervisor',menus=('reports',),details=False)
        with client.session_transaction() as state:state['csrf_token']='token'
        response=client.post('/api/history/builder/preview'+self.case.dates,json={'definition':self.spec},headers=self.headers)
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json['rows'][0]['caller'],'0912***6789')

if __name__=='__main__':unittest.main()
