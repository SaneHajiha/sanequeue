"""Read-only schedule access, scope and evidence-safe adherence API."""
import sqlite3
import unittest

from tests import test_reporting_queries as fixtures
from sanequeue.reporting import adherence_source
from sanequeue.reporting.store import QueryDeadline


class ShiftAPITests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.ReportTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.case.seed();self.path=self.case.root/'planning.db'
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE shifts(id INTEGER PRIMARY KEY,queue,agent,starts,ends,note)')
            db.executemany('INSERT INTO shifts VALUES(?,?,?,?,?,?)',[
                (1,'8001','PJSIP/100',self.case.stamp,self.case.stamp+60,'PRIVATE note'),
                (2,'8002','PJSIP/900',self.case.stamp,self.case.stamp+60,'PRIVATE other queue')])
        self.url='/api/history/adherence?from=2026-10-24&to=2026-10-25'

    def test_api_requires_both_sections_and_never_returns_notes(self):
        case=self.case
        self.assertEqual(case.client().get(self.url).status_code,403)
        self.assertEqual(case.client(menus=('shifts',)).get(self.url).status_code,403)
        client=case.client(menus=('reports','shifts'),planning_path=self.path)
        response=client.get(self.url)
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json['schedule_configured'])
        self.assertEqual([row['queue'] for row in response.json['shifts']],['8001'])
        self.assertNotIn('PRIVATE',response.get_data(as_text=True))
        row=response.json['shifts'][0]
        self.assertIsNone(row['adherence_percent'])
        self.assertIsNone(row['tardiness_seconds'])
        self.assertEqual(row['uncovered_seconds'],60)
        self.assertEqual(client.get(self.url+'&queue=8002').status_code,403)

    def test_missing_source_is_not_created(self):
        absent=self.case.root/'absent.db'
        response=self.case.client(menus=('reports','shifts'),planning_path=absent).get(self.url)
        self.assertEqual(response.status_code,200)
        self.assertFalse(response.json['schedule_configured'])
        self.assertFalse(absent.exists())

    def test_bound_excess_fails_instead_of_truncating(self):
        with sqlite3.connect(self.path) as db:
            db.executemany('INSERT INTO shifts VALUES(?,?,?,?,?,?)',[
                (i,'8001','PJSIP/100',self.case.stamp,self.case.stamp+60,'') for i in range(3,2004)])
        with self.assertRaises(QueryDeadline):
            adherence_source.read(self.path,['8001'],self.case.stamp,self.case.stamp+100)
        self.assertEqual(adherence_source.read(self.path,[],0,1)['shifts'],[])


if __name__=='__main__':unittest.main()
