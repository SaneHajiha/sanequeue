"""Time metrics retain report-menu and assignment scopes."""
import unittest
from tests import test_reporting_queries as fixtures


class AgentMetricsAPITests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.ReportTests();self.case.setUp();self.addCleanup(self.case.doCleanups);self.case.seed()

    def test_scope_unknown_metrics_and_no_private_call_identity(self):
        c=self.case;url='/api/history/agent-metrics'+c.dates
        response=c.client().get(url)
        self.assertEqual(response.status_code,200,response.json)
        self.assertFalse(response.json['complete_conversation'])
        for row in response.json['agents']:
            self.assertIsNone(row['aht_seconds']);self.assertIsNone(row['occupancy_percent'])
            self.assertNotIn('caller',row);self.assertNotIn('callid',row)
        self.assertNotIn('09999999999',response.get_data(as_text=True))
        self.assertEqual(c.client(menus=()).get(url).status_code,403)
        self.assertEqual(c.client().get(url+'&queue=8002').status_code,403)
        own=c.client(role='agent').get(url)
        self.assertEqual(own.status_code,200,own.json)


if __name__=='__main__':unittest.main()
