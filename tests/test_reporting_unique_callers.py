import unittest
from unittest.mock import patch
from tests import test_reporting_queries as fixtures
from sanequeue.reporting.queries import Scope
from sanequeue.reporting.unique_callers import report


class UniqueCallerTests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.ReportTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.case.seed()
        self.start=self.case.stamp
        with self.case.archive.writer() as db:
            db.execute('DELETE FROM report_visits')
            rows=[]
            for i,(queue,day,caller,coverage) in enumerate([
                ('8001',0,'09121234567','observed'),('8001',0,'۰۹۱۲۱۲۳۴۵۶۷','observed'),
                ('8001',1,'09121234567','observed'),('8002',0,'09121234567','observed'),
                ('8001',0,'+989121234567','observed'),('8001',0,'anonymous','observed'),
                ('8001',0,'09120000000','missing_entry')]):
                rows.append(('primary',format(i+1,'064x'),'call'+str(i),queue,self.start+day*86400,
                    None,None,caller,'PJSIP/100','abandoned',None,None,None,coverage))
            db.executemany('INSERT INTO report_visits VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',rows)

    def test_unique_scope_daily_unknown_and_nonadditive_queues(self):
        r=report(self.case.archive,Scope(('8001','8002')),self.start,self.start+2*86400)
        self.assertEqual((r['total_unique'],r['known_number_visits'],r['unknown_number_visits'],r['missing_entry_visits']),(2,5,1,1))
        self.assertEqual([row['unique_numbers'] for row in r['by_day']],[2,1])
        self.assertEqual([row['unique_numbers'] for row in r['by_queue']],[2,1])
        self.assertNotIn('09121234567',str(r))
        self.assertFalse(r['contract']['customer_identity_proven'])
        restricted=report(self.case.archive,Scope(('8002',)),self.start,self.start+2*86400)
        self.assertEqual(restricted['total_unique'],1)
        self.assertEqual(report(self.case.archive,Scope(()),self.start,self.start+2*86400)['total_unique'],0)

    def test_limit_never_returns_partial_aggregate(self):
        with patch('sanequeue.reporting.unique_callers.MAX_VISITS',3):
            result=report(self.case.archive,Scope(('8001',)),self.start,self.start+2*86400)
        self.assertEqual(result['state'],'limited');self.assertNotIn('total_unique',result)

    def test_ten_visits_in_one_day_are_one_distinct_number(self):
        with self.case.archive.writer() as db:
            db.execute('DELETE FROM report_visits')
            db.executemany('INSERT INTO report_visits VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                [('primary',format(i+1,'064x'),'call'+str(i),'8001',self.start+i,
                  None,None,'09121234567','PJSIP/100','abandoned',None,None,None,'observed') for i in range(10)])
        result=report(self.case.archive,Scope(('8001',)),self.start,self.start+86400)
        self.assertEqual(result['total_unique'],1)
        self.assertEqual(result['known_number_visits'],10)
        self.assertEqual(result['by_day'][0]['unique_numbers'],1)

    def test_api_requires_number_permission_and_never_leaks_number(self):
        url='/api/history/unique-callers'+self.case.dates
        no_details=self.case.client(role='admin',menus=('reports',),details=False)
        self.assertEqual(no_details.get(url).status_code,403)
        allowed=self.case.client(role='admin',menus=('reports',),details=True)
        response=allowed.get(url);self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.headers['Cache-Control'],'private, no-store')
        self.assertNotIn('09121234567',response.text)
        self.assertEqual(self.case.client(role='agent',menus=('reports',),details=True).get(url).status_code,403)


if __name__=='__main__':unittest.main()
