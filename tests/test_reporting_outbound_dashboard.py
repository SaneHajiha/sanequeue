import unittest
from unittest.mock import patch
from tests.test_reporting_cdr_api import CDRAPITests
from sanequeue.reporting.outbound_dashboard import report
from sanequeue.reporting.store import QueryDeadline


class OutboundDashboardTests(unittest.TestCase):
    def setUp(self):
        fixture=CDRAPITests();fixture.setUp();self.addCleanup(fixture.case.doCleanups);self.c=fixture.case
        with self.c.archive.writer() as db:
            db.execute("DELETE FROM report_visits WHERE queue='8002'")
            base=self.c.stamp
            for i,(disp,duration,bill,dest) in enumerate([('ANSWERED',30,5,'09123456789'),('BUSY',7,0,'09123456789'),('ANSWERED',8,None,'09111111111'),('UNKNOWN',4,None,'')]):
                key='synthetic'+str(i)
                db.execute('INSERT INTO report_cdr VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    ('primary',key,100+i,base+20+i,'','','100',dest,'','',duration,bill,disp,''))
                db.execute('INSERT INTO report_cdr_parties VALUES(?,?,?,?,?)',('primary',key,'100','outbound',base+20+i))
        self.start=self.c.stamp;self.end=self.start+100;self.query='?from=2026-10-24&to=2026-10-25'

    def test_segments_denominators_and_uncertain_human_answer(self):
        result=report(self.c.archive,self.start,self.end,numbers=True);total=result['totals']
        self.assertEqual((total['segments'],total['answered'],total['unanswered'],total['unknown']),(5,3,1,1))
        self.assertEqual(total['known_dispositions'],4);self.assertEqual(total['technical_answer_rate'],75)
        self.assertEqual((result['dispositions']['ANSWERED'],result['dispositions']['BUSY'],result['dispositions']['OTHER']),(3,1,1))
        self.assertEqual((total['answered_known_billsec'],total['short_answered']),(2,1))
        self.assertEqual(total['short_answered_rate'],50);self.assertEqual(total['average_answered_billsec'],12.5)
        self.assertEqual(total['average_pre_answer'],17.5);self.assertEqual(total['known_setup'],2)
        self.assertEqual(result['unique_destinations'],2);self.assertEqual(result['unknown_destination'],1)
        self.assertIn('not_proof_of_human',result['definitions']['technical_answer'])
        self.assertEqual(sum(x['segments'] for x in result['origins']),total['segments'])
        self.assertNotIn('09123456789',str(result))

    def test_bounded_scope_and_role_number_policy(self):
        with patch('sanequeue.reporting.outbound_dashboard.MAX_SEGMENTS',1):
            with self.assertRaises(QueryDeadline):report(self.c.archive,self.start,self.end)
        masked=self.c.client(role='admin',menus=('reports','users'),details=False)
        response=masked.get('/api/history/cdr/outbound-dashboard'+self.query)
        self.assertEqual(response.status_code,200,response.json);self.assertIsNone(response.json['unique_destinations'])
        self.assertNotIn('09123456789',response.text);self.assertNotIn('02199999999',response.text)
        self.assertEqual(masked.get('/api/history/cdr/outbound-dashboard'+self.query+'&party=100').status_code,403)
        self.assertEqual(self.c.client(role='supervisor',menus=('reports','users'),details=True).get('/api/history/cdr/outbound-dashboard'+self.query).status_code,403)
        full=self.c.client(role='admin',menus=('reports','users'),details=True)
        self.assertEqual(full.get('/api/history/cdr/outbound-dashboard'+self.query+'&direction=inbound').status_code,400)

    def test_permission_is_rechecked_after_archive_read(self):
        denied=[];client=self.c.client(role='admin',menus=('reports','users'),details=True,denied=denied)
        original=report
        def revoke(*args,**kwargs):
            result=original(*args,**kwargs);denied.append('caller_details');return result
        with patch('sanequeue.api.reports.outbound_dashboard.report',side_effect=revoke):
            response=client.get('/api/history/cdr/outbound-dashboard'+self.query)
        self.assertEqual(response.status_code,403);self.assertNotIn('09123456789',response.text)


if __name__=='__main__':unittest.main()
