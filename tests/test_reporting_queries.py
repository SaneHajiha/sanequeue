import json
from pathlib import Path
import tempfile
import unittest
import time
from unittest.mock import patch

from flask import Flask
from flask_login import LoginManager, UserMixin

from sanequeue.api.reports import install
from sanequeue.reporting.store import Archive, Event
from sanequeue.reporting.facts import project_batch
from sanequeue.reporting.queries import Scope, overview, visits, detail, agents
from sanequeue.reporting.audio import open_recording, byte_range


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = Archive(self.root / 'history.db', min_free_bytes=0)
        self.archive.initialize()
        for name,progress in (('sql',dict(cel_caught_up=True,cdr_caught_up=True)),('queue_log',dict(caught_up=True))):
            self.archive.append([],checkpoint_source='health:'+name,
                                checkpoint=dict(ok=True,checked=time.time(),progress=progress))
        self.stamp = 1792886400
        self.counter = 0

    def event(self, call, queue, kind, offset, values=(), agent='Local/100@from-queue/n'):
        self.counter += 1
        return Event('queue_log', str(self.counter), self.stamp + offset, kind,
                     dict(callid=call, queue=queue, agent=agent, values=list(values)))

    def seed(self):
        self.archive.append([
            self.event('a', '8001', 'ENTERQUEUE', 0, ['', '09123456789']),
            self.event('a', '8001', 'CONNECT', 10, ['10', 'agent-uid', '2']),
            self.event('a', '8001', 'COMPLETECALLER', 40, ['10', '30', '1']),
            self.event('b', '8002', 'ENTERQUEUE', 1, ['', '09999999999']),
            self.event('b', '8002', 'ABANDON', 31, ['1', '1', '30']),
        ])
        while project_batch(self.archive, limit=2)['processed']:
            pass
        self.scope = Scope(('8001',))

    def test_scoped_queue_metrics_and_segment_hangup(self):
        self.seed()
        result = overview(self.archive, self.scope, self.stamp, self.stamp + 100)
        self.assertEqual(len(result['queues']), 1)
        row = result['queues'][0]
        self.assertEqual((row['visits'], row['answered'], row['average_talk_seconds'], row['sla_percent']), (1, 1, 30, 100))
        page = visits(self.archive, self.scope, self.stamp, self.stamp + 100)
        evidence = detail(self.archive, self.scope, self.stamp, self.stamp + 100, page['rows'][0]['id'])
        self.assertEqual(evidence['visit']['segment_ended_by'], 'caller')
        self.assertIsNone(evidence['final_conversation_ended_by'])
        self.assertEqual(evidence['hangup_evidence'], 'queue_segment_only')
        self.assertEqual(len(evidence['timeline']), 3)
        agent = agents(self.archive, self.scope, self.stamp, self.stamp+100)['rows'][0]
        self.assertEqual((agent['answered'], agent['caller_segment_hangup'], agent['talk_seconds']), (1, 1, 30))
        hidden = visits(self.archive, Scope(('8002',)), self.stamp, self.stamp + 100)['rows'][0]
        self.assertIsNone(detail(self.archive, self.scope, self.stamp, self.stamp + 100, hidden['id']))

    def test_late_events_and_missing_evidence_remain_unknown(self):
        self.archive.append([self.event('a', '8001', 'COMPLETEAGENT', 40, ['10', '30'])])
        project_batch(self.archive)
        row = visits(self.archive, Scope(('8001',)), self.stamp, self.stamp + 100)['rows'][0]
        self.assertEqual(row['coverage'], 'missing_entry')
        self.archive.append([self.event('a', '8001', 'ENTERQUEUE', 0, ['', '09123456789']),
                             self.event('a', '8001', 'CONNECT', 10, ['10'])])
        project_batch(self.archive)
        row = visits(self.archive, Scope(('8001',)), self.stamp, self.stamp + 100)['rows'][0]
        self.assertEqual(row['coverage'], 'observed')
        self.assertEqual(row['segment_ended_by'], 'agent')
        self.assertEqual(project_batch(self.archive)['processed'], 0)
        self.assertEqual(visits(self.archive, Scope(()), self.stamp, self.stamp + 100)['rows'], [])
        self.assertEqual(visits(self.archive, Scope(('8001',), (), True), self.stamp, self.stamp + 100)['rows'], [])

    def test_projection_replays_latest_cdr_version_and_is_pbx_isolated(self):
        payload = dict(uniqueid='a', linkedid='a', src='200', dst='100', billsec='10', duration='20')
        first = Event('cdr', 'key', self.stamp, 'CDR', payload)
        self.archive.append([first])
        self.archive.append([Event('cdr', 'key', self.stamp, 'CDR', {**payload, 'billsec': '30'})])
        project_batch(self.archive)
        self.archive.append([first])
        project_batch(self.archive)
        with self.archive.reader() as db:
            self.assertEqual(db.execute('SELECT billsec FROM report_cdr').fetchone()[0], 30)
        other = Archive(self.archive.path, pbx='other', min_free_bytes=0)
        other.append([self.event('x', '8001', 'ENTERQUEUE', 0)])
        project_batch(other)
        self.assertEqual(visits(self.archive, Scope(('8001',)), self.stamp, self.stamp + 100)['rows'], [])

    def client(self, *, role='supervisor', menus=('reports',), details=False, denied=(), known=()):
        app = Flask(__name__)
        app.secret_key = 'synthetic-test-key'
        class User(UserMixin):
            id = 'test'
        manager = LoginManager(app)
        manager.user_loader(lambda ident: User())
        install(app, self.archive.path, role=lambda: role, sections=lambda: set(menus),
                can_queue=lambda q, action: q == '8001' and action not in denied and (action != 'caller_details' or details),
                own_interfaces=lambda: ('Local/100@from-queue/n',), recording_root=self.root / 'audio',
                known_agents=lambda: known)
        client = app.test_client()
        with client.session_transaction() as session:
            session.update(_user_id='test', _fresh=True)
        return client

    def test_analytics_api_scope_validation_and_no_sensitive_identifiers(self):
        self.seed()
        query = '?from=2026-10-24&to=2026-10-25&compare=1'
        response = self.client().get('/api/history/analytics'+query)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['totals']['visits'], 1)
        self.assertNotIn('09123456789', response.text)
        self.assertNotIn('09999999999', response.text)
        self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
        self.assertEqual(self.client(menus=()).get('/api/history/analytics'+query).status_code, 403)
        self.assertEqual(self.client().get('/api/history/analytics'+query+'&queue=8002').status_code, 403)
        self.assertEqual(self.client().get('/api/history/analytics'+query+'&sla=nan').status_code, 400)
        self.assertEqual(self.client().get('/api/history/analytics'+query.replace('compare=1','compare=maybe')).status_code, 400)

    def test_background_export_owner_csrf_and_permission_revocation(self):
        from sanequeue.reporting.export_jobs import JobStore, ExportWorker, Limits
        self.seed()
        store = JobStore(self.root/'export-jobs.sqlite3', self.root/'private-exports')
        store.initialize()
        denied = []
        client = self.client(details=True, denied=denied)
        with client.session_transaction() as session:
            session['csrf_token'] = 'test-csrf'
        query = '?from=2026-10-24&to=2026-10-25&lang=fa'
        path = '/api/history/export-jobs'
        self.assertEqual(client.post(path+query).status_code, 403)
        response = client.post(path+query, headers={'X-CSRF-Token': 'test-csrf'})
        self.assertEqual(response.status_code, 202)
        ident = response.json['id']
        self.assertNotIn('spec', response.json)
        self.assertEqual(client.get(path+'/'+ident+'/download').status_code, 404)
        worker = ExportWorker(store, self.archive, limits=Limits(min_free_bytes=0,max_load_per_cpu=0))
        self.assertEqual(worker.run_once()['state'], 'completed')
        download = client.get(path+'/'+ident+'/download')
        self.assertEqual(download.status_code, 200)
        self.assertIn('09123456789', download.data.decode('utf-8-sig'))
        self.assertEqual(download.headers['Cache-Control'], 'private, no-store')
        denied.append('caller_details')
        self.assertEqual(client.get(path+'/'+ident+'/download').status_code, 403)
        self.assertEqual(client.get(path).json['jobs'], [])
        self.assertEqual(self.client(role='agent').get(path).status_code, 403)
        self.assertEqual(client.get(path+'/'+'0'*32+'/download').status_code, 404)

    def test_export_service_does_not_initialize_on_http_request(self):
        self.seed()
        self.assertEqual(self.client().get('/api/history/export-jobs').status_code, 503)
        self.assertFalse((self.root/'export-jobs.sqlite3').exists())

    @property
    def dates(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        day = datetime.fromtimestamp(self.stamp, ZoneInfo('Asia/Tehran')).date().isoformat()
        return '?from=' + day + '&to=' + day

    def test_api_number_masking_scope_and_export(self):
        self.seed()
        client = self.client()
        response = client.get('/api/history/visits' + self.dates)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['rows'][0]['caller'], '0912***6789')
        self.assertNotIn('09999999999', response.text)
        self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
        self.assertEqual(self.client(menus=()).get('/api/history/overview' + self.dates).status_code, 403)
        export = client.get('/api/history/export.csv' + self.dates)
        self.assertEqual(export.status_code, 200)
        self.assertNotIn('09123456789', export.text)
        self.assertEqual(self.client(role='agent').get('/api/history/export.csv' + self.dates).status_code, 403)
        self.assertEqual(client.get('/api/history/overview?from=bad').status_code, 400)
        self.assertEqual(client.get('/api/history/overview' + self.dates + '&queue=8002').status_code, 403)
        self.assertEqual(self.client(denied=('report_export',)).get('/api/history/export.csv'+self.dates).status_code, 403)
        excel=client.get('/api/history/export.xlsx'+self.dates+'&lang=fa')
        self.assertEqual(excel.status_code,200)
        self.assertTrue(excel.data.startswith(b'PK'))
        self.assertEqual(self.client(denied=('report_export',)).get('/api/history/export.xlsx'+self.dates).status_code,403)

    def test_activity_api_enforces_menu_queue_and_agent_scope(self):
        self.archive.append([Event('activity',str(i),self.stamp,'ACTIVITY_INTERVAL',dict(queue=queue,agent=agent,
            canonical_agent=agent,state='paused',reason='survey',starts=self.stamp,ends=self.stamp+30,on_duty=False))
            for i,(queue,agent) in enumerate((('8001','Local/100@from-queue/n'),('8001','PJSIP/200'),('8002','PJSIP/300')))],
            checkpoint_source='activity_cache',checkpoint=dict(observed=self.stamp+40))
        project_batch(self.archive)
        for endpoint in ('activity','activity/intervals'):
            response=self.client(role='agent').get('/api/history/'+endpoint+self.dates)
            self.assertEqual(response.status_code,200)
            self.assertEqual({row['agent'] for row in response.json['rows']},{'Local/100@from-queue/n'})
            self.assertEqual(self.client(menus=()).get('/api/history/'+endpoint+self.dates).status_code,403)
            self.assertEqual(self.client().get('/api/history/'+endpoint+self.dates+'&queue=8002').status_code,403)
        bad=self.client().get('/api/history/activity/intervals'+self.dates+'&before_time=NaN&before_id=x')
        self.assertEqual(bad.status_code,400)

    def test_outbound_pause_api_masks_destination_and_enforces_scope(self):
        inventory=dict(observed_at=self.stamp,endpoints=[dict(technology='PJSIP',endpoint='100',category='extension'),
                                                         dict(technology='PJSIP',endpoint='provider',category='trunk')])
        self.archive.append([Event('activity','pause',self.stamp,'ACTIVITY_INTERVAL',dict(queue='8001',agent='Local/100@from-queue/n',
            state='paused',reason='survey',starts=self.stamp,ends=self.stamp+60,on_duty=False)),
            Event('cdr','outbound',self.stamp+10,'CDR',dict(channel='PJSIP/100-000000ab',dstchannel='PJSIP/provider-000000ac',
            uniqueid='outbound',dst='09123456789',duration=20,billsec=10,recordingfile='survey.wav'))],checkpoint_source='activity_cache',checkpoint=dict(observed=self.stamp+70))
        project_batch(self.archive,inventory=inventory)
        url='/api/history/outbound-pauses'+self.dates
        result=self.client(role='agent').get(url)
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json['rows'][0]['destination'],'0912***6789')
        self.assertNotIn('09123456789',result.text)
        self.assertEqual(self.client(details=True).get(url).json['rows'][0]['destination'],'09123456789')
        self.assertEqual(self.client(menus=()).get(url).status_code,403)
        self.assertEqual(self.client().get(url+'&queue=8002').status_code,403)
        self.assertFalse(result.json['rows'][0]['can_play'])
        audio=self.root/'audio';audio.mkdir();(audio/'survey.wav').write_bytes(b'RIFF0123456789')
        sound='/api/history/outbound-pauses/outbound/recording'+self.dates
        self.assertEqual(self.client(role='agent').get(sound).status_code,403)
        self.assertEqual(self.client(denied=('recording_play',)).get(sound).status_code,403)
        self.assertEqual(self.client(denied=('recording_download',)).get(sound+'&download=1').status_code,403)
        response=self.client().get(sound,headers={'Range':'bytes=4-7'})
        self.assertEqual(response.status_code,206);self.assertEqual(response.data,b'0123');response.close()
        self.assertEqual(self.client().get(sound.replace('outbound/recording','other/recording')).status_code,404)

    def test_audio_authorizes_before_open_supports_ranges_and_no_paths(self):
        self.seed()
        audio = self.root / 'audio'
        audio.mkdir()
        (audio / 'test.wav').write_bytes(b'RIFF0123456789')
        self.archive.append([Event('cdr', 'audio-id', self.stamp, 'CDR',
                                   dict(uniqueid='a', linkedid='a', duration=40,recordingfile='test.wav')),
                             Event('cdr', 'audio-second-leg', self.stamp, 'CDR',
                                   dict(uniqueid='second-leg', linkedid='a',duration=40, recordingfile='test.wav'))])
        project_batch(self.archive)
        ident = visits(self.archive, self.scope, self.stamp, self.stamp + 100)['rows'][0]['id']
        url = '/api/history/visits/' + ident + '/recordings/audio-id' + self.dates
        client = self.client()
        from sanequeue.reporting.recording_scope import ownership
        with patch('sanequeue.api.reports.recording_ownership',wraps=ownership) as proof:
            recording_refs = client.get('/api/history/visits/' + ident + self.dates).json['recordings']
            self.assertEqual(proof.call_count,1)
        self.assertEqual(len(recording_refs), 1)
        self.assertNotIn('recording', recording_refs[0])
        response = client.get(url, headers={'Range': 'bytes=4-7'})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.data, b'0123')
        response.close()
        self.assertEqual(client.get(url, headers={'Range': 'bytes=999-'}).status_code, 416)
        self.assertEqual(self.client(role='agent').get(url).status_code, 403)
        self.assertEqual(self.client(denied=('recording_play',)).get(url).status_code, 403)
        self.assertEqual(self.client(denied=('recording_download',)).get(url+'&download=1').status_code, 403)
        self.assertEqual(self.client(denied=('recording_play',)).get(url+'&download=1').status_code, 200)
        self.assertEqual(client.head(url).status_code, 200)
        audit_url = url.replace('?', '/access?')
        self.assertEqual(client.get(audit_url).status_code, 403)
        auditor = self.client(menus=('reports', 'audit'))
        audited = auditor.get(audit_url)
        self.assertEqual(audited.status_code, 200)
        self.assertEqual({row['action'] for row in audited.json['rows']}, {'play_request','download_request'})
        self.assertTrue(all(set(row)=={'id','user','timestamp','action'} for row in audited.json['rows']))
        self.assertNotIn('test.wav', audited.text)
        self.assertEqual(self.client(menus=('reports','audit'),denied=('recording_play','recording_download')).get(audit_url).status_code,403)
        with patch('sanequeue.api.reports.AuditStore.append',side_effect=__import__('sanequeue.reporting.access_audit',fromlist=['AuditUnavailable']).AuditUnavailable('recording_audit_unavailable')):
            self.assertEqual(client.get(url).status_code,503)
        self.assertEqual(client.get(url.replace('audio-id', 'unrelated')).status_code, 404)
        for path in ('../secret', '/etc/passwd', 'x\\secret', '\x00'):
            with self.assertRaises(ValueError):
                open_recording(audio, path)

    def test_audio_cannot_escape_queue_scope_through_linkedid_or_shared_filename(self):
        self.seed()
        self.archive.append([
            self.event('a','8002','ENTERQUEUE',22,['','200']),
            self.event('a','8002','CONNECT',23,['1'],'PJSIP/300'),
            self.event('a','8002','COMPLETECALLER',35,['1','12'],'PJSIP/300'),
            Event('cdr','private-leg',self.stamp+23,'CDR',dict(uniqueid='leg-b',linkedid='a',recordingfile='secret.wav'))])
        project_batch(self.archive)
        ident=visits(self.archive,self.scope,self.stamp,self.stamp+100)['rows'][0]['id']
        url='/api/history/visits/'+ident+self.dates
        self.assertEqual(self.client().get(url).json['recordings'],[])
        sound='/api/history/visits/'+ident+'/recordings/private-leg'+self.dates
        self.assertEqual(self.client().get(sound).status_code,403)
        # Same basename on another chain is ambiguous too; dated aliases must
        # not bypass permission by choosing the first visible reference.
        self.archive.append([Event('cdr','visible-leg',self.stamp,'CDR',dict(uniqueid='a',linkedid='a',recordingfile='2026/10/25/secret.wav'))])
        project_batch(self.archive)
        self.assertEqual(self.client().get(url).json['recordings'],[])

    def test_audio_rejects_symlinks_and_supports_suffix_ranges(self):
        audio=self.root/'audio'
        audio.mkdir()
        outside = self.root / 'secret.wav'
        outside.write_bytes(b'private')
        try:
            (audio / 'link.wav').symlink_to(outside)
        except OSError:
            pass
        else:
            with self.assertRaises((ValueError, OSError)):
                open_recording(audio, 'link.wav')
        self.assertEqual(byte_range('bytes=-4', 10), (6, 9, True))
        self.assertEqual(byte_range('bytes=4-', 10), (4, 9, True))

    def test_audio_waits_for_complete_fresh_projection_and_refuses_downstream_tail(self):
        from sanequeue.reporting.recording_scope import permitted
        self.seed()
        self.archive.append([Event('cdr','audio',self.stamp,'CDR',dict(uniqueid='a',linkedid='a',duration=40,recordingfile='voice.wav'))])
        allow=lambda q,cap:q=='8001'
        self.assertFalse(permitted(self.archive,'audio','recording_play',allow))
        project_batch(self.archive)
        self.assertTrue(permitted(self.archive,'audio','recording_play',allow))
        self.archive.append([],checkpoint_source='queue_log',checkpoint=dict(last_rotation_detected=self.stamp+90,
            coverage_gaps=[[self.stamp+50,self.stamp+90]]))
        self.assertTrue(permitted(self.archive,'audio','recording_play',allow))
        self.archive.append([],checkpoint_source='queue_log',checkpoint=dict(last_rotation_detected=self.stamp+90,
            coverage_gaps=[[self.stamp+20,self.stamp+90]]))
        self.assertFalse(permitted(self.archive,'audio','recording_play',allow))
        self.archive.append([],checkpoint_source='queue_log',checkpoint={})
        self.archive.append([],checkpoint_source='health:sql',checkpoint=dict(ok=True,checked=time.time()-100,
            progress=dict(cel_caught_up=True,cdr_caught_up=True)))
        self.assertFalse(permitted(self.archive,'audio','recording_play',allow))
        self.archive.append([],checkpoint_source='health:sql',checkpoint=dict(ok=True,checked=time.time(),
            progress=dict(cel_caught_up=True,cdr_caught_up=True)))
        # A CDR extending past the known queue end cannot be authorized while
        # a transfer event is still missing, even when health looks current.
        self.archive.append([Event('cdr','audio',self.stamp,'CDR',dict(uniqueid='a',linkedid='a',duration=80,recordingfile='voice.wav'))])
        project_batch(self.archive)
        self.assertFalse(permitted(self.archive,'audio','recording_play',allow))
        # A gap before the known visit can hide an earlier queue in the same
        # recording; its CDR span, not just visit time, must also be checked.
        self.archive.append([],checkpoint_source='queue_log',checkpoint=dict(coverage_gaps=[[self.stamp-20,self.stamp-10]]))
        self.archive.append([Event('cdr','audio',self.stamp-30,'CDR',dict(uniqueid='a',linkedid='a',duration=70,recordingfile='voice.wav'))])
        project_batch(self.archive)
        self.assertFalse(permitted(self.archive,'audio','recording_play',allow))

    def test_export_neutralizes_formulas_and_reports_missing_archive(self):
        self.archive.append([self.event('a','8001','ENTERQUEUE',0,agent='=formula'),
                             self.event('a','8001','COMPLETEAGENT',10,['0','10'],agent='=formula')])
        project_batch(self.archive)
        response=self.client().get('/api/history/export.csv'+self.dates)
        self.assertEqual(response.status_code,200)
        self.assertIn("'=formula",response.text)
        self.archive.path.unlink()
        response=self.client().get('/api/history/overview'+self.dates)
        self.assertEqual(response.status_code,503)
        self.assertEqual(response.json['error'],'report_archive_not_initialized')

    def test_keyset_and_transfer_dont_invent_conversation_hangup(self):
        self.archive.append([self.event('a', '8001', 'ENTERQUEUE', 0), self.event('a', '8001', 'CONNECT', 5, ['5']),
                             self.event('a', '8001', 'ATTENDEDTRANSFER', 15, ['method', 'a', 'b']),
                             self.event('b', '8001', 'ENTERQUEUE', 0)])
        project_batch(self.archive)
        first = visits(self.archive, Scope(('8001',)), self.stamp, self.stamp + 100, limit=1)
        second = visits(self.archive, Scope(('8001',)), self.stamp, self.stamp + 100, limit=1, before=first['next'])
        self.assertNotEqual(first['rows'][0]['id'], second['rows'][0]['id'])
        transferred = next(r for r in first['rows'] + second['rows'] if r['outcome'] == 'transferred')
        self.assertIsNone(transferred['talk_seconds'])
        self.assertIsNone(transferred['segment_ended_by'])
        self.assertEqual(overview(self.archive, Scope(('8001',)), self.stamp, self.stamp + 100)['queues'][0]['transferred'], 1)

    def test_completion_after_transfer_is_not_a_second_visit(self):
        self.archive.append([
            self.event('a', '8001', 'ENTERQUEUE', 0),
            self.event('a', '8001', 'CONNECT', 1, ['1']),
            self.event('a', '8001', 'TRANSFER', 36, ['300']),
        ])
        project_batch(self.archive)
        self.archive.append([self.event('a', '8001', 'COMPLETEAGENT', 303, ['1', '302', '1'])])
        project_batch(self.archive)
        rows = visits(self.archive, Scope(('8001',)), self.stamp, self.stamp + 400)['rows']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['outcome'], 'transferred')
        self.assertIsNone(rows[0]['segment_ended_by'])
        self.assertIsNone(rows[0]['talk_seconds'])
        self.assertEqual(rows[0]['ended'], self.stamp + 36)
        # A real second queue entry must still produce a separate visit.
        self.archive.append([
            self.event('a', '8001', 'ENTERQUEUE', 310),
            self.event('a', '8001', 'ABANDON', 320, ['1', '1', '10']),
        ])
        project_batch(self.archive)
        self.assertEqual(len(visits(self.archive, Scope(('8001',)), self.stamp, self.stamp + 400)['rows']), 2)

    def test_late_cel_attended_transfer_corrects_queue_completion(self):
        # Issabel may write numeric membername rather than Local/interface.
        self.archive.append([
            self.event('a', '8001', 'ENTERQUEUE', 0),
            self.event('a', '8001', 'CONNECT', 10, ['10'], agent='100'),
            self.event('a', '8001', 'COMPLETEAGENT', 40, ['10', '30'], agent='100'),
        ])
        project_batch(self.archive)
        self.scope = Scope(('8001',))
        transfer = dict(uniqueid='consult-leg', linkedid='a', channame='PJSIP/100-00000abc')
        # Another endpoint in the same conversation is not evidence that
        # this queue agent transferred the caller.
        self.archive.append([Event('cel', 'unrelated-transfer', self.stamp+20, 'ATTENDEDTRANSFER',
                                   {**transfer, 'channame': 'PJSIP/300-00000abc'})])
        project_batch(self.archive)
        self.assertEqual(visits(self.archive, self.scope, self.stamp, self.stamp+100)['rows'][0]['outcome'], 'answered')
        self.archive.append([Event('cel', 'transfer', self.stamp+25, 'ATTENDEDTRANSFER', transfer)])
        project_batch(self.archive)
        row = visits(self.archive, self.scope, self.stamp, self.stamp+100)['rows'][0]
        self.assertEqual((row['outcome'], row['ended']), ('transferred', self.stamp+25))
        self.assertIsNone(row['talk_seconds'])
        self.assertIsNone(row['segment_ended_by'])
        evidence = detail(self.archive, self.scope, self.stamp, self.stamp+100, row['id'])
        self.assertEqual(evidence['timeline'][-1]['kind'], 'ATTENDEDTRANSFER')
        self.assertEqual(evidence['timeline'][-1]['source'], 'cel')
        self.assertEqual(overview(self.archive, self.scope, self.stamp, self.stamp+100)['queues'][0]['answered'], 1)
        # Replaying the derived projection must produce the same result.
        with self.archive.writer() as db:db.execute('UPDATE report_projection SET after_id=0')
        while project_batch(self.archive, limit=2)['processed']:pass
        self.assertEqual(visits(self.archive, self.scope, self.stamp, self.stamp+100)['rows'][0], row)

    def test_projection_upgrade_replays_derived_facts_without_losing_evidence(self):
        self.seed()
        before = self.archive.status()['counters']['events']
        with self.archive.writer() as db:
            db.execute('UPDATE report_visits SET talk_seconds=999')
            db.execute('DELETE FROM report_projection_version')
        first = project_batch(self.archive, limit=1)
        self.assertEqual(first['processed'], 1)
        while project_batch(self.archive, limit=2)['processed']:pass
        row = visits(self.archive, self.scope, self.stamp, self.stamp+100)['rows'][0]
        self.assertEqual(row['talk_seconds'], 30)
        self.assertEqual(self.archive.status()['counters']['events'], before)


if __name__ == '__main__':
    unittest.main()
