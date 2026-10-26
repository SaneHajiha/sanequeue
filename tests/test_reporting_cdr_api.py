import unittest

from tests import test_reporting_queries as fixtures
from sanequeue.reporting.store import Event
from sanequeue.reporting.facts import project_batch


class CDRAPITests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.ReportTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        case=self.case;case.seed()
        case.archive.append([Event('cdr','segment',case.stamp+10,'CDR',dict(
            src='02199999999',dst='09123456789',channel='PJSIP/100-000000aa',
            dstchannel='PJSIP/provider-000000ab',uniqueid='private',linkedid='private',
            outbound_cnum='02112345678',did='02188888888',duration=30,billsec=20,disposition='ANSWERED'))])
        project_batch(case.archive,inventory=dict(observed_at=case.stamp,endpoints=[
            dict(technology='PJSIP',endpoint='100',category='extension'),
            dict(technology='PJSIP',endpoint='provider',category='trunk')]))
        self.query='?from=2026-10-24&to=2026-10-25'

    def test_supervisor_and_queue_only_admin_cannot_get_global_cdr(self):
        for client in (self.case.client(),self.case.client(role='supervisor',menus=('reports','users')),
                       self.case.client(role='admin'),self.case.client(role='admin',menus=('users',))):
            self.assertEqual(client.get('/api/history/cdr'+self.query).status_code,403)

    def test_partial_queue_grants_are_not_global_authorization(self):
        # The fixture allows queue 8001 only. 8002 existing in the archive
        # prevents global CDR access even when the selected request is 8001.
        client=self.case.client(role='admin',menus=('reports','users'),details=True)
        self.assertEqual(client.get('/api/history/cdr'+self.query).status_code,403)

    def test_masked_output_search_gate_and_global_aggregate_alignment(self):
        # Restrict the synthetic archive to a single authorized queue.
        with self.case.archive.writer() as db:
            db.execute("DELETE FROM report_visits WHERE queue='8002'")
        masked=self.case.client(role='admin',menus=('reports','users'))
        response=masked.get('/api/history/cdr'+self.query)
        self.assertEqual(response.status_code,200,response.json)
        row=response.json['rows'][0]
        self.assertNotEqual(row['dst'],'09123456789')
        self.assertFalse(response.json['can_search_numbers'])
        self.assertNotIn('private',response.get_data(as_text=True))
        self.assertFalse(response.json['audio_granted'])
        self.assertEqual(masked.get('/api/history/cdr'+self.query+'&party=100').status_code,403)
        full=self.case.client(role='admin',menus=('reports','users'),details=True)
        response=full.get('/api/history/cdr'+self.query+'&origin=100')
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(len(response.json['rows']),1)
        summary=full.get('/api/history/cdr/summary'+self.query+'&origin=100')
        self.assertEqual(summary.status_code,200)
        self.assertEqual(summary.json['totals']['segments_started'],1)
        self.assertEqual(sum(row['segments_started'] for row in summary.json['trunk_traffic']),1)
        self.assertEqual(full.get('/api/history/cdr'+self.query+'&queue=8001').status_code,403)


if __name__=='__main__':unittest.main()
