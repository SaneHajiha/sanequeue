import tempfile,unittest
from pathlib import Path
from sanequeue.alerts.system import SystemAlerts
from sanequeue.alerts.messaging import clean_system_rules,alert_text
from sanequeue.alerts.outbox import AlertOutbox

class CriticalTests(unittest.TestCase):
    def test_debounce_recovery_and_unknown_are_not_trunk_failure(self):
        now=[100];engine=SystemAlerts(lambda:now[0]);rules=clean_system_rules({})
        rows=[{'technology':'SIP','endpoint':'trunk-a','category':'trunk','state':'Unavailable'},{'technology':'PJSIP','endpoint':'trunk-b','category':'trunk','state':'unknown'},{'technology':'PJSIP','endpoint':'100','category':'extension','state':'Unavailable'}]
        inventory={'endpoints':rows,'disk_used_percent':20}
        self.assertEqual(engine.evaluate(inventory,{},True,rules),[]);now[0]+=11
        found=engine.evaluate(inventory,{},True,rules);self.assertEqual([a['label'] for a in found],['SIP/trunk-a'])
        live={'SIP/trunk-a':{'state':'Reachable','observed_at':now[0]}};self.assertEqual(engine.evaluate(inventory,live,True,rules),[])
        now[0]+=1;self.assertEqual(engine.evaluate(inventory,{},True,rules),[])
    def test_separate_critical_types_and_localized_safe_text(self):
        now=[100];engine=SystemAlerts(lambda:now[0]);rules=clean_system_rules({});engine.evaluate(None,{},False,rules);now[0]+=11
        self.assertEqual({a['type'] for a in engine.evaluate(None,{},False,rules)},{'monitoring_unavailable','inventory_stale'})
        alert={'queue':'8001','type':'waiting_count','value':5,'threshold':3,'label':'Sales','channel':'SECRET_CHANNEL','token':'SECRET_TOKEN'}
        fa=alert_text(alert,'fa');en=alert_text(alert,'en');both=alert_text(alert,'both')
        self.assertNotEqual(fa,en);self.assertIn(fa,both);self.assertIn(en,both);self.assertNotIn('SECRET',both)
