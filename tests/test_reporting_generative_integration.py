"""Real report installer and recording-scope callback; synthetic source text."""
import unittest
from unittest.mock import patch
from tests import test_reporting_queries as fixtures
from sanequeue.reporting.store import Event
from sanequeue.reporting.facts import project_batch
from sanequeue.reporting.ai_jobs import AIJobs

class GenerativeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.ReportTests();self.case.setUp();self.addCleanup(self.case.doCleanups);self.case.seed()
        self.case.archive.append([Event('cdr','gen-recording',self.case.stamp,'CDR',dict(uniqueid='a',linkedid='a',recordingfile='synthetic.wav',duration=40))]);project_batch(self.case.archive)
        self.client=self.case.client(role='admin',menus=('reports','audit'),details=True)
        self.ident=self.client.get('/api/history/visits'+self.case.dates).json['rows'][0]['id']
        sources=AIJobs(self.case.root/'ai-jobs.sqlite3');sources.initialize()
        job=sources.create('test',self.ident,'gen-recording','8001','fa','source');sources.claim('synthetic')
        sources.complete(job['id'],'synthetic',dict(text='Synthetic source only.',segments=[dict(start=0,end=2,text='Synthetic source only.')]))
        self.body=dict(source_job_id=job['id'],language='en',request_key='generation')
        with self.client.session_transaction() as session:session['csrf_token']='test'
        self.headers={'X-CSRF-Token':'test'};self.path='/api/history/generative-jobs'

    def test_installer_returns_proof_and_rechecks_all_current_queues(self):
        with patch.dict('os.environ',{'SANEQUEUE_TEXT_ANALYSIS_ENABLED':'1'}),patch('sanequeue.api.reports.recording_ownership',return_value=('8001',)):
            made=self.client.post(self.path,json=self.body,headers=self.headers)
            self.assertEqual(made.status_code,202,made.json)
            ident=made.json['job']['id']
            self.assertEqual(self.client.get(self.path+'/'+ident).status_code,200)
            self.assertEqual(self.client.get(self.path+'?source_job_id='+self.body['source_job_id']).status_code,200)
        with patch('sanequeue.api.reports.recording_ownership',return_value=('8001','8002')):
            self.assertIn(self.client.get(self.path+'/'+ident).status_code,(403,404))
        denied=self.case.client(role='admin',menus=('reports','audit'),details=False)
        self.assertEqual(denied.get(self.path+'/'+ident).status_code,403)

if __name__=='__main__':unittest.main()
