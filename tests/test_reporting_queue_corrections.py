"""Source revisions are evidence history, not additional queue visits."""
from pathlib import Path
import tempfile
import unittest
from sanequeue.reporting.store import Archive, Event
from sanequeue.reporting.facts import project_batch, _visit_id, _rebuild_visits, PROJECTION_VERSION
from sanequeue.reporting.queries import Scope, visits
from sanequeue.reporting.visit_snapshots import capture, page


class QueueCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.archive=Archive(Path(self.temp.name)/'history.sqlite3',min_free_bytes=0)
        self.archive.initialize()
    def event(self,key,ts,kind,values=(),*,queue='8001',call='call-a',source='queue_log'):
        return Event(source,key,ts,kind,dict(queue=queue,callid=call,agent='Local/100@from-queue/n',values=list(values)))
    def project(self,**kw):
        results=[]
        while True:
            result=project_batch(self.archive,**kw);results.append(result)
            if not result['processed']:return results
    def seed(self):
        self.archive.append([self.event('enter',100,'ENTERQUEUE',['','0000000000']),
                             self.event('connect',101,'CONNECT',['1','agent-a']),
                             self.event('complete',103,'COMPLETEAGENT',['1','2'])])
        self.project()
    def rows(self,queues=('8001',)):
        return visits(self.archive,Scope(queues),90,200)['rows']
    def snapshot(self,token):
        with self.archive.reader() as db:return page(db,self.archive.pbx,token,Scope(('8001',)),90,200)
    def test_corrected_completion_replaces_duration_and_keeps_pinned_export_and_history(self):
        self.seed();token=capture(self.archive);original_id=self.rows()[0]['id']
        self.archive.append([self.event('complete',130,'COMPLETEAGENT',['1','29'])]);self.project()
        current=self.rows();self.assertEqual(len(current),1)
        self.assertEqual((current[0]['id'],current[0]['coverage'],current[0]['talk_seconds']), (original_id,'observed',29))
        self.assertEqual([(row['id'],row['talk_seconds']) for row in self.snapshot(token)],[(original_id,2)])
        with self.archive.reader() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE source_key='complete'").fetchone()[0],2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM report_queue_events").fetchone()[0],4)
        self.assertEqual(project_batch(self.archive)['processed'],0)
    def test_future_source_revision_does_not_apply_before_projection_watermark(self):
        self.seed()
        self.archive.append([self.event('unused',104,'CONFIGRELOAD'),self.event('complete',130,'COMPLETEAGENT',['1','29'])])
        project_batch(self.archive,limit=1)
        self.assertEqual([(r['coverage'],r['talk_seconds']) for r in self.rows()],[('observed',2)])
        project_batch(self.archive,limit=1)
        self.assertEqual([(r['coverage'],r['talk_seconds']) for r in self.rows()],[('observed',29)])
    def test_changed_identity_and_invalid_payload_rebuild_old_pair(self):
        self.seed()
        self.archive.append([self.event('complete',130,'COMPLETEAGENT',['1','29'],queue='8002',call='call-b')]);self.project()
        old=self.rows();self.assertEqual(len(old),1);self.assertEqual(old[0]['outcome'],'connected');self.assertIsNone(old[0]['talk_seconds'])
        new=self.rows(('8002',));self.assertEqual(len(new),1);self.assertEqual(new[0]['coverage'],'missing_entry')
        # A later unusable revision still supersedes its old source item.
        self.archive.append([self.event('complete',131,'COMPLETEAGENT',['1','30'],queue='',call='')]);self.project()
        self.assertEqual(self.rows(('8002',)),[])
    def test_corrected_kind_and_enter_identity_do_not_retain_obsolete_visit(self):
        self.seed();old_id=self.rows()[0]['id']
        self.archive.append([self.event('complete',130,'CONFIGRELOAD')]);self.project()
        self.assertEqual(self.rows()[0]['outcome'],'connected')
        self.archive.append([self.event('enter',102,'ENTERQUEUE',['','0000000001'])]);self.project()
        rows=self.rows();self.assertNotIn(old_id,{row['id'] for row in rows})
        observed=[row for row in rows if row['caller']=='0000000001'];self.assertEqual(len(observed),1)
    def test_same_key_in_other_source_or_pbx_does_not_supersede(self):
        self.seed()
        other=Archive(self.archive.path,pbx='other',min_free_bytes=0)
        other.append([self.event('complete',130,'COMPLETEAGENT',['1','29'])]);project_batch(other)
        self.archive.append([self.event('complete',130,'CHAN_START',source='cel')]);self.project()
        self.assertEqual(self.rows()[0]['talk_seconds'],2)
    def test_v9_upgrade_replays_bounded_and_repairs_existing_bad_derived_rows(self):
        self.seed();token=capture(self.archive);old=self.rows()[0]
        self.archive.append([self.event('complete',130,'COMPLETEAGENT',['1','29'])]);self.project()
        with self.archive.writer() as db:
            event_id=db.execute("SELECT MAX(id) FROM events WHERE source_key='complete'").fetchone()[0]
            db.execute('UPDATE report_visits SET ended=103,talk_seconds=2 WHERE id=?',(old['id'],))
            db.execute('INSERT INTO report_visits VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       ('primary',_visit_id('primary','8001','call-a',event_id),'call-a','8001',130,None,130,'','Local/100@from-queue/n','answered',1,29,'agent','missing_entry'))
            db.execute('UPDATE report_projection_version SET version=9')
        self.assertEqual(len(self.rows()),2)
        results=self.project(limit=1);self.assertTrue(all(result['processed']<=1 for result in results))
        self.assertEqual(PROJECTION_VERSION,10)
        self.assertEqual([(r['coverage'],r['talk_seconds']) for r in self.rows()],[('observed',29)])
        self.assertEqual([(r['coverage'],r['talk_seconds']) for r in self.snapshot(token)],[('observed',2)])
    def test_raw_version_limit_remains_before_superseded_filter(self):
        self.seed()
        with self.archive.writer() as db:
            db.executemany('INSERT INTO report_queue_events VALUES(?,?,?,?,?,?,?,?)',
                           [('primary',10000+n,'call-a','8001','',100,'UNKNOWN','[]') for n in range(10001)])
            with self.assertRaisesRegex(ValueError,'queue_call_evidence_limit'):
                _rebuild_visits(db,'primary','8001','call-a',3)
    def test_rebuild_uses_call_identity_index_not_a_pbx_wide_event_range(self):
        self.seed();recorded=[]
        with self.archive.writer() as db:
            class Connection:
                def execute(self,sql,args=()):
                    if 'SELECT r.event_id,r.ts,r.kind' in sql:recorded.append((sql,args))
                    return db.execute(sql,args)
            _rebuild_visits(Connection(),'primary','8001','call-a',3)
            self.assertEqual(len(recorded),1)
            sql,args=recorded[0]
            plan=' '.join(row[3] for row in db.execute('EXPLAIN QUERY PLAN '+sql,args))
            self.assertIn('SEARCH r USING INDEX rq_call',plan)
            self.assertIn('USING COVERING INDEX event_source',plan)
            self.assertNotIn('SCAN r',plan)
