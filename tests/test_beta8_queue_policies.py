"""Offline policy and safety tests. Zero network, no real AMI writes."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from qpanel.queue_policies import QueuePolicyStore, DEFAULT_QUEUE, validate_config, send_bale_alert


def sample_policy(queue='8001', roster=10, pct=50, count=5):
    q = {
        'label':'فروش',
        'alerts':{'waiting_above':5,'wait_seconds_above':300,'min_ready':3,'cooldown_seconds':300,'bale_enabled':True},
        'staffing':{'roster_size':roster,'max_absent_percent':pct,'max_absent_count':count,'min_on_duty':0},
        'pause_reasons':[{'id':'break','label':'استراحت'},{'id':'meeting','label':'جلسه'}],
    }
    return {'version':1,'queues':{queue:q},'supervisors':{'supervisorA':{'queues':[queue],'actions':['view','pause']}}}


def active_members(num):
    return {f'PJSIP/{100+i}':{'Status':'1','Paused':'0','Location':f'PJSIP/{100+i}'} for i in range(num)}


class Beta8PolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=QueuePolicyStore(Path(self.tmp.name)/'local_queue_policies.json')
        self.store.replace(sample_policy(),visible_queues={'8001'})

    def test_policy_restricts_user_to_own_queue_and_actions(self):
        data={'8001':{},'8002':{}}
        self.assertEqual(self.store.visible('supervisorA','supervisor',data),{'8001':{}})
        self.assertFalse(self.store.access('supervisorA','supervisor','8002','pause'))
        self.assertFalse(self.store.access('supervisorA','supervisor','8001','hangup'))
        self.assertTrue(self.store.access('supervisorA','supervisor','8001','pause'))
        self.assertTrue(self.store.access('any','admin','8002','hangup'))
        self.assertFalse(self.store.access('unauthorized','viewer','8001','view'))

    def test_tenth_member_and_fifty_percent_allows_fifth_exit_not_sixth(self):
        for active in (10,9,8,7,6):
            q={'members':active_members(active)}
            allowed,_=self.store.can_leave('8001',q,'PJSIP/100')
            self.assertTrue(allowed,active)
        blocked,reason=self.store.can_leave('8001',{'members':active_members(5)},'PJSIP/100')
        self.assertFalse(blocked)
        self.assertEqual(reason,'queue_exit_limit_reached')

    def test_fixed_roster_prevents_membership_shrink_bypass(self):
        q={'members':active_members(5)}
        self.assertFalse(self.store.can_leave('8001',q,'PJSIP/100')[0])
        # Current membership 5 is NOT treated as a fresh new 50% roster.
        self.assertEqual(self.store.queue('8001')['staffing']['roster_size'],10)

    def test_busy_on_duty_counts_for_capacity(self):
        members=active_members(6)
        members['PJSIP/101']['Status']='2'
        self.assertTrue(self.store.can_leave('8001',{'members':members},'PJSIP/100')[0])

    def test_absent_agent_denied_and_optional_staffing_is_independent(self):
        self.assertFalse(self.store.can_leave('8001',{'members':active_members(10)},'PJSIP/999')[0])
        cfg=sample_policy();cfg['queues']['8001']['staffing']['roster_size']=0
        self.store.replace(cfg)
        self.assertTrue(self.store.can_leave('8001',{'members':active_members(10)},'PJSIP/100')[0])
        cfg['queues']['8001']['staffing']['enabled']=True
        with self.assertRaises(ValueError):self.store.replace(cfg)

    def test_thresholds_include_boundary_and_transition_deduplicated(self):
        queue={'members':active_members(5),'Calls':'4','entries':{'a':{'Wait':'299'}},'Completed':'14','Abandoned':'3','Holdtime':'94','TalkTime':'12','ServicelevelPerf':'84.21'}
        res=self.store.evaluate({'8001':queue},now=0)
        self.assertEqual(res['alerts'],[])
        queue['Calls']='5';queue['entries']['a']['Wait']='300'
        fired=self.store.evaluate({'8001':queue},now=10)
        self.assertEqual({a['type'] for a in fired['alerts']},{'waiting_count','waiting_time'})
        self.assertEqual(len(fired['notify']),2)
        self.assertEqual(self.store.evaluate({'8001':queue},now=999)['notify'],[])
        queue['Calls']='0';queue['entries']['a']['Wait']='0';self.store.evaluate({'8001':queue},now=1000)
        queue['Calls']='6';self.assertEqual(len(self.store.evaluate({'8001':queue},now=1001)['notify']),1)

    def test_count_and_time_can_be_disabled_or_combined(self):
        config=sample_policy();rules=config['queues']['8001']['alerts']
        rules.update(count_enabled=False,time_enabled=True,match_mode='any');self.store.replace(config)
        queue={'Calls':'100','members':active_members(5),'entries':{'a':{'Wait':'299'}}}
        self.assertFalse(self.store.evaluate({'8001':queue})['alerts'])
        queue['entries']['a']['Wait']='300'
        self.assertEqual({a['type'] for a in self.store.evaluate({'8001':queue})['alerts']},{'waiting_time'})
        rules.update(count_enabled=True,match_mode='all');self.store.replace(config)
        queue['Calls']='4'
        self.assertFalse(self.store.evaluate({'8001':queue})['alerts'])
        queue['Calls']='5'
        self.assertEqual(len(self.store.evaluate({'8001':queue})['alerts']),2)
        rules.update(count_enabled=False,time_enabled=False);self.store.replace(config)
        self.assertFalse(self.store.evaluate({'8001':queue})['alerts'])

    def test_numeric_limit_is_stricter_than_percentage(self):
        cfg=sample_policy(pct=90,count=2)
        self.store.replace(cfg)
        self.assertTrue(self.store.can_leave('8001',{'members':active_members(9)},'PJSIP/100')[0])
        self.assertFalse(self.store.can_leave('8001',{'members':active_members(8)},'PJSIP/100')[0])

    def test_reason_validation_and_customization(self):
        self.assertEqual(self.store.validate_reason('8001','meeting'),'meeting')
        with self.assertRaises(ValueError):self.store.validate_reason('8001','bad:AMI\r\nAction')
        cfg=sample_policy();cfg['queues']['8001']['pause_reasons'].append({'id':'office','label':'کار اداری'})
        self.store.replace(cfg)
        self.assertEqual(self.store.validate_reason('8001','office'),'office')

    def test_html_injection_invalid_limits_and_unknown_scope_rejected(self):
        for qid in ('8001\r\nAction: Hangup','<script>','*'):
            with self.subTest(qid=qid), self.assertRaises(ValueError):validate_config(sample_policy(qid))
        cfg=sample_policy();cfg['supervisors']['supervisorA']['queues']=['8002']
        with self.assertRaises(ValueError):validate_config(cfg)
        cfg=sample_policy();cfg['queues']['8001']['staffing']['max_absent_percent']=101
        with self.assertRaises(ValueError):validate_config(cfg)
        with self.assertRaises(ValueError):self.store.replace(sample_policy(),visible_queues={'8002'})

    def test_summary_stays_aggregate_without_caller_identifiers(self):
        q={'members':active_members(4),'entries':{'a':{'Wait':'135','CallerIDNum':'09123456789'}},'Calls':'1','Completed':'14','Abandoned':'3','Holdtime':'94','TalkTime':'12','ServicelevelPerf':'84.21','Strategy':'ringall'}
        import json
        summary=self.store.summary('8001',q)
        self.assertEqual(summary['completed'],14)
        self.assertEqual(summary['abandoned'],3)
        self.assertEqual(summary['longest_wait'],135)
        self.assertEqual(summary['service_level_pct'],84.21)
        self.assertNotIn('09123456789',json.dumps(summary))

    def test_config_no_secret_and_atomic_replace(self):
        cfg=sample_policy();self.store.replace(cfg)
        import json
        saved=json.loads((Path(self.tmp.name)/'local_queue_policies.json').read_text(encoding='utf-8'))
        self.assertNotIn('secret',json.dumps(saved))
        self.assertNotIn('password',json.dumps(saved))
        cfg['queues']['8001']['label']='پیگیری'
        self.store.replace(cfg)
        self.assertEqual(self.store.export()['queues']['8001']['label'],'پیگیری')

    def test_pending_action_reservation_blocks_double_exit_on_stale_snapshot(self):
        # Both supervisors might observe the same six-person snapshot while
        # QueuePause responses have not yet arrived from Asterisk.
        from concurrent.futures import ThreadPoolExecutor
        q={'members':active_members(6)}
        with ThreadPoolExecutor(max_workers=2) as pool:
            f1=pool.submit(self.store.reserve_leave,'8001',q,'PJSIP/100')
            f2=pool.submit(self.store.reserve_leave,'8001',q,'PJSIP/101')
            a=f1.result();b=f2.result()
        self.assertEqual(sum(v[0] for v in (a,b)),1)
        self.store.release_leave('8001','PJSIP/100')
        self.store.release_leave('8001','PJSIP/101')
        self.assertTrue(self.store.reserve_leave('8001',q,'PJSIP/101')[0])

    def test_pause_reason_is_queue_specific(self):
        conf=sample_policy()
        conf['queues']['8002']=dict(conf['queues']['8001'])
        conf['queues']['8002']['pause_reasons']=[{'id':'training','label':'آموزش'}]
        self.store.replace(conf,visible_queues={'8001','8002'})
        with self.assertRaises(ValueError):self.store.validate_reason('8002','meeting')
        self.assertEqual(self.store.validate_reason('8001','meeting'),'meeting')

    def test_bale_api_uses_fixed_host_and_no_callers(self):
        class Resp:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,n):return b'{"ok":true}'
        with patch('qpanel.queue_policies.urllib.request.urlopen',return_value=Resp()) as mock:
            self.assertTrue(send_bale_alert({'queue':'8001','label':'فروش','type':'waiting_count','value':6,'threshold':5},'a'*20,'123456'))
            req=mock.call_args.args[0]
            self.assertTrue(req.full_url.startswith('https://tapi.bale.ai/bot'))
            self.assertIn(b'8001',req.data)
            self.assertNotIn(b'09123456789',req.data)

if __name__=='__main__':unittest.main()
