import json
from pathlib import Path
import tempfile
import unittest

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

    def client(self, *, role='supervisor', menus=('reports',), details=False, denied=()):
        app = Flask(__name__)
        app.secret_key = 'synthetic-test-key'
        class User(UserMixin):
            id = 'test'
        manager = LoginManager(app)
        manager.user_loader(lambda ident: User())
        install(app, self.archive.path, role=lambda: role, sections=lambda: set(menus),
                can_queue=lambda q, action: q == '8001' and action not in denied and (action != 'caller_details' or details),
                own_interfaces=lambda: ('Local/100@from-queue/n',), recording_root=self.root / 'audio')
        client = app.test_client()
        with client.session_transaction() as session:
            session.update(_user_id='test', _fresh=True)
        return client

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

    def test_audio_authorizes_before_open_supports_ranges_and_no_paths(self):
        self.seed()
        audio = self.root / 'audio'
        audio.mkdir()
        (audio / 'test.wav').write_bytes(b'RIFF0123456789')
        self.archive.append([Event('cdr', 'audio-id', self.stamp, 'CDR',
                                   dict(uniqueid='a', linkedid='a', recordingfile='test.wav'))])
        project_batch(self.archive)
        ident = visits(self.archive, self.scope, self.stamp, self.stamp + 100)['rows'][0]['id']
        url = '/api/history/visits/' + ident + '/recordings/audio-id' + self.dates
        client = self.client()
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
        self.assertEqual(client.get(url.replace('audio-id', 'unrelated')).status_code, 404)
        for path in ('../secret', '/etc/passwd', 'x\\secret', '\x00'):
            with self.assertRaises(ValueError):
                open_recording(audio, path)
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


if __name__ == '__main__':
    unittest.main()
