import json
from pathlib import Path
import tempfile
import unittest
from sanequeue.realtime.local_inventory import definitions,endpoint_states,read_snapshot,projection,internal_contexts


class LocalInventoryTests(unittest.TestCase):
    def test_custom_context_is_explicit_and_does_not_admit_numeric_trunks(self):
        source='[100]\ntype=endpoint\ncontext=from-internal-sales\n[99999]\ntype=endpoint\ncontext=from-pstn\n'
        self.assertEqual(definitions(source,'PJSIP')[0]['category'],'trunk')
        rows=definitions(source,'PJSIP',{'from-internal','from-internal-sales'})
        self.assertEqual([row['endpoint'] for row in rows if row['category']=='extension'],['100'])
        self.assertEqual(rows[1]['category'],'trunk')

    def test_custom_context_configuration_is_bounded_and_validated(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'inventory.ini'
            self.assertEqual(internal_contexts(path),{'from-internal'})
            path.write_text('[inventory]\ninternal_contexts=from-internal,internal-sales\n')
            self.assertEqual(internal_contexts(path),{'from-internal','internal-sales'})
            for value in ('', 'from-internal,*', ','.join('ctx'+str(i) for i in range(33))):
                path.write_text('[inventory]\ninternal_contexts='+value+'\n')
                with self.assertRaises(ValueError):internal_contexts(path)

    def test_numeric_trunk_is_not_an_extension_and_secrets_are_dropped(self):
        source='[100]\ntype=endpoint\ncontext=from-internal\nsecret=never-return\n[auth100]\ntype=auth\nusername=100\n[99999999]\ntype=endpoint\ncontext=from-pstn\n'
        rows=definitions(source,'PJSIP')
        self.assertEqual([r['endpoint'] for r in rows if r['category']=='extension'],['100'])
        self.assertEqual(rows[1]['category'],'trunk')
        self.assertNotIn('never-return',json.dumps(rows))
        self.assertEqual(definitions('[7777]\ntype=peer\ncontext=to-cidformatter','SIP')[0]['category'],'trunk')

    def test_states_and_freshness_are_explicit(self):
        self.assertEqual(endpoint_states(' Endpoint: 100/100       Not in use    0 of inf','PJSIP'),{'100':'Not in use'})
        self.assertEqual(endpoint_states('888/888  10.0.0.1  Yes  Yes  5060  UNREACHABLE','SIP'),{'888':'UNREACHABLE'})
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'inventory.json';path.write_text(json.dumps({'observed_at':100,'endpoints':[]}))
            self.assertIsNotNone(read_snapshot(path,now=150))
            self.assertIsNone(read_snapshot(path,now=191))
            self.assertIsNone(read_snapshot(path,now=99))
            path.write_text(json.dumps({'observed_at':float('nan'),'endpoints':[]}))
            self.assertIsNone(read_snapshot(path,now=150))
            path.write_text(json.dumps({'observed_at':100,'endpoints':[{'endpoint':'trunk','category':'extension'}]}))
            self.assertIsNone(read_snapshot(path,now=150))

    def test_extension_projection_excludes_trunks_and_no_false_available_state(self):
        data={'observed_at':100,'drivers':{'PJSIP':True,'SIP':True},'source':'test','endpoints':[
            {'endpoint':'100','technology':'PJSIP','category':'extension','state':'Not in use'},
            {'endpoint':'200','technology':'PJSIP','category':'extension','state':'Unavailable'},
            {'endpoint':'9999','technology':'SIP','category':'trunk','state':'UNREACHABLE'}]}
        result=projection(data,'extension')
        self.assertEqual(result['data']['total'],2);self.assertEqual(result['data']['available'],1)
        self.assertEqual(projection(data,'trunk')['data']['total'],1)
