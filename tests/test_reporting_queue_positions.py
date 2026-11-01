import unittest
from tests import test_reporting_queries as fixtures
from sanequeue.reporting.facts import project_batch
from sanequeue.reporting.queries import Scope,visits,detail


class QueuePositionTests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.ReportTests();self.case.setUp();self.addCleanup(self.case.doCleanups)

    def test_explicit_positions_conflicts_unknown_and_queue_isolation(self):
        c=self.case
        c.archive.append([c.event('a','8001','ENTERQUEUE',0,['','100','5']),
          c.event('a','8001','EXITWITHKEY',25,['9','2','5','25']),
          c.event('b','8001','ENTERQUEUE',30,['','200','4']),
          c.event('b','8001','ABANDON',40,['1','3','10']),
          c.event('c','8001','ENTERQUEUE',50,['','300','0']),
          c.event('c','8001','CONNECT',60,['10','peer','1']),
          c.event('c','8001','COMPLETEAGENT',70,['10','10','bad']),
          c.event('d','8002','ENTERQUEUE',80,['','400','9']),
          c.event('d','8002','EXITWITHTIMEOUT',90,['2','9','10'])])
        while project_batch(c.archive,limit=3)['processed']:pass
        rows=visits(c.archive,Scope(('8001',)),c.stamp,c.stamp+100)['rows'];by_caller={row['caller']:row for row in rows}
        self.assertEqual((by_caller['100']['entry_position'],by_caller['100']['exit_position']),(5,2))
        self.assertEqual(by_caller['100']['exit_position_evidence'],'exitwithkey')
        self.assertIsNone(by_caller['200']['entry_position']);self.assertEqual(by_caller['200']['entry_position_evidence'],'conflicting')
        self.assertIsNone(by_caller['300']['entry_position']);self.assertIsNone(by_caller['300']['exit_position'])
        self.assertEqual(by_caller['300']['exit_position_evidence'],'unavailable')
        self.assertIsNone(detail(c.archive,Scope(('8001',)),c.stamp,c.stamp+100,
                                 visits(c.archive,Scope(('8002',)),c.stamp,c.stamp+100)['rows'][0]['id']))
        self.assertEqual(detail(c.archive,Scope(('8001',)),c.stamp,c.stamp+100,by_caller['100']['id'])['visit']['entry_position'],5)

    def test_incremental_repair_rebuilds_existing_positions_in_bounded_steps(self):
        from sanequeue.reporting.repair_queue_positions import step,CHECKPOINT
        c=self.case
        c.archive.append([c.event('a','8001','ENTERQUEUE',0,['','100','5']),
                          c.event('a','8001','ABANDON',10,['2','5','10']),
                          c.event('b','8001','ENTERQUEUE',20,['','200','7']),
                          c.event('b','8001','EXITWITHKEY',30,['9','3','7','10'])])
        while project_batch(c.archive,limit=2)['processed']:pass
        with c.archive.writer() as db:db.execute('DELETE FROM report_visit_positions')
        self.assertTrue(all(r['entry_position'] is None for r in visits(c.archive,Scope(('8001',)),c.stamp,c.stamp+100)['rows']))
        for _ in range(10):
            result=step(c.archive,scan_limit=2,max_calls=1)
            self.assertLessEqual(result['rebuilt_calls'],1)
            if result['completed']:break
        self.assertTrue(result['completed']);self.assertTrue(c.archive.checkpoint(CHECKPOINT)['completed'])
        rows=visits(c.archive,Scope(('8001',)),c.stamp,c.stamp+100)['rows']
        self.assertEqual({(r['entry_position'],r['exit_position']) for r in rows},{(5,2),(7,3)})
        self.assertEqual(step(c.archive)['rebuilt_calls'],0)

    def test_reentry_does_not_mix_positions_and_rebuild_removes_old(self):
        c=self.case
        c.archive.append([c.event('a','8001','ENTERQUEUE',0,['','100','5']),
          c.event('a','8001','ABANDON',10,['2','5','10']),
          c.event('a','8001','ENTERQUEUE',20,['','100','7']),
          c.event('a','8001','ABANDON',30,['3','7','10'])])
        while project_batch(c.archive,limit=2)['processed']:pass
        rows=visits(c.archive,Scope(('8001',)),c.stamp,c.stamp+100)['rows']
        self.assertEqual({(r['entry_position'],r['exit_position']) for r in rows},{(5,2),(7,3)})
        self.assertEqual(project_batch(c.archive)['processed'],0)

if __name__=='__main__':unittest.main()
