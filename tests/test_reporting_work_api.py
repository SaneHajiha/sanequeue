"""Happy-call API acceptance with no queue-activity dependency."""
import unittest
from unittest.mock import patch

from tests import test_reporting_queries as fixtures
from sanequeue.reporting.store import Event
from sanequeue.reporting.facts import project_batch


class WorkAPITests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ReportTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        project_batch(self.fixture.archive)

    def test_happy_call_removed_from_all_queues_is_reported_and_masked(self):
        case = self.fixture
        client = case.client(role='admin', menus=('reports','users'), known=('PJSIP/100',))
        with client.session_transaction() as session:
            session['csrf_token'] = 'test'
        query = '?from=2026-10-24&to=2026-10-25&pause_direction=internal'
        # No activity exists. Admin uses the explicit extension inventory.
        # An allowed queue is needed for creating a scoped work session.
        case.archive.append([case.event('other-call','8001','ENTERQUEUE',0,['','200'])])
        project_batch(case.archive)
        listed = client.get('/api/history/work-sessions'+query)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json['agents'], ['PJSIP/100'])
        payload = dict(agent='PJSIP/100', purpose='happy_call', title='Customer follow-up', request_key='request-1')
        path = '/api/history/work-sessions'
        self.assertEqual(client.post(path+query,json=payload).status_code,403)
        with patch('sanequeue.reporting.work_sessions._now', return_value=case.stamp+10):
            created = client.post(path+query, json=payload, headers={'X-CSRF-Token':'test'})
        self.assertEqual(created.status_code,201)
        ident = created.json['session']['id']
        case.archive.append([Event('cdr','survey-segment',case.stamp+20,'CDR',dict(
            uniqueid='survey',linkedid='survey',channel='PJSIP/100-000000ab',dstchannel='SIP/200-000000ac',
            dst='200',duration=30,billsec=25,disposition='ANSWERED'))])
        inventory=dict(observed_at=case.stamp,endpoints=[dict(technology='PJSIP',endpoint='100',category='extension'),
                                                       dict(technology='SIP',endpoint='200',category='extension')])
        project_batch(case.archive,inventory=inventory)
        with patch('sanequeue.reporting.work_sessions._now', return_value=case.stamp+60):
            closed = client.post(path+'/'+ident+'/close'+query,headers={'X-CSRF-Token':'test'})
        self.assertEqual(closed.status_code,200)
        summary=client.get(path+'/'+ident+'/summary'+query)
        self.assertEqual(summary.status_code,200)
        self.assertEqual(summary.json['declared_seconds'],50)
        self.assertEqual(summary.json['totals']['segments_started'],1)
        self.assertEqual(summary.json['totals']['known_billsec_sum'],25)
        calls=client.get(path+'/'+ident+'/calls'+query)
        self.assertEqual(calls.status_code,200)
        self.assertEqual(calls.json['rows'][0]['destination'],'***')
        self.assertFalse(calls.json['rows'][0]['can_play'])
        self.assertEqual(client.get(path+'/'+ident+'/summary'+query+'&queue=8002').status_code,403)


if __name__ == '__main__':
    unittest.main()
