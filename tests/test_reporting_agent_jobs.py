import unittest
from tests import test_reporting_queries as fixtures
from sanequeue.reporting.agent_jobs import AgentJobStore, AgentSummaryWorker, read_result
from sanequeue.reporting.export_jobs import JobStore, ExportFailure


class AgentJobTests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.ReportTests();self.case.setUp();self.addCleanup(self.case.doCleanups);self.case.seed()
        with self.case.archive.writer() as db:
            db.execute("UPDATE report_visits SET agent='PJSIP/100' WHERE agent LIKE 'Local/100%'")
        self.case.archive.append([],checkpoint_source='activity_cache',checkpoint={'observed':self.case.stamp+1000})
        JobStore(self.case.root/'export-jobs.sqlite3',self.case.root/'private-exports').initialize()
        self.store=AgentJobStore(self.case.root/'agent-summary-jobs.sqlite3',self.case.root/'private-agent-summaries')
        self.store.initialize()
        self.client=self.case.client(role='admin',menus=('reports',))
        with self.client.session_transaction() as state:state['csrf_token']='token'
        self.headers={'X-CSRF-Token':'token'}
        self.url='/api/history/agent-summary-jobs'+self.case.dates

    def create(self,key='one'):
        return self.client.post(self.url,json={'min_samples':1,'top':10,'request_key':key},headers=self.headers)

    def test_end_to_end_permissions_integrity_and_private_response(self):
        response=self.create();self.assertEqual(response.status_code,202,response.json)
        ident=response.json['job']['id']
        self.assertEqual(self.create().json['job']['id'],ident)
        worker=AgentSummaryWorker(self.store,self.case.archive,lambda:None,lambda spec:True)
        result=worker.run_once();self.assertEqual(result['state'],'completed',result)
        url='/api/history/agent-summary-jobs/'+ident+'/result'
        response=self.client.get(url);self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.headers['Cache-Control'],'private, no-store')
        self.assertNotIn('09123456789',response.text)
        self.assertEqual(self.client.get(url.replace('/result','/download')).json,response.json)
        revoked=self.case.client(role='admin',menus=('reports',),denied=('report_export',))
        self.assertEqual(revoked.get(url).status_code,403)
        (self.store.output_dir/(ident+'.json')).write_text('{}',encoding='utf8')
        with self.assertRaises(ExportFailure):read_result(self.store,ident,'test')

    def test_csrf_role_cancel_and_revocation(self):
        body={'min_samples':1,'top':10,'request_key':'x'}
        self.assertEqual(self.client.post(self.url,json=body).status_code,403)
        agent=self.case.client(role='agent',menus=('reports',))
        self.assertEqual(agent.get(self.url).status_code,403)
        ident=self.create().json['job']['id']
        denied=AgentSummaryWorker(self.store,self.case.archive,lambda:None,lambda spec:False).run_once()
        self.assertEqual(denied['state'],'failed')
        self.assertEqual(denied['error'],'agent_access_denied')
        self.assertFalse((self.store.output_dir/(ident+'.json')).exists())
        ident=self.create('cancel').json['job']['id']
        self.assertTrue(self.client.post('/api/history/agent-summary-jobs/'+ident+'/cancel',headers=self.headers).json['cancelled'])
        self.assertEqual(self.store.get(ident,'test')['state'],'cancelled')

    def test_permission_revoked_during_calculation_never_publishes(self):
        ident=self.create('revoked').json['job']['id']
        checks=[]
        def authorize(spec):
            checks.append(1)
            return len(checks)<4
        state=AgentSummaryWorker(self.store,self.case.archive,lambda:None,authorize).run_once()
        self.assertEqual(state['state'],'failed')
        self.assertEqual(state['error'],'agent_access_denied')
        self.assertFalse((self.store.output_dir/(ident+'.json')).exists())
        self.assertEqual(self.client.get('/api/history/agent-summary-jobs/'+ident+'/result').status_code,404)


if __name__=='__main__':unittest.main()
