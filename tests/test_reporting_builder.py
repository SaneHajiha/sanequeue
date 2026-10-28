"""Small real SQLite fixtures for whitelist, scope, unknowns and private versions."""
import tempfile
from pathlib import Path
import sqlite3
import unittest
from sanequeue.reporting.report_builder import Templates,BuilderConflict,definition,preview,DEFAULT
from sanequeue.reporting.store import Archive
from sanequeue.reporting.queries import Scope
from sanequeue.reporting.facts import project_batch
from contextlib import closing


class BuilderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.archive=Archive(self.root/'archive.db',min_free_bytes=0);self.archive.initialize()
        project_batch(self.archive,inventory={})
        self.spec={**DEFAULT,'queues':['8001']};self.store=Templates(self.root/'builder.db');self.store.initialize()
    def add(self,number,queue='8001',agent='100',entered=100,answered=110,wait=10,talk=20,outcome='answered'):
        with self.archive.writer() as db:db.execute('INSERT INTO report_visits VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            ('primary',format(number,'064x'),'private-call',queue,entered,answered,130,'09123456789',agent,outcome,wait,talk,'caller','observed'))
    def run_preview(self,spec=None,scope=None,**extra):
        return preview(self.archive,scope or Scope(('8001',)),90,300,spec or self.spec,number_modes={'8001':'masked'},**extra)
    def test_table_keyset_same_timestamp_masks_and_returns_only_selected_columns(self):
        for n in range(1,5):self.add(n)
        spec={**self.spec,'columns':['caller','agent']};first=self.run_preview(spec,limit=2)
        self.assertEqual(first['columns'],['caller','agent']);self.assertEqual(len(first['rows']),2)
        self.assertEqual(first['rows'][0],dict(caller='0912***6789',agent='100'))
        second=self.run_preview(spec,before=first['next'],limit=2)
        self.assertEqual(len(second['rows']),2);self.assertIsNone(second['next'])
        self.assertNotIn('09123456789',str(first));self.assertNotIn('private-call',str(first))
    def test_scope_multiqueue_own_agent_and_assignment_cutoff(self):
        self.add(1,entered=95);self.add(2,entered=110);self.add(3,agent='200',entered=120);self.add(4,queue='8002')
        result=self.run_preview(scope=Scope(('8001',),('100',),True,100))
        self.assertEqual(len(result['rows']),1)
        with self.assertRaises(PermissionError):self.run_preview({**self.spec,'queues':['8001','8002']})
        self.assertEqual(self.run_preview(scope=Scope(('8001',),(),True))['rows'],[])
    def test_aggregate_uses_known_denominators_and_queue_segments(self):
        self.add(1);self.add(2,answered=None,wait=None,talk=None,outcome='abandoned')
        data=self.run_preview({**self.spec,'group_by':['queue']});row=data['rows'][0]
        self.assertEqual((row['visits'],row['answered_known'],row['wait_known'],row['talk_known']),(2,1,1,1))
        self.assertEqual((row['average_wait_seconds'],row['average_queue_talk_seconds'],row['queue_talk_seconds']),(10,20,20))
        self.assertFalse(data['contract']['conversation_unique']);self.assertFalse(data['contract']['complete_source_coverage'])
        empty=self.run_preview({**self.spec,'group_by':['outcome'],'filters':{'outcomes':['unknown']}})
        self.assertEqual(empty['rows'],[])
    def test_numeric_thresholds_exclude_unknown_and_outcome_filters_bind(self):
        self.add(1);self.add(2,wait=None,talk=None);self.add(3,wait=50,talk=90,outcome='abandoned')
        data=self.run_preview({**self.spec,'filters':{'wait_min':0,'wait_max':20,'talk_max':30,'outcomes':['answered']}})
        self.assertEqual(len(data['rows']),1)
    def test_rejects_sql_unknown_fields_dates_groups_and_bad_cursors(self):
        for change in ({'columns':['caller;DROP TABLE events']},{'group_by':['caller']},{'filters':{'sql':'1=1'}},{'dataset':'cdr'},{'columns':['queue','queue']}):
            with self.subTest(change=change),self.assertRaises(ValueError):definition({**self.spec,**change})
        for cursor in ('bad','WzEsIngiXQ==','W3RydWUsIjAwIl0='):
            with self.assertRaises(ValueError):self.run_preview(before=cursor)
        with self.assertRaisesRegex(ValueError,'builder_range_limit'):preview(self.archive,Scope(('8001',)),0,32*86400,self.spec,number_modes={'8001':'masked'})
        with self.assertRaises(ValueError):self.run_preview(limit=101)
    def test_group_ceiling_fails_rather_than_truncating(self):
        with self.archive.writer() as db:db.executemany('INSERT INTO report_visits VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            [('primary',format(n,'064x'),'private','8001',100,110,120,'09123456789',str(n),'answered',10,10,'caller','observed') for n in range(501)])
        with self.assertRaisesRegex(ValueError,'builder_group_limit'):self.run_preview({**self.spec,'group_by':['agent']})
    def test_oversized_source_text_fails_without_materializing_it_in_payload(self):
        self.add(1)
        with self.archive.writer() as db:db.execute('UPDATE report_visits SET caller=?,agent=?',('X'*5000,'Y'*5000))
        with self.assertRaisesRegex(ValueError,'builder_field_limit'):self.run_preview()
        with self.assertRaisesRegex(ValueError,'builder_field_limit'):self.run_preview({**self.spec,'group_by':['agent']})
    def test_private_versions_owner_scope_and_immutable_rows(self):
        first=self.store.save('alice','One',self.spec);second=self.store.save('alice','Two',self.spec,ident=first['id'],expected_version=1)
        self.assertEqual(second['version'],2);self.assertEqual(len(self.store.list('alice')),1)
        self.assertIsNone(self.store.get(first['id'],'bob'));self.assertEqual(self.store.list('bob'),[])
        with self.assertRaises(BuilderConflict):self.store.save('alice','Stale',self.spec,ident=first['id'],expected_version=1)
        with self.assertRaises(FileNotFoundError):self.store.save('bob','Hijack',self.spec,ident=first['id'],expected_version=2)
        with closing(sqlite3.connect(self.store.path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM builder_templates').fetchone()[0],2)
            with self.assertRaises(sqlite3.IntegrityError):db.execute("UPDATE builder_templates SET name='bad'")
    def test_private_store_rejects_archive_and_symlink(self):
        from sanequeue.reporting.report_builder import BuilderUnavailable
        with self.assertRaises(BuilderUnavailable):Templates(self.archive.path).initialize()

if __name__=='__main__':unittest.main()
