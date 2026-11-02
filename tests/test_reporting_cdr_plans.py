import json
import os
import unittest
from unittest.mock import patch

from tests.test_reporting_builder_plans import BuilderPlanWorkerTests
from tests.test_reporting_cdr_api import CDRAPITests
from sanequeue.reporting.export_jobs import ExportWorker,JobStore,Limits
from sanequeue.reporting.plan_worker import current_cdr_modes
from sanequeue.reporting.report_plans import SavedReports


class CDRPlanWorkerTests(BuilderPlanWorkerTests):
    def save_cdr(self,**changes):
        data=dict(owner='owner',name='Scheduled PBX',queues=['8001'],format='pdf',language='en',enabled=True,
                  cdr_definition=dict(columns=['direction','billsec'],group_by=['direction']),cdr_filters={'direction':'outbound'})
        data.update(changes);return self.plans.save(**data)

    def seed_cdr(self):
        stamp=self.stamp-86400+3600
        with self.archive.writer() as db:
            db.execute('INSERT INTO report_visits VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                ('primary','a'*64,'q','8001',stamp,stamp+1,stamp+4,'09123456789','100','answered',1,3,'caller','observed'))
            db.execute('INSERT INTO report_cdr VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                ('primary','cdr1',1,stamp,'','','100','09123456789','','',12,8,'ANSWERED',''))
            db.execute('INSERT INTO report_cdr_parties VALUES(?,?,?,?,?)',('primary','cdr1','100','outbound',stamp))

    def test_cdr_schedule_is_denied_without_explicit_global_authorizer(self):
        self.seed_cdr();plan=self.save_cdr();result=self.worker.run_once()
        self.assertEqual(result['reason'],'access_revoked');self.assertEqual(self.jobs.list('owner'),[])
        self.assertEqual(self.occurrence(plan)['state'],'failed')

    def test_cdr_schedule_freezes_definition_and_dispatches_private_pdf(self):
        self.seed_cdr();original=dict(columns=['direction','billsec'],group_by=['direction'])
        self.worker.authorize_cdr=lambda spec:{'8001':'masked'}
        plan=self.save_cdr(cdr_definition=original);result=self.worker.run_once();self.assertEqual(result['state'],'dispatched',result)
        ident=result['export_job_id'];job=self.jobs.get(ident,'owner')
        self.assertEqual(job['spec']['cdr_definition'],original);self.assertEqual(job['spec']['cdr_filters']['direction'],'outbound')
        self.assertEqual(job['spec']['consistency'],'worker_start_snapshot')
        self.save_cdr(ident=plan['id'],cdr_definition=dict(columns=['src'],group_by=[]))
        worker=ExportWorker(self.jobs,self.archive,authorize=lambda spec:True,limits=Limits(min_free_bytes=0,max_load_per_cpu=0),disabled_file=self.disabled)
        result=worker.run_once();self.assertEqual(result['state'],'completed',result);self.assertEqual(result['rows'],1)
        fd,_=self.jobs.open_output(ident,'owner')
        with os.fdopen(fd,'rb') as stream:self.assertTrue(stream.read().startswith(b'%PDF-'))
        self.assertEqual(self.jobs.get(ident,'owner')['spec']['cdr_definition'],original)

    def test_cdr_schedule_global_permission_rechecked_and_filtered_number_requires_full_grant(self):
        self.seed_cdr();root=self.root;accounts=root/'accounts.json';policies=root/'policies.json'
        accounts.write_text(json.dumps({'owner':dict(role='admin',phone='PJSIP/100',menus=['reports','users'],password_hash='pbkdf2:sha256:test')}),encoding='utf8')
        policies.write_text(json.dumps(dict(version=1,queues={'8001':{}},supervisors={})),encoding='utf8')
        plan=self.save_cdr();spec={**plan,'owner':'owner'}
        self.assertEqual(current_cdr_modes(spec,self.archive,accounts,policies),{'8001':'full'})
        with self.archive.writer() as db:
            db.execute('INSERT INTO report_visits VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                ('primary','b'*64,'q2','8002',self.stamp,self.stamp+1,self.stamp+4,'09123456789','100','answered',1,3,'caller','observed'))
        self.assertIsNone(current_cdr_modes(spec,self.archive,accounts,policies))
        with self.archive.writer() as db:db.execute("DELETE FROM report_visits WHERE queue='8002'")
        accounts.write_text(json.dumps({'owner':dict(role='admin',phone='PJSIP/100',menus=['reports'],password_hash='pbkdf2:sha256:test')}),encoding='utf8')
        self.assertIsNone(current_cdr_modes(spec,self.archive,accounts,policies))


class CDRPlanAPITests(unittest.TestCase):
    def setUp(self):
        self.case=CDRAPITests();self.case.setUp();self.addCleanup(self.case.case.doCleanups);self.c=self.case.case
        with self.c.archive.writer() as db:db.execute("DELETE FROM report_visits WHERE queue='8002'")
        JobStore(self.c.root/'export-jobs.sqlite3',self.c.root/'private-exports').initialize()
        self.client=self.c.client(role='admin',menus=('reports','users'),details=False)
        with self.client.session_transaction() as state:state['csrf_token']='token'
        self.headers={'X-CSRF-Token':'token'};self.query='?from=2026-10-24&to=2026-10-25'
        self.body=dict(name='CDR schedule',queues=['8001'],format='xlsx',language='en',period='yesterday',enabled=False,
            cdr_definition=dict(columns=['direction'],group_by=['direction']),cdr_filters={'direction':'outbound'})

    def test_cdr_plan_can_run_and_preserves_definition_on_schedule_edit(self):
        response=self.client.post('/api/history/plans'+self.query,json=self.body,headers=self.headers)
        self.assertEqual(response.status_code,201,response.json);plan=response.json['plan'];self.assertEqual(plan['cdr_filters']['direction'],'outbound')
        job=self.client.post('/api/history/plans/'+plan['id']+'/run'+self.query,json={'request_key':'first'},headers=self.headers)
        self.assertEqual(job.status_code,202,job.json);self.assertEqual(job.json['job']['dataset'],'cdr_segments')
        edited={**self.body,'id':plan['id'],'name':'updated'};edited.pop('cdr_definition');edited.pop('cdr_filters')
        result=self.client.post('/api/history/plans'+self.query,json=edited,headers=self.headers)
        self.assertEqual(result.status_code,201,result.json);self.assertEqual(result.json['plan']['cdr_definition'],self.body['cdr_definition'])

    def test_cdr_plan_denies_supervisor_number_filter_without_permission_and_partial_scope(self):
        self.assertEqual(self.client.post('/api/history/plans'+self.query,json={**self.body,'cdr_filters':{'src':'100'}},headers=self.headers).status_code,403)
        self.assertEqual(self.client.post('/api/history/plans'+self.query,json={**self.body,'queues':['8002']},headers=self.headers).status_code,403)
        supervisor=self.c.client(role='supervisor',menus=('reports','users'),details=True)
        with supervisor.session_transaction() as state:state['csrf_token']='token'
        self.assertEqual(supervisor.post('/api/history/plans'+self.query,json=self.body,headers=self.headers).status_code,403)

    def test_old_sensitive_occurrence_hidden_after_number_permission_revoked(self):
        denied=[]
        client=self.c.client(role='admin',menus=('reports','users'),details=True,denied=denied)
        with client.session_transaction() as state:state['csrf_token']='token'
        body={**self.body,'enabled':True,'at':'00:00','cdr_filters':{'src':'100'}}
        response=client.post('/api/history/plans'+self.query,json=body,headers=self.headers)
        self.assertEqual(response.status_code,201,response.json)
        ident=response.json['plan']['id']
        store=SavedReports(self.c.root/'report-plans.sqlite3')
        occurrence=store.reserve_due('test')
        self.assertIsNotNone(occurrence)
        self.assertEqual(occurrence['spec']['cdr_filters']['src'],'100')
        edited={**body,'id':ident,'cdr_filters':{'direction':'outbound'}}
        response=client.post('/api/history/plans'+self.query,json=edited,headers=self.headers)
        self.assertEqual(response.status_code,201,response.json)
        denied.append('caller_details')
        response=client.get('/api/history/plans/'+ident+'/runs'+self.query)
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json['runs'],[])


if __name__=='__main__':unittest.main()
