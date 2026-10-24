"""Beta 11 offline tests; all inputs are synthetic."""
import unittest
from pathlib import Path
from qpanel.ami_live import parse_queue_events
from qpanel.privacy import public_queue_snapshot

ROOT=Path(__file__).resolve().parents[1]

class Beta11Tests(unittest.TestCase):
    def test_asterisk20_standard_service_level_and_member_name(self):
        data=parse_queue_events([
            {'Event':'QueueParams','Queue':'8001','ServiceLevelPerf':'93.2','Holdtime':'22','Calls':'0','Completed':'5','Abandoned':'3'},
            {'Event':'QueueMember','Queue':'8001','MemberName':'Operator 100','Interface':'Local/100@from-queue/n','Status':'1','Paused':'0'}], '8001')['8001']
        self.assertEqual(data['ServicelevelPerf'],'93.2')
        self.assertEqual(data['members']['Local/100@from-queue/n']['Name'],'Operator 100')
        self.assertEqual(data['Holdtime'],'22')
    def test_mixed_case_ami_fields_and_legacy_spellings(self):
        x=parse_queue_events([{'Event':'QueueParams','Queue':'8001','servicelevelperf':'90','ServiceLevelPerf2':'83'},
          {'Event':'QueueMember','Queue':'8001','Name':'Fallback','Location':'PJSIP/100','Status':'1'}])['8001']
        self.assertEqual(x['ServicelevelPerf'],'90')
        self.assertEqual(x['ServicelevelPerf2'],'83')
        self.assertEqual(x['members']['PJSIP/100']['Name'],'Fallback')
    def test_no_customer_number_or_call_channel_to_viewer(self):
        raw={'8001':{'entries':{'x':{'Channel':'PJSIP/abc-000','CallerIDNum':'09121234567','CallerIDName':'Private Customer'}},'members':{'a':{'LiveCaller':'02112345678','LiveChannel':'PJSIP/999-001'}}}}
        view=public_queue_snapshot(raw)
        self.assertEqual(view['8001']['entries']['entry_1']['CallerIDNum'],'••••67')
        self.assertNotIn('Channel',view['8001']['entries']['entry_1'])
        self.assertNotIn('LiveChannel',view['8001']['members']['a'])
        self.assertNotIn('09121234567',str(view))
        self.assertIn('Channel',raw['8001']['entries']['x'])
    def test_supervisor_can_target_opaque_channel_but_not_read_caller_number(self):
        raw={'8001':{'entries':{'x':{'Channel':'PJSIP/abc-000','CallerIDNum':'09121234567'}},'members':{}}}
        privileged=public_queue_snapshot(raw,privileged=True)
        self.assertEqual(privileged['8001']['entries']['x']['Channel'],'PJSIP/abc-000')
        self.assertEqual(privileged['8001']['entries']['x']['CallerIDNum'],'••••67')
    def test_legacy_routes_cannot_bypass_auth(self):
        x=(ROOT/'qpanel/app.py').read_text(encoding='utf-8')
        self.assertIn('def retire_legacy_http_surface()',x)
        for path in ('/spy','/whisper','/barge','/hangup','/remove_from_queue'):
            self.assertIn(repr(path),x)
        x=(ROOT/'qpanel/operations.py').read_text(encoding='utf-8')
        self.assertIn("if request.endpoint in ('spy','whisper','barge','hangup_call','remove_from_queue')",x)
        self.assertIn("}.get(request.endpoint, None)",x)
    def test_no_old_brand_on_modern_screen(self):
        html=(ROOT/'qpanel/themes/qpanel/templates/operations.html').read_text(encoding='utf-8')
        self.assertNotIn('Based on QPanel',html)
        self.assertNotIn('github.com/roramirez/qpanel',html)
        self.assertIn('SaneQueue',html)
        self.assertIn('Rodrigo', (ROOT/'LICENSE').read_text(encoding='utf-8'))
        self.assertIn('QPanel',(ROOT/'NOTICE').read_text(encoding='utf-8'))
    def test_ami_cache_is_bounded_and_live_error_fails_closed(self):
        x=(ROOT/'demo_monitor.py').read_text(encoding='utf-8')
        self.assertIn('LIVE_CACHE_SECONDS = 5.0',x)
        self.assertIn("('ops_control','pause_member')",x)
        self.assertIn('Never substitute stale/demo data after a live error.',x)
if __name__=='__main__':unittest.main()
