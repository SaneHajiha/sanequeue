"""Custom definitions reach durable jobs/plans without broadening queue scope."""
import unittest
from unittest.mock import patch
from tests import test_reporting_queries as fixtures
from sanequeue.reporting.export_jobs import JobStore


class BuilderBackgroundAPITests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.ReportTests();self.case.setUp();self.addCleanup(self.case.doCleanups);self.case.seed()
        self.jobs=JobStore(self.case.root/'export-jobs.sqlite3',self.case.root/'private-exports');self.jobs.initialize()
        self.client=self.case.client(role='admin',menus=('reports',),details=False)
        with self.client.session_transaction() as state:state['csrf_token']='token'
        self.headers={'X-CSRF-Token':'token'}
        self.spec=dict(dataset='queue_visits',queues=['8001'],columns=['agent','caller'],group_by=['agent'],filters={'talk_min':10})
        self.url='/api/history/export-jobs'+self.case.dates+'&format=xlsx'

    def test_exact_definition_selected_scope_and_masking_are_frozen(self):
        response=self.client.post(self.url,json={'builder_definition':self.spec},headers=self.headers)
        self.assertEqual(response.status_code,202,response.json)
        job=self.jobs.get(response.json['id'],'test');spec=job['spec']
        self.assertEqual(spec['builder_definition'],self.spec)
        self.assertEqual(spec['scope']['queues'],['8001'])
        self.assertEqual(spec['number_modes'],{'8001':'masked'})
        self.assertEqual(spec['format'],'xlsx');self.assertIn('snapshot',spec)

    def test_invalid_unknown_queue_pdf_conflicting_outcome_and_missing_csrf_fail(self):
        for url,body,headers,status in (
            (self.url,{'builder_definition':self.spec},{},403),
            (self.url,{'builder_definition':{**self.spec,'queues':['9999']}},self.headers,403),
            (self.url.replace('xlsx','pdf'),{'builder_definition':self.spec},self.headers,400),
            (self.url+'&outcome=answered',{'builder_definition':self.spec},self.headers,400),
            (self.url,{'builder_definition':{**self.spec,'columns':['raw_sql']}},self.headers,400)):
            with self.subTest(url=url,body=body):
                response=self.client.post(url,json=body,headers=headers)
                self.assertEqual(response.status_code,status,response.json)
        self.assertEqual(self.jobs.list('test'),[])

    def test_private_plan_run_freezes_definition_and_edits_do_not_mutate_job(self):
        body=dict(name='Exact grouped',queues=['8001'],format='csv',language='fa',period='yesterday',enabled=False,builder_definition=self.spec)
        made=self.client.post('/api/history/plans'+self.case.dates,json=body,headers=self.headers)
        self.assertEqual(made.status_code,201,made.json);plan=made.json['plan']
        url='/api/history/plans/'+plan['id']+'/run'+self.case.dates
        response=self.client.post(url,json={'request_key':'same'},headers=self.headers)
        self.assertEqual(response.status_code,202,response.json)
        ident=response.json['job']['id']
        changed={**body,'id':plan['id'],'builder_definition':{**self.spec,'columns':['queue'],'group_by':[]}}
        self.assertEqual(self.client.post('/api/history/plans'+self.case.dates,json=changed,headers=self.headers).status_code,201)
        with patch('sanequeue.api.reports.visit_snapshots.capture',side_effect=AssertionError('retry must reuse original')):
            retried=self.client.post(url,json={'request_key':'same'},headers=self.headers)
        self.assertEqual(retried.json['job']['id'],ident)
        self.assertEqual(self.jobs.get(ident,'test')['spec']['builder_definition'],self.spec)
        legacy_edit={**body,'id':plan['id'],'name':'Schedule only'};legacy_edit.pop('builder_definition')
        kept=self.client.post('/api/history/plans'+self.case.dates,json=legacy_edit,headers=self.headers)
        self.assertEqual(kept.status_code,201,kept.json)
        self.assertEqual(kept.json['plan']['builder_definition'],changed['builder_definition'])
        cleared=self.client.post('/api/history/plans'+self.case.dates,json={**legacy_edit,'builder_definition':None},headers=self.headers)
        self.assertEqual(cleared.status_code,400)

    def test_body_size_bound_and_agent_cannot_queue(self):
        response=self.client.post(self.url,data=' '*16385,content_type='application/json',headers=self.headers)
        self.assertEqual(response.status_code,413)
        agent=self.case.client(role='agent',menus=('reports',))
        with agent.session_transaction() as state:state['csrf_token']='token'
        self.assertEqual(agent.post(self.url,json={'builder_definition':self.spec},headers=self.headers).status_code,403)
        nested='['*1500+'0'+']'*1500
        for url in (self.url,'/api/history/plans'+self.case.dates):
            self.assertEqual(self.client.post(url,data=nested,content_type='application/json',headers=self.headers).status_code,400)

    def test_ranking_api_scope_units_invalid_metric_and_private_headers(self):
        response=self.client.get('/api/history/agent-rankings'+self.case.dates+'&min_samples=1')
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json['allowed_queues'],['8001'])
        self.assertEqual(response.json['unit'],'queue_visit')
        self.assertEqual(response.headers['Cache-Control'],'private, no-store')
        self.assertNotIn('09999999999',response.text)
        self.assertEqual(self.client.get('/api/history/agent-rankings'+self.case.dates+'&metric=quality').status_code,400)
        self.assertEqual(self.client.get('/api/history/agent-rankings'+self.case.dates+'&min_samples=0').status_code,400)
        self.assertEqual(self.client.get('/api/history/agent-rankings'+self.case.dates+'&queue=8002').status_code,403)

    def test_custom_plan_queue_selection_is_independent_of_display_queue(self):
        original=fixtures.install
        def both(*args,**kwargs):
            kwargs['can_queue']=lambda queue,cap:queue in ('8001','8002')
            return original(*args,**kwargs)
        with patch.object(fixtures,'install',side_effect=both):client=self.case.client(role='admin',menus=('reports',))
        with client.session_transaction() as state:state['csrf_token']='token'
        spec={**self.spec,'queues':['8001','8002']}
        body=dict(name='Both queues',queues=spec['queues'],format='csv',builder_definition=spec)
        response=client.post('/api/history/plans'+self.case.dates+'&queue=8001',json=body,headers=self.headers)
        self.assertEqual(response.status_code,201,response.json)
        self.assertEqual(response.json['plan']['builder_definition']['queues'],['8001','8002'])


if __name__=='__main__':unittest.main()
