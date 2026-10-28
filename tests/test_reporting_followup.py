"""Later contact is scoped evidence, not proof of a successful callback."""
import unittest
from unittest.mock import patch
from tests import test_reporting_queries as fixtures
from sanequeue.reporting.facts import project_batch
from sanequeue.reporting.queries import Scope
from sanequeue.reporting.followup import report
from sanequeue.reporting.store import QueryDeadline


class FollowupTests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.ReportTests();self.case.setUp();self.addCleanup(self.case.doCleanups)

    def seed(self):
        c=self.case;c.archive.append([
            c.event('first','8001','ENTERQUEUE',0,['','09123456789']),
            c.event('first','8001','ABANDON',5,['1','1','5']),
            c.event('foreign','8002','ENTERQUEUE',10,['','09123456789']),
            c.event('foreign','8002','CONNECT',12,['2','foreign-peer']),
            c.event('again','8001','ENTERQUEUE',20,['','09123456789']),
            c.event('again','8001','CONNECT',23,['3','peer']),
            c.event('again','8001','COMPLETECALLER',30,['3','7'])])
        while project_batch(c.archive)['processed']:pass

    def test_same_identity_after_abandon_and_scope(self):
        self.seed();c=self.case
        data=report(c.archive,Scope(('8001',)),c.stamp,c.stamp+6,now=c.stamp+100)
        row=data['rows'][0]
        self.assertEqual(row['first_reentry']['entered'],c.stamp+20)
        self.assertEqual(row['later_answered']['queue'],'8001')
        self.assertFalse(row['window_elapsed']);self.assertFalse(data['outbound_callback_proven'])
        self.assertFalse(data['complete_history'])
        both=report(c.archive,Scope(('8001','8002')),c.stamp,c.stamp+6,now=c.stamp+100)
        self.assertEqual(both['rows'][0]['first_reentry']['queue'],'8002')
        self.assertEqual(report(c.archive,Scope(('8002',)),c.stamp,c.stamp+6)['rows'],[])

    def test_api_masks_and_agent_is_forbidden(self):
        self.seed();c=self.case
        response=c.client(role='supervisor').get('/api/history/followup'+c.dates)
        self.assertEqual(response.status_code,200,response.json)
        self.assertNotIn('09123456789',response.get_data(as_text=True))
        self.assertEqual(response.json['rows'][0]['caller'],'0912***6789')
        self.assertEqual(c.client(role='agent').get('/api/history/followup'+c.dates).status_code,403)
        self.assertEqual(c.client().get('/api/history/followup'+c.dates+'&window_days=31').status_code,400)

    def test_deadline_and_no_matching_unproven_boundary(self):
        self.seed();c=self.case
        self.assertEqual(report(c.archive,Scope(('8001',)),c.stamp,c.stamp+6,now=c.stamp+6)['rows'][0]['first_reentry'],None)
        with self.assertRaises(ValueError):report(c.archive,Scope(('8001',),('PJSIP/100',),True),c.stamp,c.stamp+6)

    def test_later_answer_is_not_claimed_before_actual_answer_time(self):
        self.seed();c=self.case
        row=report(c.archive,Scope(('8001',)),c.stamp,c.stamp+6,now=c.stamp+22)['rows'][0]
        self.assertIsNotNone(row['first_reentry']);self.assertIsNone(row['later_answered'])
        row=report(c.archive,Scope(('8001',)),c.stamp,c.stamp+6,now=c.stamp+24)['rows'][0]
        self.assertEqual(row['later_answered']['answered'],c.stamp+23)

    def test_window_starts_at_abandonment_and_answer_boundary_is_exclusive(self):
        self.seed();c=self.case
        with c.archive.writer() as db:
            db.execute("UPDATE report_visits SET entered=?,answered=? WHERE queue='8001' AND outcome='answered'",
                (c.stamp+86404,c.stamp+86405))
        row=report(c.archive,Scope(('8001',)),c.stamp,c.stamp+6,window_days=1,now=c.stamp+90000)['rows'][0]
        self.assertIsNotNone(row['first_reentry']);self.assertIsNone(row['later_answered'])
        self.assertEqual(row['observation_end'],c.stamp+86405);self.assertTrue(row['window_elapsed'])

    def test_unknown_identity_or_unproven_source_never_matches(self):
        self.seed();c=self.case
        for value in (' anonymous ','<unknown>','Unavailable','   '):
            with self.subTest(value=value):
                with c.archive.writer() as db:db.execute('UPDATE report_visits SET caller=?',(value,))
                row=report(c.archive,Scope(('8001',)),c.stamp,c.stamp+6,now=c.stamp+100)['rows'][0]
                self.assertFalse(row['matchable']);self.assertIsNone(row['first_reentry'])
        with c.archive.writer() as db:db.execute("UPDATE report_visits SET caller='200',coverage='unknown'")
        self.assertFalse(report(c.archive,Scope(('8001',)),c.stamp,c.stamp+6,now=c.stamp+100)['rows'][0]['matchable'])

    def test_scope_cutoff_empty_scope_and_deadline(self):
        self.seed();c=self.case
        self.assertEqual(report(c.archive,Scope(()),c.stamp,c.stamp+6,now=c.stamp+100)['rows'],[])
        self.assertEqual(report(c.archive,Scope(('8001',),not_before=c.stamp+6),c.stamp,c.stamp+6,now=c.stamp+100)['rows'],[])
        with patch('sanequeue.reporting.followup.time.monotonic',side_effect=[0,10]):
            with self.assertRaises(QueryDeadline):report(c.archive,Scope(('8001',)),c.stamp,c.stamp+6,now=c.stamp+100)

    def test_ongoing_known_entry_counts_without_completion_but_missing_entry_does_not(self):
        self.seed();c=self.case;scope=Scope(('8001','8002'))
        row=report(c.archive,scope,c.stamp,c.stamp+6,now=c.stamp+15)['rows'][0]
        self.assertEqual(row['first_reentry']['queue'],'8002')
        self.assertEqual(row['later_answered']['queue'],'8002')
        with c.archive.writer() as db:
            db.execute("UPDATE report_visits SET answered=NULL,outcome='waiting' WHERE queue='8002'")
        row=report(c.archive,scope,c.stamp,c.stamp+6,now=c.stamp+15)['rows'][0]
        self.assertEqual(row['first_reentry']['queue'],'8002');self.assertIsNone(row['later_answered'])
        with c.archive.writer() as db:db.execute("UPDATE report_visits SET coverage='missing_entry' WHERE queue='8002'")
        self.assertIsNone(report(c.archive,scope,c.stamp,c.stamp+6,now=c.stamp+15)['rows'][0]['first_reentry'])

    def test_abandonment_in_future_is_not_reported_as_already_abandoned(self):
        self.seed();c=self.case
        self.assertEqual(report(c.archive,Scope(('8001',)),c.stamp,c.stamp+6,now=c.stamp+4)['rows'],[])
        row=report(c.archive,Scope(('8001',)),c.stamp,c.stamp+6,now=c.stamp+5)['rows'][0]
        self.assertTrue(row['matchable']);self.assertIsNone(row['first_reentry'])


if __name__=='__main__':unittest.main()
