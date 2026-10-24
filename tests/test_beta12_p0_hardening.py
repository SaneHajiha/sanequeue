"""Beta12 P0/P1 checks; no PBX credentials or network needed."""
import unittest
from pathlib import Path
from qpanel.privacy import public_queue_snapshot
from qpanel.test_control_gate import TestControlGate, ALLOWED_ACTIONS
from qpanel.ami_live import parse_queue_events

ROOT = Path(__file__).resolve().parents[1]
USER='supervisor_sales'
SESSION='a'*32
ACTIONS=frozenset(ALLOWED_ACTIONS)


def new_gate(actions=ACTIONS):
    gate=TestControlGate()
    assert gate.arm('ENABLE 8001',True,True,queue='8001',agents={'PJSIP/100'},
                    owner_user=USER,owner_session=SESSION,allowed_actions=actions)
    return gate


class PrivacyChecks(unittest.TestCase):
    def test_viewer_does_not_leak_channel_in_mapping_key(self):
        source={'8001': {'entries':{'PJSIP/123-0001':{
            'Channel':'PJSIP/123-0001','Uniqueid':'123.4','Linkedid':'12.2',
            'CallerIDNum':'09123456789','CallerIDName':'Alice','Position':'1', 'Wait':'20'}},
            'members':{'PJSIP/100':{'LiveChannel':'PJSIP/100-abc','LiveCaller':'09125554444'}}}}
        result=public_queue_snapshot(source)
        dump=str(result)
        for value in ('PJSIP/123-0001','123.4','12.2','09123456789','Alice','PJSIP/100-abc','09125554444'):
            self.assertNotIn(value,dump)
        entry=result['8001']['entries']['entry_1']
        self.assertEqual(entry['CallerIDNum'],'••••89')
        self.assertEqual(entry['Wait'],'20')
        self.assertIn('PJSIP/123-0001',str(source))

    def test_keys_scoped_locally_and_complete_not_empty(self):
        source={'8001':{'entries':{'PJSIP/a-1':{'Channel':'PJSIP/a-1','Wait':'1'},'PJSIP/b-2':{'Channel':'PJSIP/b-2','Wait':'2'}},'members':{}}}
        view=public_queue_snapshot(source)
        self.assertEqual(list(view['8001']['entries']),['entry_1','entry_2'])
        self.assertEqual([x['Wait'] for x in view['8001']['entries'].values()],['1','2'])

    def test_privileged_keeps_channel_but_masks_customer(self):
        d={'8001':{'entries':{'PJSIP/a-1':{'Channel':'PJSIP/a-1','CallerIDNum':'09123456789'}},'members':{}}}
        v=public_queue_snapshot(d,privileged=True)
        self.assertIn('PJSIP/a-1',v['8001']['entries'])
        self.assertEqual(v['8001']['entries']['PJSIP/a-1']['CallerIDNum'],'••••89')


class GateChecks(unittest.TestCase):
    def test_unowned_gate_never_arms(self):
        g=TestControlGate()
        self.assertFalse(g.arm('ENABLE 8001', True, True,allowed_actions=ACTIONS))
        self.assertFalse(g.active())

    def test_gate_requires_exact_owner_session(self):
        gate=new_gate()
        x={'queue':'8001','agent':'PJSIP/100','paused':'true'}
        self.assertTrue(gate.authorize('pause_member',x,True,True,owner_user=USER,owner_session=SESSION))
        self.assertFalse(gate.authorize('pause_member',x,True,True,owner_user='supervisor_finance',owner_session=SESSION))
        self.assertFalse(gate.authorize('pause_member',x,True,True,owner_user=USER,owner_session='b'*32))
        self.assertFalse(gate.authorize('pause_member',x,True,True))

    def test_gate_action_grants_are_not_shared(self):
        gate=new_gate({'pause_member'})
        x={'queue':'8001','agent':'PJSIP/100','paused':'true'}
        self.assertTrue(gate.authorize('pause_member',x,True,True,owner_user=USER,owner_session=SESSION))
        self.assertFalse(gate.authorize('ops_control',{'queue':'8001','agent':'PJSIP/100','action':'spy'},True,True,owner_user=USER,owner_session=SESSION))

    def test_gate_queue_scope_and_credential_fail_closed(self):
        gate=new_gate()
        x={'queue':'8002','agent':'PJSIP/100','paused':'true'}
        self.assertFalse(gate.authorize('pause_member',x,True,True,owner_user=USER,owner_session=SESSION))
        x['queue']='8001'
        self.assertFalse(gate.authorize('pause_member',x,False,True,owner_user=USER,owner_session=SESSION))
        self.assertFalse(gate.authorize('pause_member',x,True,False,owner_user=USER,owner_session=SESSION))

    def test_gate_expiry_disarms_owner(self):
        gate=new_gate()
        gate.expires_at-=9999
        self.assertFalse(gate.active(owner_user=USER,owner_session=SESSION))
        self.assertFalse(gate.enabled)

    def test_gate_rejects_browser_chosen_listen_phone(self):
        gate=new_gate()
        x={'queue':'8001','agent':'PJSIP/100','action':'spy','destination':'PJSIP/999'}
        self.assertFalse(gate.authorize('ops_control',x,True,True,owner_user=USER,owner_session=SESSION))


class CodeBoundaryChecks(unittest.TestCase):
    def test_absent_policy_is_default_deny(self):
        code=(ROOT/'qpanel/operations.py').read_text(encoding='utf-8')
        self.assertIn('if store else {}',code)
        self.assertIn('return bool(store and store.access(',code)
        self.assertIn("if not callable(gate) or not gate(request):",code)

    def test_legacy_stats_prefix_is_blocked(self):
        code=(ROOT/'qpanel/app.py').read_text(encoding='utf-8')
        self.assertIn("request.path.startswith(('/queue/', '/stats/'))",code)

    def test_deployers_cannot_start_unsafe_backend(self):
        docker=(ROOT/'Dockerfile').read_text(encoding='utf-8')
        systemd=(ROOT/'deploy/sanequeue.service').read_text(encoding='utf-8')
        self.assertNotIn('qpanel.app:app',docker)
        self.assertIn('qpanel.wsgi:app',systemd)
        self.assertIn('--workers 1',systemd)

    def test_control_gate_uses_signed_session_and_current_user(self):
        code=(ROOT/'demo_monitor.py').read_text(encoding='utf-8')
        self.assertIn('owner_user=current_user.get_id()',code)
        self.assertIn('owner_session=_gate_session_nonce()',code)

    def test_ready_does_not_include_inuse_ringing(self):
        code=(ROOT/'qpanel/operations.py').read_text(encoding='utf-8')
        self.assertIn("str(member.get('Status', '0')) == '1'",code)
        self.assertIn("str(member.get('InCall', '0')).lower() in ('0', 'false')",code)

    def test_js_marks_stale_and_disables_controls(self):
        code=(ROOT/'qpanel/themes/qpanel/static/js/operations.js').read_text(encoding='utf-8')
        self.assertIn("currentDataSource='stale';cfg.test_controls_enabled=false",code)

    def test_asterisk20_standard_fields_work(self):
        rows=[{'Event':'QueueParams','Queue':'8001','ServiceLevelPerf':'88.2','Holdtime':'22'},
              {'Event':'QueueMember','Queue':'8001','MemberName':'Foo','Interface':'PJSIP/100'}]
        data=parse_queue_events(rows)['8001']
        self.assertEqual(data['ServicelevelPerf'],'88.2')
        self.assertEqual(data['members']['PJSIP/100']['Name'],'Foo')

if __name__=='__main__': unittest.main()
