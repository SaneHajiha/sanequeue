"""Beta 9 regressions: customer-survey PausedReason, AMI diagnostics, queue scope.

All tests use fakes. No real PBX connection or write action.
"""
import ast
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from qpanel.ami_connection_qa import classify_error
from qpanel.queue_policies import DEFAULT_REASONS, QueuePolicyStore
from qpanel.ami_live import parse_queue_events
from AMI_READONLY_TEST import ReadOnlyAMI

ROOT=Path(__file__).resolve().parents[1]

class Beta9SurveyTests(unittest.TestCase):
    def test_survey_explicit_outbound_and_not_ivr(self):
        reason=next(r for r in DEFAULT_REASONS if r['id']=='survey')
        self.assertIn('خروجی',reason['label'])
        self.assertIn('مشتریان',reason['label'])
        self.assertNotIn('IVR',reason['label'])
    def test_custom_reasons_per_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=QueuePolicyStore(Path(tmp)/'policy.json')
            self.assertEqual(store.validate_reason('8001','survey'),'survey')
            with self.assertRaises(ValueError):store.validate_reason('8001','unknown_reason')
            policy=store.export();policy['queues']['8001']=store.queue('8001')
            policy['queues']['8001']['pause_reasons'].append({'id':'manual_review','label':'تماس خروجی نظرسنجی'})
            store.replace(policy,visible_queues={'8001'})
            self.assertEqual(store.validate_reason('8001','manual_review'),'manual_review')
            self.assertNotIn('manual_review', [x['id'] for x in store.queue('8002')['pause_reasons']])
    def test_queue_member_paused_reason_stays_visible(self):
        ev=[{'Event':'QueueParams','Queue':'8001','Calls':'0'},
            {'Event':'QueueMember','Queue':'8001','Location':'Local/100@from-queue/n','Name':'test','Status':'1','Paused':'1','PausedReason':'survey'}]
        member=parse_queue_events(ev,'8001')['8001']['members']['Local/100@from-queue/n']
        self.assertEqual(member['PausedReason'],'survey')
        self.assertEqual(member['Paused'],'1')
    def test_diagnostic_classification_by_step(self):
        self.assertEqual(classify_error(PermissionError('secret and username should never echo'),'login'),'ami_authentication_rejected')
        self.assertEqual(classify_error(PermissionError('denied'),'queue_status'),'queue_status_permission_denied')
        self.assertEqual(classify_error(ValueError('missing'),'visibility'),'no_visible_queues_match')
        self.assertEqual(classify_error(socket.timeout(),'tcp'),'ami_timeout')
        self.assertEqual(classify_error(ConnectionRefusedError(),'tcp'),'tcp_connection_refused')
    def test_no_plaintext_secrets_in_frontend(self):
        js=(ROOT/'qpanel/themes/qpanel/static/js/operations.js').read_text(encoding='utf-8')
        html=(ROOT/'qpanel/themes/qpanel/templates/operations.html').read_text(encoding='utf-8')
        self.assertIn("'/api/ami/diagnose'",js)
        self.assertIn('id="ami-diagnose"',html)
        self.assertIn('id="pause-reason-dialog"',html)
        self.assertIn('id="survey-agent-banner"',html)
        for variable in ('defaultPauseReasons','policyState','loadPolicyEditor','showQueueSummary'):
            self.assertIn(variable,js)
        self.assertNotIn('INSECURE_SENTINEL_PLACEHOLDER_DO_NOT_USE',js)
        self.assertNotIn('INSECURE_SENTINEL_PLACEHOLDER_DO_NOT_USE',html)
    def test_launcher_version_and_port(self):
        self.assertEqual((ROOT/'VERSION').read_text(encoding='utf-8').strip(),'2.1.0-beta.9')
        start=(ROOT/'RUN_SANEQUEUE_18887_DEBUG.cmd').read_text(encoding='utf-8')
        self.assertIn('18887',start)
        self.assertIn('PYTHONUTF8=1',start)
        self.assertIn('pause-reason', (ROOT/'qpanel/themes/qpanel/static/css/operations.css').read_text(encoding='utf-8'))

class AMIConnectionStages(unittest.TestCase):
    @staticmethod
    def make_run_fn():
        """Extract pure diagnostic function to test with injected AMI mocks, no Flask imports."""
        path=ROOT/'demo_monitor.py'
        tree=ast.parse(path.read_text(encoding='utf-8'))
        node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_run_ami_diagnostic')
        return compile(ast.Module(body=[node],type_ignores=[]),str(path),'exec')
    def run_diagnostic(self, *, failure=None, omit_queue=False):
        class FakeSocketClient:
            def __init__(self,*a,**kw):
                if failure=='tcp': raise ConnectionRefusedError('secret NOT exportable')
            def login(self,*a):
                if failure=='login':raise PermissionError('secret NOT exportable')
            def queue_snapshot(self,*a,**kw):
                if failure=='queue_status':raise PermissionError('secret NOT exportable')
                return {'snapshot_complete':True,'queue_count':1}
            def close(self):pass
        def read_queue_data(*args):
            if failure=='live_parser':raise RuntimeError('private customer ID')
            return {'8001':{'Calls':0}}
        def filter_queue_data(q,visible):
            if omit_queue:return {}
            return q
        from qpanel.ami_targets import validate_target
        from qpanel.ami_connection_qa import safe_stage,classify_error
        env={'validate_target':validate_target,'ReadOnlyAMI':FakeSocketClient,'read_queue_data':read_queue_data,
             'filter_queue_data':filter_queue_data,'safe_stage':safe_stage,'classify_error':classify_error}
        exec(self.make_run_fn(),env)
        return env['_run_ami_diagnostic']({'host':'127.0.0.1','port':15038,'user':'sq','password':'SECRET_NOT_FOR_RESULTS','queue':'*','visible_queues':'8001'})
    def test_success_six_stages(self):
        r=self.run_diagnostic();self.assertTrue(r['ready']);self.assertEqual(len(r['stages']),6)
        self.assertNotIn('SECRET_NOT_FOR_RESULTS',str(r))
    def test_login_denied_only_login_fails(self):
        r=self.run_diagnostic(failure='login');self.assertEqual(r['error_code'],'ami_authentication_rejected')
        self.assertEqual(r['stages'][-1]['stage'],'login')
    def test_queue_status_denied(self):
        r=self.run_diagnostic(failure='queue_status');self.assertEqual(r['error_code'],'queue_status_permission_denied')
    def test_no_visible_queue_clear_message(self):
        r=self.run_diagnostic(omit_queue=True);self.assertEqual(r['error_code'],'no_visible_queues_match')
    def test_network_refused(self):
        r=self.run_diagnostic(failure='tcp');self.assertEqual(r['error_code'],'tcp_connection_refused')

if __name__=='__main__':unittest.main()
