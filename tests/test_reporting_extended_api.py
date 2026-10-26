"""Cross-module UI adapter boundaries: quality, journey and local text access."""
import unittest
from unittest.mock import patch
from tests import test_reporting_queries as fixtures
from sanequeue.reporting.store import Event
from sanequeue.reporting.facts import project_batch


class ExtendedAPITests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.ReportTests();self.case.setUp();self.addCleanup(self.case.doCleanups);self.case.seed()
        self.client=self.case.client(role='admin',menus=('reports','audit'),details=True)
        with self.client.session_transaction() as session:session['csrf_token']='test'
        page=self.client.get('/api/history/visits'+self.case.dates).json
        self.ident=page['rows'][0]['id'];self.url='/api/history/visits/'+self.ident
        self.headers={'X-CSRF-Token':'test'}

    def test_quality_csrf_role_scope_and_frozen_form_review(self):
        form=dict(name='Phone quality',criteria=[dict(id='accuracy',label='Accuracy',max_score=5,weight=100)])
        path='/api/history/quality/forms'+self.case.dates
        self.assertEqual(self.client.post(path,json=form).status_code,403)
        self.assertEqual(self.case.client().get(path).status_code,403)
        created=self.client.post(path,json=form,headers=self.headers)
        self.assertEqual(created.status_code,201,created.json)
        first=created.json['form']
        body=dict(form_id=first['id'],form_version=first['version'],scores={'accuracy':4},comment='<plain text>',request_key='one')
        path=self.url+'/reviews'+self.case.dates
        response=self.client.post(path,json=body,headers=self.headers)
        self.assertEqual(response.status_code,201,response.json)
        self.assertEqual(response.json['review']['score'],80)
        self.assertEqual(self.client.post(path,json=body,headers=self.headers).json['review']['id'],response.json['review']['id'])
        notes={**body,'request_key':'two','notes':[dict(offset_seconds=0,text='not authorized audio')]}
        self.assertEqual(self.client.post(path,json=notes,headers=self.headers).status_code,403)
        self.assertEqual(len(self.client.get(path).json['rows']),1)
        masked=self.case.client(role='supervisor',menus=('reports','audit'))
        redacted=masked.get(path)
        self.assertEqual(redacted.status_code,200)
        self.assertTrue(redacted.json['rows'][0]['content_redacted'])
        self.assertEqual(redacted.json['rows'][0]['comment'],'')
        self.assertEqual(masked.post(path,json=body,headers=self.headers).status_code,403)
        self.assertEqual(self.client.get(path+'&queue=8002').status_code,403)
        summary=self.client.get('/api/history/quality/summary'+self.case.dates)
        self.assertEqual(summary.status_code,200)

    def test_journey_masks_numbers_and_does_not_grant_audio(self):
        masked=self.case.client()
        response=masked.get(self.url+'/journey'+self.case.dates)
        self.assertEqual(response.status_code,200,response.json)
        self.assertNotIn('09123456789',response.get_data(as_text=True))
        self.assertNotIn('private',response.get_data(as_text=True))
        self.assertFalse(response.json['coverage']['complete_conversation'])
        self.assertFalse(response.json['audio_granted'])

    def test_ai_creation_requires_current_audio_number_and_audit_permissions(self):
        case=self.case
        case.archive.append([Event('cdr','audio',case.stamp,'CDR',dict(uniqueid='a',linkedid='a',
            recordingfile='private.wav',duration=40,billsec=30,disposition='ANSWERED'))])
        project_batch(case.archive)
        url=self.url+'/recordings/audio/ai'+case.dates
        for client in (case.client(),case.client(menus=('reports','audit')),
                       case.client(menus=('reports','audit'),details=True,denied=('recording_play',))):
            self.assertEqual(client.get(url).status_code,403)
        with patch('sanequeue.api.reports.recording_ownership',return_value=('8001',)),patch.dict('os.environ',{'SANEQUEUE_REPORT_AI_ENABLED':'1'}):
            client=case.client(menus=('reports','audit'),details=True)
            with client.session_transaction() as session:session['csrf_token']='test'
            self.assertEqual(client.post(url,json={'request_key':'one'}).status_code,403)
            response=client.post(url,json={'request_key':'one'},headers=self.headers)
            self.assertEqual(response.status_code,202,response.json)
            ident=response.json['job']['id']
            self.assertEqual(client.get('/api/history/ai-jobs/'+ident+case.dates).status_code,200)
            self.assertTrue(client.post('/api/history/ai-jobs/'+ident+case.dates,headers=self.headers).json['cancelled'])


if __name__=='__main__':unittest.main()
