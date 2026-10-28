"""Real Flask/SQLite boundaries with current queue and assignment grants."""
import time
import unittest
from unittest.mock import patch
from flask import Flask
from flask_login import LoginManager, UserMixin
from sanequeue.api.diagnostics import install
from sanequeue.diagnostics.store import Store, Scope as DiagnosticScope
from sanequeue.reporting.queries import Scope, visits
from sanequeue.reporting.store import Event
from sanequeue.reporting.facts import project_batch
from sanequeue.diagnostics.worker import Worker
from tests import test_reporting_queries as fixtures


class User(UserMixin):
    def __init__(self,ident):self.id=ident


class DiagnosticsAPITests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.ReportTests();self.case.setUp();self.addCleanup(self.case.doCleanups);self.case.seed()
        self.archive=self.case.archive;self.role='supervisor';self.queues=['8001'];self.full=False;self.cutoff=0;self.menu=True
        app=Flask(__name__);app.secret_key='synthetic-key';manager=LoginManager(app);manager.user_loader(lambda ident:User(ident))
        def context():return Scope(tuple(self.queues),('Local/100@from-queue/n',),self.role=='agent',self.cutoff),time.time()-86400,time.time()+86400
        install(app,self.archive,context=context,role=lambda:self.role,sections=lambda:['reports'] if self.menu else [],
                can_queue=lambda q,action:q in self.queues and (action!='caller_details' or self.full))
        self.client=app.test_client();self.login('user-a');self.headers={'X-CSRF-Token':'csrf'}
        self.visit=visits(self.archive,Scope(('8001',)),self.case.stamp,self.case.stamp+100)['rows'][0]['id']
        self.body={'visit_id':self.visit,'kind':'one_way_audio','description':'Private report 09123456789'}
    def login(self,user):
        with self.client.session_transaction() as session:session.update(_user_id=user,_fresh=True,csrf_token='csrf')
    def create(self):return self.client.post('/api/diagnostics/incidents',json=self.body,headers=self.headers)
    def test_manual_report_csrf_private_headers_identity_and_no_intent_verdict(self):
        self.assertEqual(self.client.post('/api/diagnostics/incidents',json=self.body).status_code,403)
        r=self.create();self.assertEqual(r.status_code,201,r.json);row=r.json['incident']
        self.assertEqual(len(row['reporter']),64);self.assertNotIn('user-a',r.text)
        self.assertEqual(row['queues'],['8001']);self.assertEqual(row['human_intent'],'unavailable')
        self.assertEqual(row['description'],self.body['description'])
        self.assertIn('no-store',r.headers['Cache-Control']);self.assertEqual(r.headers['X-Content-Type-Options'],'nosniff')
        self.assertEqual(self.client.get('/api/diagnostics/incidents').json['rows'][0]['id'],row['id'])
        self.role='viewer';self.assertEqual(self.client.get('/api/diagnostics/incidents').status_code,403)
    def test_fresh_queue_permissions_assignment_cutoff_and_foreign_uid_reuse(self):
        r=self.create();ident=r.json['incident']['id'];path='/api/diagnostics/incidents/'+ident
        self.queues=['8002'];self.assertEqual(self.client.get(path).status_code,404)
        self.queues=['8001'];self.cutoff=self.case.stamp+100
        self.assertEqual(self.client.get(path).status_code,404)
        self.cutoff=0
        with self.archive.writer() as db:
            db.execute('INSERT INTO report_visits SELECT pbx,?,callid,?,entered,answered,ended,caller,agent,outcome,wait_seconds,talk_seconds,segment_ended_by,coverage FROM report_visits WHERE id=?',('f'*64,'8002',self.visit))
        self.assertEqual(self.client.get(path).status_code,404)
        self.assertEqual(self.client.get('/api/diagnostics/incidents').json['rows'],[])
        self.queues=['8001','8002'];self.assertEqual(self.client.get(path).status_code,200)
    def test_private_human_text_is_not_a_number_policy_bypass(self):
        ident=self.create().json['incident']['id'];self.login('user-b')
        row=self.client.get('/api/diagnostics/incidents/'+ident).json['incident']
        self.assertIsNone(row['description']);self.assertNotIn('09123456789',str(row))
        self.full=True;self.assertEqual(self.client.get('/api/diagnostics/incidents/'+ident).json['incident']['description'],self.body['description'])
    def test_agent_own_report_only_comment_and_manager_versioned_actions(self):
        self.role='agent';r=self.create();self.assertEqual(r.status_code,201,r.json);ident=r.json['incident']['id'];path='/api/diagnostics/incidents/'+ident
        self.assertEqual(self.client.post(path,json={'action':'resolve'},headers=self.headers).status_code,403)
        r=self.client.post(path,json={'action':'comment','note':'My note','expected_version':1},headers=self.headers)
        self.assertEqual(r.status_code,200,r.json)
        self.login('user-b');self.assertEqual(self.client.get(path).status_code,404)
        self.role='supervisor';self.login('user-a')
        self.assertEqual(self.client.post(path,json={'action':'resolve','expected_version':1},headers=self.headers).status_code,409)
        r=self.client.post(path,json={'action':'resolve','expected_version':2},headers=self.headers)
        self.assertEqual(r.status_code,200,r.json);self.assertEqual(r.json['incident']['status'],'resolved')
        self.assertEqual(r.json['incident']['root_cause'],'unavailable')
    def test_projection_lag_and_invalid_payload_do_not_create_incidents(self):
        for payload in ({**self.body,'queues':['8002']},{**self.body,'occurred_at':float('nan')},{**self.body,'description':'x'*1001}):
            self.assertEqual(self.client.post('/api/diagnostics/incidents',json=payload,headers=self.headers).status_code,400)
        self.archive.append([Event('cel','late',self.case.stamp+50,'CHAN_START',{'uniqueid':'late'})])
        self.assertEqual(self.create().status_code,503)
        self.assertEqual(Store(self.case.root/'diagnostics.sqlite3').page(DiagnosticScope(('8001',)))['rows'],[])
    def test_admin_health_requires_all_queue_scope_and_does_not_enable_sources(self):
        self.assertEqual(self.client.get('/api/diagnostics/source-health').status_code,403)
        self.role='admin';self.assertEqual(self.client.get('/api/diagnostics/source-health').status_code,403)
        self.queues=['8001','8002'];before=self.archive.checkpoint('health:sql');r=self.client.get('/api/diagnostics/source-health')
        self.assertEqual(r.status_code,200,r.json);self.assertEqual(r.json['live_media_coverage'],'unavailable')
        self.assertNotIn('09123456789',r.text);self.assertEqual(r.json['sources']['cel']['state'],'current')
        self.assertEqual(self.archive.checkpoint('health:sql'),before)
    def test_post_read_grant_revocation_prevents_publication(self):
        ident=self.create().json['incident']['id'];actual=Store.get;changed=[]
        def get(store,*args,**kwargs):
            row=actual(store,*args,**kwargs)
            if row is not None and not changed:changed.append(True);self.queues=['8002']
            return row
        with patch.object(Store,'get',get):
            r=self.client.get('/api/diagnostics/incidents/'+ident)
        self.assertIn(r.status_code,(403,404));self.assertNotIn('09123456789',r.text)

    def test_machine_policy_recheck_uses_persisted_threshold_without_claiming_root_cause(self):
        self.archive.append([self.case.event('machine','8001','ENTERQUEUE',100,['','09123456789']),
                             self.case.event('machine','8001','CONNECT',102,['2']),
                             self.case.event('machine','8001','COMPLETECALLER',110,['2','8'])])
        while project_batch(self.archive)['processed']:pass
        store=Store(self.case.root/'diagnostics.sqlite3')
        worker=Worker(self.archive,store,generation='archive_'+'a'*32,threshold_seconds=10)
        self.assertEqual(worker.run_batch()['inserted'],1)
        rows=self.client.get('/api/diagnostics/incidents').json['rows']
        row=next(r for r in rows if r['kind']=='short_after_answer')
        self.assertTrue(row['current_rule_match']);self.assertFalse(row['current_state_verified'])
        self.assertEqual(row['rule_parameters'],{'threshold_seconds':10})
        self.assertEqual(row['status'],'needs_review');self.assertEqual(row['human_intent'],'unavailable')
        with self.archive.writer() as db:
            db.execute('UPDATE report_visits SET talk_seconds=20,ended=answered+20 WHERE id=?',(row['visit_id'],))
        changed=self.client.get('/api/diagnostics/incidents/'+row['id']).json['incident']
        self.assertFalse(changed['current_rule_match'])
        self.assertEqual(changed['classification_state'],'historical_candidate_requires_review')
        self.assertNotIn('09123456789',str(changed))

    def test_role_downgrade_during_page_never_exposes_another_reporter(self):
        self.create();self.login('user-b');actual=Store.page
        def page(store,*args,**kwargs):
            value=actual(store,*args,**kwargs);self.role='agent';return value
        with patch.object(Store,'page',page):r=self.client.get('/api/diagnostics/incidents')
        self.assertEqual(r.status_code,200,r.json);self.assertEqual(r.json['rows'],[])

    def test_revocation_during_final_private_read_and_health_read_is_enforced(self):
        ident=self.create().json['incident']['id'];actual=Store.get;reads=[]
        def get(store,*args,**kwargs):
            value=actual(store,*args,**kwargs);reads.append(1)
            if len(reads)==2:self.role='viewer'
            return value
        with patch.object(Store,'get',get):r=self.client.get('/api/diagnostics/incidents/'+ident)
        self.assertEqual(r.status_code,403,r.json);self.assertNotIn('09123456789',r.text)
        self.role='admin';self.queues=['8001','8002']
        from sanequeue.api import diagnostics as adapter
        original=adapter.source_health
        def health(*args,**kwargs):
            value=original(*args,**kwargs);self.menu=False;return value
        with patch.object(adapter,'source_health',health):r=self.client.get('/api/diagnostics/source-health')
        self.assertEqual(r.status_code,403)

    def test_hidden_pages_are_scanned_bounded_without_hidden_cursor_leaks(self):
        valid=self.create().json['incident']['id'];store=Store(self.case.root/'diagnostics.sqlite3');now=time.time()+1
        hidden=[]
        for i in range(51):
            hidden.append(store.create_manual('one_way_audio',('8001',),'b'*64,self.case.stamp,
                           visit_id=format(i+1000,'064x'),now=now+i)['id'])
        r=self.client.get('/api/diagnostics/incidents?limit=1')
        self.assertEqual(r.status_code,200,r.json);self.assertEqual([row['id'] for row in r.json['rows']],[valid])
        self.assertTrue(all(ident not in r.text for ident in hidden));self.assertIsNone(r.json['next'])

    def test_deep_json_and_unversioned_status_change_are_rejected(self):
        payload=b'{"kind":'+b'['*1200+b'0'+b']'*1200+b'}'
        r=self.client.post('/api/diagnostics/incidents',data=payload,content_type='application/json',headers=self.headers)
        self.assertEqual(r.status_code,400)
        ident=self.create().json['incident']['id']
        r=self.client.post('/api/diagnostics/incidents/'+ident,json={'action':'resolve'},headers=self.headers)
        self.assertEqual(r.status_code,400)

    def test_final_authorization_filter_marks_partial_instead_of_false_end_of_data(self):
        ident=self.create().json['incident']['id']
        from sanequeue.api import diagnostics as adapter
        original=adapter.queries._scope;calls=[]
        def changed(*args,**kwargs):
            clause,values=original(*args,**kwargs);calls.append(1)
            return (clause+' AND 0',values) if len(calls)==2 else (clause,values)
        with patch.object(adapter.queries,'_scope',changed):r=self.client.get('/api/diagnostics/incidents')
        self.assertEqual(r.status_code,200,r.json);self.assertEqual(r.json['rows'],[])
        self.assertTrue(r.json['refresh_required']);self.assertTrue(r.json['scan_limited'])
        self.assertIsNone(r.json['next']);self.assertNotIn(ident,r.text)
