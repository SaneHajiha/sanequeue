"""Saved report API ownership, grant and request-id boundaries."""
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from types import SimpleNamespace
from unittest.mock import Mock,patch
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

    def test_manual_retry_after_tehran_midnight_reuses_original_job_before_new_snapshot(self):
        made=self.client.post(self.path,json=self.body,headers=self.headers)
        ident=made.json['plan']['id'];url='/api/history/plans/'+ident+'/run'+self.case.dates
        before_midnight=datetime(2026,10,25,23,59,59,tzinfo=ZoneInfo('Asia/Tehran')).timestamp()
        # Replace this module's binding, not the shared time module used by
        # Flask's signed-session age validation and every other worker/store.
        with patch('sanequeue.api.reports.time',SimpleNamespace(time=Mock(return_value=before_midnight))):
            first=self.client.post(url,json={'request_key':'same-network-request'},headers=self.headers)
        self.assertEqual(first.status_code,202,first.json)
        with patch('sanequeue.api.reports.time',SimpleNamespace(time=Mock(return_value=before_midnight+2))),\
             patch('sanequeue.api.reports.period_bounds',side_effect=AssertionError('retry recomputed period')),\
             patch('sanequeue.api.reports.visit_snapshots.capture',side_effect=AssertionError('retry captured snapshot')):
            again=self.client.post(url,json={'request_key':'same-network-request'},headers=self.headers)
        self.assertEqual(again.status_code,202,again.json)
        self.assertEqual(again.json['job']['id'],first.json['job']['id'])
        self.assertEqual(again.json['job']['start'],first.json['job']['start'])
        store=JobStore(self.case.root/'export-jobs.sqlite3',self.case.root/'private-exports')
        self.assertEqual(len(store.list('test')),1)
        # Simulate a concurrent request winning the unique key immediately
        # after this retry's first lookup, across the midnight period change.
        lookup=JobStore.by_request;lookups=[]
        def just_created(store,owner,key):
            lookups.append(1)
            return None if len(lookups)==1 else lookup(store,owner,key)
        with patch('sanequeue.api.reports.time',SimpleNamespace(time=Mock(return_value=before_midnight+2))),\
             patch.object(JobStore,'by_request',autospec=True,side_effect=just_created):
            raced=self.client.post(url,json={'request_key':'same-network-request'},headers=self.headers)
        self.assertEqual(raced.status_code,202,raced.json)
        self.assertEqual(raced.json['job']['id'],first.json['job']['id']);self.assertEqual(len(lookups),2)

    def test_manual_retry_rechecks_original_full_number_permission_and_plan_key_namespace(self):
        made=self.client.post(self.path,json=self.body,headers=self.headers)
        ident=made.json['plan']['id'];url='/api/history/plans/'+ident+'/run'+self.case.dates
        first=self.client.post(url,json={'request_key':'one'},headers=self.headers)
        self.assertEqual(first.status_code,202,first.json)
        masked=self.case.client(role='admin',menus=('reports',),details=False)
        with masked.session_transaction() as session:session['csrf_token']='test'
        self.assertEqual(masked.post(url,json={'request_key':'one'},headers=self.headers).status_code,403)
        second=self.client.post(self.path,json={**self.body,'name':'Another plan'},headers=self.headers)
        second_url='/api/history/plans/'+second.json['plan']['id']+'/run'+self.case.dates
        other=self.client.post(second_url,json={'request_key':'one'},headers=self.headers)
        self.assertEqual(other.status_code,202,other.json)
        self.assertNotEqual(first.json['job']['id'],other.json['job']['id'])

if __name__=='__main__':unittest.main()
