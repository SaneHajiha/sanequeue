import unittest
from sanequeue.reporting.customer_segments import CustomerSegments
from tests import test_reporting_queries as fixtures


class CustomerSegmentAPITests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.ReportTests();self.case.setUp();self.addCleanup(self.case.doCleanups);self.case.seed()
        self.client=self.case.client(role='admin',menus=('reports',),details=True)
        with self.client.session_transaction() as session:session['csrf_token']='test'
        self.path='/api/history/customer-segments';self.url=self.path+self.case.dates
        self.body=dict(queue='8001',number='09123456789',enabled=True,apply_from_period_start=True,request_key='one')
        self.headers={'X-CSRF-Token':'test'}

    def test_csrf_menu_queue_and_full_number_grant_enforced(self):
        url=self.path+'/vip'+self.case.dates
        self.assertEqual(self.client.post(url,json=self.body).status_code,403)
        self.assertEqual(self.client.post(url,json=dict(self.body,queue='8002'),headers=self.headers).status_code,403)
        self.assertEqual(self.case.client().post(url,json=self.body,headers=self.headers).status_code,403)
        response=self.client.post(url,json=self.body,headers=self.headers)
        self.assertEqual(response.status_code,201,response.json)
        self.assertEqual(self.client.post(url,json=self.body,headers=self.headers).json['id'],response.json['id'])
        data=self.client.get(self.url);self.assertEqual(data.status_code,200,data.json)
        self.assertEqual(data.json['vip'][0]['classification'],'vip')
        self.assertEqual(data.headers['Cache-Control'],'private, no-store')

    def test_masking_current_menu_and_agent_denial(self):
        self.client.post(self.path+'/vip'+self.case.dates,json=self.body,headers=self.headers)
        store=CustomerSegments(self.case.root/'customer-segments.sqlite3')
        store.import_blocks('pbx_export',[dict(id='one',queue='8001',number='09123456789',at=self.case.stamp+5,reason='blacklist')])
        response=self.case.client().get(self.url)
        self.assertEqual(response.status_code,200,response.json)
        self.assertNotIn('09123456789',response.get_data(as_text=True));self.assertFalse(response.json['can_manage'])
        self.assertEqual(self.case.client(role='agent').get(self.url).status_code,403)
        self.assertEqual(self.case.client(menus=()).get(self.url).status_code,403)
        self.assertEqual(self.client.get(self.url+'&queue=8002').status_code,403)


if __name__=='__main__':unittest.main()
