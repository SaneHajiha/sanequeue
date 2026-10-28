import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from sanequeue.reporting.customer_segments import CustomerSegments,SegmentConflict,number
from sanequeue.reporting.queries import Scope
from tests import test_reporting_journey as fixtures


class CustomerSegmentTests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.JourneyTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.archive=self.case.archive;self.root=self.archive.path.parent
        self.store=CustomerSegments(self.root/'customer-segments.sqlite3');self.store.initialize()
        self.case.seed(*self.case.visit('first',stamp=100),*self.case.visit('second',stamp=130),
                       *self.case.visit('foreign','8002',stamp=100))

    def report(self,scope=None):return self.store.report(self.archive,scope or Scope(('8001',)),90,300)

    def test_temporal_vip_labels_and_sla_denominators_are_queue_scoped(self):
        self.store.tag('admin','8001','09123456789',True,effective=95,request_key='a')
        self.store.tag('admin','8001','09123456789',False,effective=125,request_key='b')
        rows=self.report()['vip'];self.assertEqual(len(rows),2)
        self.assertEqual({r['classification'] for r in rows},{'vip','not_vip'})
        self.assertTrue(all(r['visits']==1 and r['sla_denominator']==1 and r['sla_percent']==100 for r in rows))
        foreign=self.report(Scope(('8002',)))['vip']
        self.assertEqual(foreign[0]['classification'],'unclassified')
        self.assertNotIn('8002',json.dumps(self.report()))

    def test_unknown_is_not_zero_and_no_unlabelled_customer_is_assumed_ordinary(self):
        report=self.report();self.assertEqual(report['vip'][0]['classification'],'unclassified')
        self.assertEqual(report['observations'],[])
        with self.archive.writer() as db:db.execute('UPDATE report_visits SET wait_seconds=NULL')
        row=self.report()['vip'][0];self.assertIsNone(row['sla_percent']);self.assertEqual(row['sla_denominator'],0)

    def test_annotation_idempotency_conflict_and_current_effective_retries(self):
        a=self.store.tag('a','8001','۰۹۱۲ ۳۴۵۶۷۸۹',True,effective=None,request_key='one')
        b=self.store.tag('a','8001','09123456789',True,effective=None,request_key='one')
        self.assertEqual(a,b)
        with self.assertRaises(SegmentConflict):self.store.tag('a','8001','09123456789',False,effective=None,request_key='one')
        with self.assertRaises(SegmentConflict):self.store.tag('b','8001','09123456789',False,effective=a['effective'],request_key='other')
        self.assertNotEqual(number('09123456789'),number('+989123456789'))

    def test_imported_block_observations_deduplicate_and_preserve_provenance(self):
        row=dict(id='source-1',queue='8001',number='09123456789',at=110,reason='blacklist')
        self.assertEqual(self.store.import_blocks('pbx_export',[row]),1)
        self.assertEqual(self.store.import_blocks('pbx_export',[row]),0)
        self.store.import_blocks('pbx_export',[dict(row,id='private',queue='8002')])
        report=self.report();self.assertEqual(report['blocks'][0]['observations'],1)
        self.assertEqual(report['observations'][0]['source'],'pbx_export')
        self.assertNotIn('event_key',report['observations'][0])
        self.assertEqual(report['blocks_basis'],'operator_imported_observation_not_independent_pbx_proof')
        with self.assertRaises(SegmentConflict):self.store.import_blocks('pbx_export',[dict(row,reason='security')])

    def test_invalid_import_is_atomic_and_scope_time_limits_apply(self):
        row=dict(id='source-1',queue='8001',number='09123456789',at=110,reason='blacklist')
        with self.assertRaises(ValueError):self.store.import_blocks('pbx_export',[row,dict(row,id='bad',number='SIP/private')])
        self.assertEqual(self.report()['blocks'],[])
        self.store.import_blocks('pbx_export',[row])
        self.assertEqual(self.report(Scope(('8001',),not_before=120))['observations'],[])
        with self.assertRaises(PermissionError):self.report(Scope(('8001',),('PJSIP/100',),True))
        with self.assertRaises(ValueError):self.store.report(self.archive,Scope(('8001',)),0,32*86400)

    def test_operator_cli_imports_real_jsonl_without_exposing_numbers(self):
        path=self.root/'observations.jsonl';path.write_text(json.dumps(dict(id='one',queue='8001',number='09123456789',at=110,reason='policy'))+'\n')
        result=subprocess.run([sys.executable,'-m','sanequeue.reporting.customer_segments','--database',str(self.store.path),'--source','verified_export',str(path)],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(json.loads(result.stdout)['inserted'],1)
        self.assertNotIn('09123456789',result.stdout)
        self.assertEqual(self.report()['observations'][0]['reason'],'policy')


    def test_history_rejects_direct_update_or_delete(self):
        import sqlite3
        self.store.tag('a','8001','100',True,effective=None,request_key='immutable')
        self.store.import_blocks('export',[dict(id='one',queue='8001',number='100',at=110,reason='policy')])
        for table in ('customer_tags','blocked_observations'):
            for statement in ('UPDATE '+table+' SET number=?','DELETE FROM '+table):
                with self.assertRaises(sqlite3.IntegrityError):
                    with self.store.db(write=True) as db:
                        db.execute(statement,('200',) if statement.startswith('UPDATE') else ())

if __name__=='__main__':unittest.main()
