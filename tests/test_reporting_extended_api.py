"""Cross-module UI adapter boundaries: quality, journey and local text access."""
import unittest
import builtins
import importlib.util
import io
import wave
from unittest.mock import patch
from tests import test_reporting_queries as fixtures
from sanequeue.reporting.store import Event
from sanequeue.reporting.facts import project_batch
from tests.test_reporting_audio_duration import mp3_metadata,ogg_metadata


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

    def test_historic_ai_job_identity_ignores_ui_filters_but_rechecks_current_permissions(self):
        case=self.case
        case.archive.append([Event('cdr','historic-audio',case.stamp,'CDR',dict(uniqueid='a',linkedid='a',
            recordingfile='private.wav',duration=40,billsec=30,disposition='ANSWERED'))])
        project_batch(case.archive)
        url=self.url+'/recordings/historic-audio/ai'+case.dates
        with patch('sanequeue.api.reports.recording_ownership',return_value=('8001',)),\
             patch.dict('os.environ',{'SANEQUEUE_REPORT_AI_ENABLED':'1'}):
            created=self.client.post(url,json={'request_key':'historical'},headers=self.headers)
            self.assertEqual(created.status_code,202,created.json)
            job_url='/api/history/ai-jobs/'+created.json['job']['id']
            for query in ('','?from=2000-01-01&to=2000-01-01','?queue=8002'):
                with self.subTest(query=query):
                    response=self.client.get(job_url+query)
                    self.assertEqual(response.status_code,200,response.json)
                    self.assertEqual(response.json['job']['id'],created.json['job']['id'])
            for denied in ('recording_play','caller_details','view'):
                revoked=case.client(menus=('reports','audit'),details=True,denied=(denied,))
                self.assertIn(revoked.get(job_url).status_code,(403,404))
            missing_audit=case.client(menus=('reports',),details=True)
            self.assertEqual(missing_audit.get(job_url).status_code,403)
            self.assertEqual(self.client.post(job_url,headers=self.headers).status_code,200)

    def test_quality_timed_notes_use_bounded_wav_mp3_ogg_metadata_and_fail_closed(self):
        case=self.case;audio=case.root/'audio';audio.mkdir(exist_ok=True)
        buffer=io.BytesIO()
        with wave.open(buffer,'wb') as stream:
            stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(8000);stream.writeframes(bytes(32000))
        form=self.client.post('/api/history/quality/forms'+case.dates,headers=self.headers,
            json=dict(name='Timed QA',criteria=[dict(id='accuracy',label='Accuracy',max_score=5,weight=100)])).json['form']
        url=self.url+'/reviews'+case.dates
        def payload(key,notes):
            return dict(form_id=form['id'],form_version=form['version'],scores={'accuracy':4},comment='',
                request_key=key,recording_id='qa-audio',notes=notes)
        with patch('sanequeue.api.reports.recording_ownership',return_value=('8001',)):
            for extension,data,offset in [('wav',buffer.getvalue(),1),('mp3',mp3_metadata(),.05),('ogg',ogg_metadata(),.5)]:
                with self.subTest(codec=extension):
                    name='qa.'+extension;(audio/name).write_bytes(data)
                    case.archive.append([Event('cdr','qa-audio',case.stamp,'CDR',dict(uniqueid='a',linkedid='a',
                        recordingfile=name,duration=40,billsec=30,disposition='ANSWERED'))]);project_batch(case.archive)
                    response=self.client.post(url,headers=self.headers,json=payload(extension,[dict(offset_seconds=offset,text='Review note')]))
                    supported=extension=='wav' or importlib.util.find_spec('mutagen') is not None
                    self.assertEqual(response.status_code,201 if supported else 415,response.json)
            # No parser is not a successful zero-duration guess; no review is saved.
            original=builtins.__import__
            def unavailable(name,*args,**kwargs):
                if name=='mutagen' or name.startswith('mutagen.'):raise ImportError('not installed')
                return original(name,*args,**kwargs)
            before=len(self.client.get(url).json['rows'])
            with patch('builtins.__import__',side_effect=unavailable):
                response=self.client.post(url,headers=self.headers,json=payload('missing-parser',[dict(offset_seconds=0,text='Not saved')]))
            self.assertEqual(response.status_code,415,response.json)
            self.assertEqual(response.json['error'],'recording_duration_parser_unavailable')
            self.assertEqual(len(self.client.get(url).json['rows']),before)
            # Linking a recording without timed notes never probes its duration.
            with patch('sanequeue.api.reports.duration_seconds',side_effect=AssertionError('unneeded probe')):
                response=self.client.post(url,headers=self.headers,json=payload('no-notes',[]))
            self.assertEqual(response.status_code,201,response.json)


if __name__=='__main__':unittest.main()
