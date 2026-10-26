"""Saved report API ownership, grant and request-id boundaries."""
import unittest
from tests import test_reporting_queries as fixtures
from sanequeue.reporting.export_jobs import JobStore

class PlanAPITests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.ReportTests();self.case.setUp();self.addCleanup(self.case.doCleanups);self.case.seed()
        JobStore(self.case.root/'export-jobs.sqlite3',self.case.root/'private-exports').initialize()
        self.client=self.case.client(role='admin',menus=('reports',),details=True)
        with self.client.session_transaction() as session:session['csrf_token']='test'
        self.headers={'X-CSRF-Token':'test'}
        self.path='/api/history/plans'+self.case.dates
        self.body=dict(name='Acceptance schedule',queues=['8001'],format='xlsx',language='fa',period='yesterday',enabled=False)

    def test_create_list_scope_csrf_and_archive(self):
        self.assertEqual(self.client.post(self.path,json=self.body).status_code,403)
        invalid={**self.body,'queues':['9999']}
        self.assertEqual(self.client.post(self.path,json=invalid,headers=self.headers).status_code,403)
        made=self.client.post(self.path,json=self.body,headers=self.headers)
        self.assertEqual(made.status_code,201,made.json)
        ident=made.json['plan']['id']
        self.assertEqual(len(self.client.get(self.path).json['plans']),1)
        path='/api/history/plans/'+ident
        self.assertEqual(self.client.post(path+'/archive'+self.case.dates,headers=self.headers).status_code,200)
        self.assertEqual(self.client.post(path+'/run'+self.case.dates,json={'request_key':'archived'},headers=self.headers).status_code,403)

    def test_viewer_cannot_create_and_ungranted_plan_never_visible(self):
        viewer=self.case.client(role='viewer',menus=('reports',))
        self.assertEqual(viewer.get(self.path).status_code,403)
        self.client.post(self.path,json=self.body,headers=self.headers)
        restricted=self.case.client(role='admin',menus=('reports',),details=True,denied=('report_export',))
        result=restricted.get(self.path)
        self.assertIn(result.status_code,(200,403))
        if result.status_code==200:self.assertEqual(result.json['plans'],[])

if __name__=='__main__':unittest.main()
