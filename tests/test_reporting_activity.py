import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from contextlib import closing
from sanequeue.reporting.store import Archive,Event
from sanequeue.reporting.activity_source import ActivitySource
from sanequeue.realtime.activity import ActivityStore
from sanequeue.reporting.facts import project_batch
from sanequeue.reporting.queries import Scope
from sanequeue.reporting.activity_queries import summary,intervals
from sanequeue.reporting.identity import canonical


class ActivityImportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.archive=Archive(self.root/'archive.sqlite3',min_free_bytes=0);self.archive.initialize()
        self.cache=ActivityStore(self.root/'activity.sqlite3')
        self.source=ActivitySource(self.cache.path)

    def test_open_heartbeat_no_event_growth_then_late_close(self):
        self.cache.write([('8001','PJSIP/100','available','',100,True)],110,'g1')
        self.assertEqual(self.source.ingest(self.archive)['inserted'],1)
        self.cache.write([],120,'g1')
        self.assertEqual(self.source.ingest(self.archive)['inserted'],0)
        self.assertEqual(self.archive.checkpoint('activity_cache')['observed'],120)
        self.cache.write([('8001','PJSIP/100','paused','survey',125,False)],130,'g1')
        self.assertEqual(self.source.ingest(self.archive)['inserted'],2)
        rows=self.archive.page(source='activity')
        self.assertEqual(rows[-1]['payload']['ends'],125)
        self.assertEqual(len(rows),3)
        with self.archive.reader() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM activity_import_open').fetchone()[0],1)

    def test_restart_does_not_credit_observation_gap(self):
        self.cache.write([('8001','PJSIP/100','available','',100,True)],110,'g1')
        self.source.ingest(self.archive)
        self.cache.write([('8001','PJSIP/100','available','',200,True)],210,'g2')
        self.source.ingest(self.archive)
        rows=self.archive.page(source='activity')
        old=[r for r in rows if r['payload']['starts']==100][-1]['payload']
        self.assertEqual(old['ends'],110)
        self.assertTrue(self.archive.checkpoint('activity_cache')['gaps'])

    def test_raw_archive_survives_source_retention(self):
        self.cache.write([('8001','PJSIP/100','available','',100,True)],110,'g1')
        self.source.ingest(self.archive)
        self.cache.write([('8001','PJSIP/100','paused','lunch',120,False)],130,'g1')
        self.source.ingest(self.archive)
        with closing(sqlite3.connect(self.cache.path)) as db:
            db.execute('DELETE FROM activity WHERE ends IS NOT NULL');db.commit()
        self.source.ingest(self.archive)
        self.assertTrue(any(r['payload']['starts']==100 for r in self.archive.page(source='activity')))

    def test_bookkeeping_failure_rolls_back_events_and_cursor(self):
        def fail(db):raise RuntimeError('synthetic_failure')
        with self.assertRaises(RuntimeError):
            self.archive.append([Event('activity','1',100,'ACTIVITY_INTERVAL',{})],
                                checkpoint_source='activity_cache',checkpoint={'after':1},update_state=fail)
        self.assertEqual(self.archive.page(),[])
        self.assertEqual(self.archive.checkpoint('activity_cache'),{})

    def test_multi_queue_duty_is_unioned_and_self_scope_is_applied(self):
        self.cache.write([('8001','PJSIP/100','available','',100,True)],100,'g1')
        self.cache.write([('8002','PJSIP/100','available','',110,True),
                          ('8001','PJSIP/200','available','',110,True)],110,'g1')
        self.cache.write([('8001','PJSIP/100','paused','survey',130,False)],130,'g1')
        self.cache.write([('8002','PJSIP/100','paused','survey',140,False)],160,'g1')
        while not self.source.ingest(self.archive,limit=2)['caught_up']:pass
        while project_batch(self.archive,limit=2)['processed']:pass
        scope=Scope(('8001','8002'),('PJSIP/100',),True)
        result=summary(self.archive,scope,90,200,now=170)
        self.assertEqual(len(result['agents']),1)
        agent=result['agents'][0]
        self.assertEqual(agent['unique_on_duty_seconds'],40)
        self.assertEqual(agent['membership_on_duty_seconds'],60)
        self.assertEqual(agent['paused_membership_seconds'],50)
        self.assertEqual(sum(row['seconds'] for row in result['rows'] if row['state']=='paused'),50)
        cutoff=summary(self.archive,Scope(('8001','8002'),('PJSIP/100',),True,115),90,200,now=170)
        self.assertEqual(cutoff['agents'][0]['unique_on_duty_seconds'],25)
        page=intervals(self.archive,scope,90,200,limit=2)
        self.assertEqual(len(page['rows']),2)
        self.assertIsNotNone(page['next'])
        next_page=intervals(self.archive,scope,90,200,limit=2,before=page['next'])
        self.assertFalse({r['id'] for r in page['rows']}&{r['id'] for r in next_page['rows']})
        self.assertEqual(summary(self.archive,Scope(()),90,200,now=170)['rows'],[])

    def test_large_restart_is_drained_in_bounded_batches(self):
        first=[('8001','PJSIP/'+str(i),'available','',100,True) for i in range(1001)]
        self.cache.write(first,110,'g1')
        for _ in range(20):
            if self.source.ingest(self.archive)['caught_up']:break
        else:self.fail('initial import did not finish')
        second=[('8001','PJSIP/'+str(i),'paused','survey',200,False) for i in range(1001)]
        self.cache.write(second,210,'g2')
        for _ in range(30):
            result=self.source.ingest(self.archive)
            if result['caught_up'] and not self.archive.checkpoint('activity_cache')['resetting']:break
        else:self.fail('restart import did not finish')
        self.assertEqual(self.archive.checkpoint('activity_cache')['gaps'],1)

    def test_inventory_proves_local_alias_without_merging_trunks(self):
        inventory={'endpoints':[dict(category='extension',technology='PJSIP',endpoint='100'),
                                dict(category='trunk',technology='SIP',endpoint='100')]}
        self.assertEqual(canonical('Local/100@from-queue/n',inventory),'PJSIP/100')
        self.assertEqual(canonical('SIP/100',inventory),'SIP/100')
        self.cache.write([('8001','Local/100@from-queue/n','available','',100,True),
                          ('8002','PJSIP/100','available','',100,True)],120,'g1')
        with patch('sanequeue.reporting.activity_source.read_snapshot',return_value=inventory):self.source.ingest(self.archive)
        project_batch(self.archive)
        data=summary(self.archive,Scope(('8001','8002')),90,200,now=130)
        self.assertEqual(len(data['agents']),1)
        self.assertEqual(data['agents'][0]['unique_on_duty_seconds'],20)
        self.assertEqual(data['agents'][0]['membership_on_duty_seconds'],40)


if __name__=='__main__':unittest.main()
