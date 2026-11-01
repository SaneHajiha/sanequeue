"""Later contact is scoped evidence, not proof of a successful callback."""
import unittest
from unittest.mock import patch
from tests import test_reporting_queries as fixtures
from sanequeue.reporting.facts import project_batch
from sanequeue.reporting.queries import Scope
from sanequeue.reporting.followup import report,outbound_candidates
from sanequeue.reporting.store import QueryDeadline,Event


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

    def test_access_revocation_during_query_never_returns_old_followup_rows(self):
        self.seed();denied=[];client=self.case.client(role='supervisor',denied=denied)
        def revoke(*args,**kwargs):
            value=report(*args,**kwargs);denied.append('view');return value
        with patch('sanequeue.api.reports.followup.report',side_effect=revoke):
            response=client.get('/api/history/followup'+self.case.dates)
        self.assertEqual(response.status_code,403);self.assertNotIn('09123456789',response.get_data(as_text=True))

    def test_manual_actions_require_caller_permission_and_csrf_are_idempotent_and_not_call_proof(self):
        self.seed();c=self.case
        visit=report(c.archive,Scope(('8001',)),c.stamp,c.stamp+6,now=c.stamp+100)['rows'][0]['id']
        path='/api/history/followup/'+visit+'/actions'+c.dates
        restricted=c.client(role='supervisor',details=False);self.assertEqual(restricted.get(path).status_code,403)
        client=c.client(role='supervisor',details=True)
        with client.session_transaction() as session:session['csrf_token']='token'
        body=dict(status='reached',note='declared contact',request_key='request-one')
        self.assertEqual(client.post(path,json=body).status_code,403)
        response=client.post(path,json=body,headers={'X-CSRF-Token':'token'})
        self.assertEqual(response.status_code,201,response.json);action=response.json['action']
        self.assertEqual(action['evidence'],'user_reported');self.assertFalse(action['outbound_call_proven'])
        retry=client.post(path,json=body,headers={'X-CSRF-Token':'token'})
        self.assertEqual(retry.json['action']['id'],action['id'])
        conflict=client.post(path,json={**body,'status':'closed'},headers={'X-CSRF-Token':'token'})
        self.assertEqual(conflict.status_code,409)
        history=client.get(path);self.assertEqual(history.status_code,200);self.assertEqual(len(history.json['rows']),1)
        self.assertEqual(c.client(role='agent',details=True).get(path).status_code,403)
        self.assertEqual(client.get(path+'&queue=8002').status_code,403)
        self.assertNotIn('09123456789',history.get_data(as_text=True))
        with self.assertRaises(Exception):
            with c.client(role='supervisor',details=True).application.app_context():
                from sanequeue.reporting.quality import QualityStore
                store=QualityStore(c.root/'quality.sqlite3')
                with store._db(write=True) as db:db.execute('DELETE FROM followup_actions')

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

    def test_outbound_candidates_require_observed_abandonment_number_and_evidence(self):
        self.seed();c=self.case
        inventory=dict(observed_at=c.stamp,endpoints=[dict(technology='PJSIP',endpoint='100',category='extension'),dict(technology='PJSIP',endpoint='provider',category='trunk')])
        def cdr(key,ts,dst,channel='PJSIP/100-aa',dstchannel='PJSIP/provider-bb'):
            return Event('cdr',key,ts,'CDR',dict(src='100',dst=dst,channel=channel,dstchannel=dstchannel,disposition='ANSWERED',duration=12,billsec=8))
        c.archive.append([cdr('correct',c.stamp+40,'09123456789'),cdr('other',c.stamp+42,'09111111111'),
            cdr('inbound',c.stamp+43,'09123456789',channel='PJSIP/provider-aa',dstchannel='PJSIP/100-bb')])
        while project_batch(c.archive,inventory=inventory)['processed']:pass
        with c.archive.reader() as db:visit=dict(db.execute("SELECT * FROM report_visits WHERE outcome='abandoned' AND queue='8001'").fetchone())
        result=outbound_candidates(c.archive,visit,now=c.stamp+100)
        self.assertEqual([row['id'] for row in result['rows']],['correct']);self.assertNotIn('09123456789',str(result))
        self.assertEqual(outbound_candidates(c.archive,visit,source_key='other',now=c.stamp+100)['rows'],[])
        self.assertFalse(outbound_candidates(c.archive,{**visit,'coverage':'missing_entry'},now=c.stamp+100)['available'])
        self.assertFalse(outbound_candidates(c.archive,{**visit,'caller':'anonymous'},now=c.stamp+100)['available'])
        self.assertEqual(outbound_candidates(c.archive,visit,now=c.stamp+10)['rows'],[])
        with self.assertRaises(ValueError):outbound_candidates(c.archive,visit,window_days=31)

    def test_linked_cdr_evidence_is_global_admin_only_frozen_and_does_not_prove_causation(self):
        self.seed();c=self.case
        with c.archive.writer() as db:db.execute("DELETE FROM report_visits WHERE queue='8002'")
        inventory=dict(observed_at=c.stamp,endpoints=[dict(technology='PJSIP',endpoint='100',category='extension'),dict(technology='PJSIP',endpoint='provider',category='trunk')])
        c.archive.append([Event('cdr','outbound-proof',c.stamp+40,'CDR',dict(src='100',dst='09123456789',
            channel='PJSIP/100-aa',dstchannel='PJSIP/provider-bb',disposition='ANSWERED',duration=12,billsec=8))])
        while project_batch(c.archive,inventory=inventory)['processed']:pass
        with c.archive.writer() as db:db.execute("DELETE FROM report_visits WHERE queue='8002'")
        visit=report(c.archive,Scope(('8001',)),c.stamp,c.stamp+6,now=c.stamp+100)['rows'][0]['id']
        base='/api/history/followup/'+visit;query=c.dates
        client=c.client(role='admin',menus=('reports','users'),details=True)
        with client.session_transaction() as session:session['csrf_token']='token'
        headers={'X-CSRF-Token':'token'}
        action=client.post(base+'/actions'+query,json=dict(status='reached',note='',request_key='one'),headers=headers)
        self.assertEqual(action.status_code,201,action.json);action_id=action.json['action']['id']
        path=base+'/actions/'+action_id+'/cdr-evidence'+query
        candidates=client.get(base+'/cdr-candidates'+query);self.assertEqual(candidates.status_code,200,candidates.json)
        self.assertEqual([r['id'] for r in candidates.json['rows']],['outbound-proof']);self.assertNotIn('09123456789',candidates.text)
        body=dict(source_key='outbound-proof',request_key='evidence-one',window_days=7)
        self.assertEqual(client.post(path,json=body).status_code,403)
        result=client.post(path,json=body,headers=headers);self.assertEqual(result.status_code,201,result.json)
        self.assertEqual(result.json['evidence']['attribution'],'manual_link_same_number_not_proof_of_causation')
        retry=client.post(path,json=body,headers=headers);self.assertEqual(retry.json['evidence']['id'],result.json['evidence']['id'])
        self.assertEqual(client.post(path,json={**body,'source_key':'bogus'},headers=headers).status_code,404)
        self.assertEqual(len(client.get(path).json['rows']),1)
        c.archive.append([Event('cdr','outbound-proof',c.stamp+40,'CDR',dict(src='100',dst='09123456789',
            channel='PJSIP/100-aa',dstchannel='PJSIP/provider-bb',disposition='ANSWERED',duration=12,billsec=5))])
        while project_batch(c.archive,inventory=inventory)['processed']:pass
        self.assertEqual(client.get(path).json['rows'][0]['cdr']['billsec'],8)
        self.assertEqual(client.post(path,json=body,headers=headers).status_code,409)
        self.assertEqual(c.client(role='supervisor',menus=('reports','users'),details=True).get(base+'/cdr-candidates'+query).status_code,403)
        self.assertEqual(c.client(role='admin',menus=('reports','users'),details=False).get(base+'/cdr-candidates'+query).status_code,403)

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

