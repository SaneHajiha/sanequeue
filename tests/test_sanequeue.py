import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch
from qpanel.reporting import QueueReports


class ReportsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = os.path.join(self.tmp.name, 'queue_log')
        self.reports = QueueReports(os.path.join(self.tmp.name, 'reports.db'))
        self.ts = int(datetime(2026, 1, 2, 12).timestamp())
        with open(self.log, 'w') as f:
            f.write('{}|a|sales|NONE|ENTERQUEUE||private-number\n'.format(self.ts))
            f.write('{}|a|sales|SIP/100|CONNECT|10|a|0\n'.format(self.ts + 10))
            f.write('{}|a|sales|SIP/100|COMPLETEAGENT|10|40|1\n'.format(self.ts + 50))
            f.write('{}|b|private|NONE|ENTERQUEUE||private-number\n'.format(self.ts))

    def tearDown(self):
        self.tmp.cleanup()

    def test_incremental_scope_and_kpi(self):
        self.assertTrue(self.reports.ingest(self.log)['caught_up'])
        self.reports.ingest(self.log)
        result = self.reports.report(self.ts, self.ts + 100, ['sales'])
        self.assertEqual(result['totals']['entered'], 1)
        self.assertEqual(result['totals']['answered'], 1)
        self.assertEqual(result['totals']['average_wait'], 10)
        self.assertEqual(result['totals']['average_talk'], 40)
        self.assertEqual(result['totals']['service_level'], 100)
        self.assertEqual(len(result['rows']), 2)
        with self.reports.connect() as db:
            self.assertNotIn('private-number', str(db.execute('SELECT * FROM events').fetchall()))

    def test_partial_line_and_rotation(self):
        self.reports.ingest(self.log)
        with open(self.log, 'a') as f:
            f.write('{}|c|sales|NONE|ENTERQUEUE||'.format(self.ts + 60))
        self.assertFalse(self.reports.ingest(self.log)['caught_up'])
        with open(self.log, 'a') as f:
            f.write('number\n')
        self.reports.ingest(self.log)
        os.rename(self.log, self.log + '.1')
        with open(self.log, 'w') as f:
            f.write('{}|d|sales|NONE|ENTERQUEUE||number\n'.format(self.ts + 70))
        self.reports.ingest(self.log)
        result = self.reports.report(self.ts, self.ts + 100, ['sales'])
        self.assertEqual(result['totals']['entered'], 3)

    def test_empty_denominators(self):
        result = self.reports.report(0, 1, ['none'])
        self.assertIsNone(result['totals']['service_level'])
        self.assertIsNone(result['totals']['average_wait'])


class AccessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ['QPANEL_CONFIG_FILE'] = os.path.join(os.path.dirname(__file__), 'data/configs/config_default.ini')
        with patch('qpanel.backend.Backend._connect'):
            from qpanel import app
        cls.module = app
        cls.app = app.app

    def setUp(self):
        self.client = self.app.test_client()
        self.original = self.module.cfg.config
        self.original_language = self.module.cfg.language
        self.module.cfg.language = 'en'
        self.old_app_config = dict(self.app.config)
        self.temp = tempfile.TemporaryDirectory()
        from qpanel.queue_policies import QueuePolicyStore
        self.store = QueuePolicyStore(os.path.join(self.temp.name, 'policy.json'))
        self.store.replace({'queues': {'sales': {}}, 'supervisors': {'supervisor': {'queues': ['sales'], 'actions': ['view','pause','priority','hangup','monitor','caller_details']}, 'viewer': {'queues': ['sales'], 'actions': ['view']}}})
        self.app.config['SANEQUEUE_POLICY_STORE'] = self.store
        self.app.config['SANEQUEUE_TEST_CONTROL_GUARD'] = lambda req: self.module.cfg.get_value_set_default('sanequeue','demo_mode','false') != 'true'
        self.app.config['SANEQUEUE_TEST_CONTROLS_STATUS'] = lambda: True
        import configparser
        config = configparser.ConfigParser()
        config.read_dict({'users': {'viewer': 'password', 'supervisor': 'password'}, 'roles': {'supervisor': 'supervisor'}, 'sanequeue': {'reports_enabled': 'true'}})
        self.module.cfg.config = config
        self.fake = {'sales': {'members': {'SIP/100': {'Status': '1', 'Paused': '0'}}, 'entries': {}, 'Calls': '0'}}
        self.mock = patch.object(self.module.backend, 'get_data_queues', return_value=self.fake)
        self.mock.start()
        self.module.backend.last_error = False

    def tearDown(self):
        self.mock.stop()
        self.module.cfg.config = self.original
        self.module.cfg.language = self.original_language
        self.app.config.clear(); self.app.config.update(self.old_app_config)
        self.temp.cleanup()

    def login(self, name):
        with self.client.session_transaction() as session:
            session['_user_id'] = name
            session['_fresh'] = True
            session['csrf_token'] = 'test-csrf'

    def test_login_form_rejects_incorrect_password(self):
        response = self.client.get('/login')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'name="username"', response.data)
        self.assertIn(b'name="pw"', response.data)
        response = self.client.post('/login', data={'username': 'supervisor', 'pw': 'wrong'})
        self.assertEqual(response.status_code, 401)
        self.assertIn(b'Incorrect username or password', response.data)

    def test_login_accepts_hashed_password_and_redirects_to_dashboard(self):
        from werkzeug.security import generate_password_hash
        self.module.cfg.config.set('users', 'supervisor', generate_password_hash('local-test-secret'))
        response = self.client.post('/login', data={'username': 'supervisor', 'pw': 'local-test-secret'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, '/')
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_unsupported_language_is_rejected(self):
        self.login('viewer')
        self.assertEqual(self.client.get('/lang/unsupported').status_code, 400)

    def test_anonymous_report_requires_login(self):
        self.assertEqual(self.client.get('/api/reports').status_code, 302)
        self.assertEqual(self.client.get('/stats').status_code, 410)
        self.assertEqual(self.client.post('/hangup', data={'username': 'supervisor', 'pw': 'wrong', 'channel': 'SIP/100'}).status_code, 410)

    def test_viewer_cannot_control(self):
        self.login('viewer')
        self.assertEqual(self.client.post('/api/members/pause', data={'queue': 'sales', 'agent': 'SIP/100', 'paused': 'true'}, headers={'X-CSRF-Token': 'test-csrf'}).status_code, 403)

    def test_csrf_and_queue_scope(self):
        self.login('supervisor')
        self.assertEqual(self.client.post('/api/members/pause').status_code, 400)
        self.assertEqual(self.client.post('/api/members/pause', data={'queue': 'private', 'agent': 'SIP/100'}, headers={'X-CSRF-Token': 'test-csrf'}).status_code, 403)
        self.assertEqual(self.client.post('/hangup', data={'queue': 'sales', 'channel': 'SIP/private'}, headers={'X-CSRF-Token': 'test-csrf'}).status_code, 410)

    def test_live_failure_is_not_zero(self):
        self.login('viewer')
        self.module.backend.last_error = True
        self.assertEqual(self.client.get('/api/operations').status_code, 503)

    def test_dashboard_and_date_validation(self):
        self.login('viewer')
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(self.client.get('/api/reports?from=not-a-date').status_code, 400)

    def test_priority_uses_visible_caller_and_immediate(self):
        self.login('supervisor')
        self.fake['sales']['entries'] = {'call': {'Channel': 'PJSIP/caller-1', 'Priority': '4'}}
        with patch.object(self.module.backend, '_connect') as connect:
            manager = connect.return_value.connection
            manager._translate_response.return_value = {'Response': 'Success'}
            response = self.client.post('/api/control', data={'action': 'first', 'queue': 'sales', 'channel': 'PJSIP/caller-1'}, headers={'X-CSRF-Token': 'test-csrf'})
            self.assertEqual(response.status_code, 202)
            action, fields = manager._write_action.call_args.args
            self.assertEqual(action, 'QueueChangePriorityCaller')
            self.assertEqual({k:v for k,v in fields.items() if k != 'ActionID'}, {'Queue': 'sales', 'Caller': 'PJSIP/caller-1', 'Priority': '5', 'Immediate': 'yes'})
            response = self.client.post('/api/control', data={'action': 'hangup', 'queue': 'sales', 'channel': 'PJSIP/private-1'}, headers={'X-CSRF-Token': 'test-csrf'})
            self.assertEqual(response.status_code, 409)

    def test_staffing_and_supervisor_destination(self):
        self.login('supervisor')
        self.module.cfg.config.set('sanequeue', 'minimum_ready_percent', '50')
        with patch.object(self.module.backend, '_connect') as connect:
            response = self.client.post('/api/members/pause', data={'queue': 'sales', 'agent': 'SIP/100', 'paused': 'true'}, headers={'X-CSRF-Token': 'test-csrf'})
            self.assertEqual(response.status_code, 409)
            connect.assert_not_called()
            self.fake['sales']['members']['SIP/100']['InCall']='1'
            response = self.client.post('/api/control', data={'queue': 'sales', 'agent': 'SIP/100', 'action': 'spy', 'destination': 'PJSIP/999'}, headers={'X-CSRF-Token': 'test-csrf'})
            self.assertEqual(response.status_code, 403)
            connect.assert_not_called()

    def test_successful_pause_returns_response_with_policy_store(self):
        self.login('supervisor')
        with patch.object(self.module.backend, '_connect') as connect:
            manager=connect.return_value.connection
            manager._translate_response.return_value={'Response':'Success'}
            response=self.client.post('/api/members/pause',data={'queue':'sales','agent':'SIP/100','paused':'false'},headers={'X-CSRF-Token':'test-csrf'})
            self.assertEqual(response.status_code,202)
            self.assertTrue(response.get_json()['ok'])

    def test_supervision_modes_use_assigned_phone_and_explicit_caller_id(self):
        self.login('supervisor')
        self.module.cfg.config.add_section('supervisor_extensions')
        self.module.cfg.config.set('supervisor_extensions','supervisor','PJSIP/300')
        self.fake['sales']['members']['SIP/100']['InCall']='1'
        for action,mode in [('spy','q'),('whisper','qw'),('barge','qB')]:
            with self.subTest(action=action), patch.object(self.module.backend,'_connect') as connect:
                manager=connect.return_value.connection
                manager._translate_response.return_value={'Response':'Success'}
                response=self.client.post('/api/control',data={'queue':'sales','agent':'SIP/100','action':action},headers={'X-CSRF-Token':'test-csrf'})
                self.assertEqual(response.status_code,202)
                command,fields=manager._write_action.call_args.args
                self.assertEqual(command,'Originate')
                self.assertEqual(fields['Channel'],'PJSIP/300')
                self.assertEqual(fields['Data'],'SIP/100,'+mode)
                self.assertEqual(fields['CallerID'],'SaneQueue <300>')
                self.assertEqual(fields['Timeout'],'60000')

    def test_ami_rejection_is_reported(self):
        from Asterisk.Manager import ActionFailed
        self.login('supervisor')
        with patch.object(self.module.backend, '_connect') as connect:
            connect.return_value.connection._translate_response.side_effect = ActionFailed('test rejection')
            response = self.client.post('/api/members/pause', data={'queue': 'sales', 'agent': 'SIP/100', 'paused': 'false'}, headers={'X-CSRF-Token': 'test-csrf'})
            self.assertEqual(response.status_code, 502)

    def test_monitoring_tabs_render_without_reports(self):
        self.login('supervisor')
        response = self.client.get('/operations')
        self.assertEqual(response.status_code, 200)
        text = response.get_data(as_text=True)
        for marker in ('id="queues-view"', 'id="calls-view"', 'id="active-call-rows"', 'id="queue-focus-cards"', 'id="waiting-room-rows"'):
            self.assertIn(marker, text)
        self.assertNotIn('data-view="reports"', text)
        self.assertNotIn('id="reports-view"', text)
        from qpanel import __version__
        self.assertIn(__version__, text)

    def test_optional_channel_metadata_is_scoped(self):
        self.login('supervisor')
        self.fake['sales']['members'] = {'PJSIP/100': {'Name': 'Test Agent', 'Status': '2', 'Paused': '0', 'StateInterface': 'PJSIP/100'}}
        with patch.object(self.module.backend, '_connect') as connect:
            connect.return_value.connection.CoreShowChannels.return_value = [
                {'Channel': 'PJSIP/100-000001', 'ChannelStateDesc': 'Up', 'Duration': '00:00:29', 'CallerIDNum': '02100000000'},
                {'Channel': 'PJSIP/PRIVATE-000001', 'ChannelStateDesc': 'Up', 'Duration': '00:08:00', 'CallerIDNum': 'hidden'}]
            response = self.client.get('/api/operations')
        self.assertEqual(response.status_code, 200)
        member = response.json['queues']['sales']['members']['PJSIP/100']
        self.assertEqual(member['LiveDuration'], '00:00:29')
        self.assertEqual(member['LiveChannelState'], 'Up')
        self.assertEqual(member['LiveChannel'], 'PJSIP/100-000001')
        self.assertNotIn('PRIVATE', str(response.json))

    def test_preview_blocks_direct_control_requests(self):
        self.login('supervisor')
        self.module.cfg.config.set('sanequeue', 'demo_mode', 'true')
        response = self.client.post('/api/control', data={'queue':'sales','action':'remove','agent':'SIP/100'}, headers={'X-CSRF-Token':'test-csrf'})
        self.assertEqual(response.status_code, 403)
        response = self.client.post('/api/members/pause', data={'queue':'sales','agent':'SIP/100','paused':'true'}, headers={'X-CSRF-Token':'test-csrf'})
        self.assertEqual(response.status_code, 403)

    def test_demonstration_mode_is_declared(self):
        self.login('supervisor')
        self.module.cfg.config.set('sanequeue', 'demo_mode', 'true')
        response = self.client.get('/operations')
        self.assertEqual(response.status_code, 200)
        self.assertIn('"demo_mode": true', response.get_data(as_text=True))

    def test_python3_queue_scope(self):
        data = {'allowed': {}, 'private': {}}
        with patch.object(self.module.backend.config, 'queue_enables_for_username', return_value=['allowed']):
            self.assertEqual(self.module.backend.filter_data_for_user(data, 'viewer'), {'allowed': {}})


if __name__ == '__main__':
    unittest.main()
