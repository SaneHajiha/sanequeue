import unittest
from unittest.mock import patch
from io import BytesIO
from zipfile import ZipFile
from sanequeue.reporting.facts import project_batch
from sanequeue.reporting.store import Event
from tests import test_reporting_queries as fixtures


class UnitAPITests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.ReportTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.case.seed()
        with self.case.archive.writer() as db:db.execute("DELETE FROM report_visits WHERE queue='8002'")
        self.case.archive.append([Event('cdr','unit-row',self.case.stamp+1,'CDR',dict(
            src='09123456789',dst='100',channel='PJSIP/provider-000000aa',
            dstchannel='PJSIP/100-000000bb',duration=10,billsec=5,disposition='ANSWERED'))])
        while project_batch(self.case.archive,inventory=dict(observed_at=self.case.stamp,endpoints=[
            dict(technology='PJSIP',endpoint='100',category='extension'),
            dict(technology='PJSIP',endpoint='provider',category='trunk')]))['processed']:pass
        self.admin=self.case.client(role='admin',menus=('reports','users'),details=True)
        with self.admin.session_transaction() as state:state['csrf_token']='token'
        self.header={'X-CSRF-Token':'token'}

    def post(self,**body):
        result=self.admin.post('/api/organization/access',json=body,headers=self.header)
        self.assertEqual(result.status_code,201,result.get_data(as_text=True));return result.json['id']

    def test_management_is_restricted_and_scope_used_for_summary(self):
        url='/api/organization/access'
        self.assertEqual(self.case.client().get(url).status_code,403)
        self.assertEqual(self.case.client(role='admin',menus=('reports','users')).get(url).status_code,403)
        self.assertEqual(self.admin.post(url,json={'operation':'create','name':'X','kind':'organization'}).status_code,403)
        org=self.post(operation='create',kind='organization',name='Org')
        dept=self.post(operation='create',kind='department',name='Dept',parent=org)
        unit=self.post(operation='create',kind='unit',name='Site',parent=dept)
        unknown=self.admin.post(url,json={'operation':'grant','unit_id':unit,'username':'missing',
            'capability':'summary'},headers=self.header)
        self.assertEqual(unknown.status_code,400)
        self.post(operation='assign',unit_id=unit,endpoint='PJSIP/100',start=self.case.stamp-10)
        self.post(operation='grant',unit_id=unit,username='test',capability='summary')
        report='/api/organization/reports/cdr/summary?from=2026-10-24&to=2026-10-25'
        result=self.case.client().get(report)
        self.assertEqual(result.status_code,200,result.get_data(as_text=True))
        self.assertEqual(result.json['totals']['segments_started'],1)
        self.assertNotIn('09123456789',result.get_data(as_text=True))
        self.assertEqual(self.case.client(menus=('users',)).get(report).status_code,403)
        self.assertEqual(self.case.client().get(report+'&src=09123456789').status_code,403)

    def test_identifier_filters_require_number_permission_for_entire_scope(self):
        org=self.post(operation='create',kind='organization',name='Org')
        dept=self.post(operation='create',kind='department',name='Dept',parent=org)
        first=self.post(operation='create',kind='unit',name='Site',parent=dept)
        other=self.post(operation='create',kind='unit',name='Other',parent=dept)
        self.post(operation='assign',unit_id=first,endpoint='PJSIP/100',start=self.case.stamp-10)
        for unit in (first,other):
            for capability in ('summary','call_details'):
                self.post(operation='grant',unit_id=unit,username='test',capability=capability)
        self.post(operation='grant',unit_id=first,username='test',capability='full_numbers')
        base='/api/organization/reports/cdr?from=2026-10-24&to=2026-10-25'
        self.assertEqual(self.admin.get(base+'&endpoint=PJSIP%2F100').status_code,403)
        number_grant=self.post(operation='grant',unit_id=other,username='test',capability='full_numbers')
        self.assertEqual(self.admin.get(base+'&endpoint=PJSIP%2F100').status_code,200)
        self.assertEqual(self.case.client(role='viewer').get(base+'&endpoint=PJSIP%2F100').status_code,403)
        summary='/api/organization/reports/cdr/summary?from=2026-10-24&to=2026-10-25'
        self.assertEqual(self.admin.get(summary+'&party=09123456789').json['totals']['segments_started'],1)
        self.assertEqual(self.admin.get(summary+'&party=09121111111').json['totals']['segments_started'],0)
        from sanequeue.reporting.cdr_queries import summary as calculate
        def revoke_during_search(*args,**kwargs):
            result=calculate(*args,**kwargs);self.post(operation='revoke',id=number_grant);return result
        with patch('sanequeue.reporting.unit_cdr.cdr_queries.summary',side_effect=revoke_during_search):
            denied=self.admin.get(summary+'&party=09123456789')
        self.assertNotEqual(denied.status_code,200)
        self.assertNotIn('totals',denied.json)

    def test_queue_summary_respects_historical_unit_and_excludes_handover_visit(self):
        org=self.post(operation='create',kind='organization',name='Org')
        dept=self.post(operation='create',kind='department',name='Dept',parent=org)
        first=self.post(operation='create',kind='unit',name='Site',parent=dept)
        second=self.post(operation='create',kind='unit',name='Other',parent=dept)
        self.post(operation='assign_queue',unit_id=first,queue='8001',start=self.case.stamp-10,end=self.case.stamp+50)
        self.post(operation='assign_queue',unit_id=second,queue='8001',start=self.case.stamp+50)
        self.post(operation='grant',unit_id=first,username='test',capability='summary')
        c=self.case
        c.archive.append([c.event('cross','8001','ENTERQUEUE',45,['','09']),c.event('cross','8001','ABANDON',55,['1','1','10']),
                          c.event('later','8001','ENTERQUEUE',60,['','09']),c.event('later','8001','ABANDON',70,['1','1','10'])])
        while project_batch(c.archive)['processed']:pass
        url='/api/organization/reports/queues?from=2026-10-24&to=2026-10-25'
        response=self.admin.get(url);self.assertEqual(response.status_code,200,response.get_data(as_text=True))
        self.assertEqual(response.json['queues'][0]['visits'],1)
        self.assertEqual(response.json['eligibility'],'closed_visits_contained_in_assignment')
        self.assertNotIn('09123456789',response.get_data(as_text=True))
        from sanequeue.security.unit_scope import UnitScopeStore
        from sanequeue.reporting.unit_queue import summary as queue_summary
        store=UnitScopeStore(self.case.archive.path.parent/'unit-scope.sqlite3')
        store.grant('other-manager',second,'summary')
        other_report=queue_summary(c.archive,store,'other-manager',self.case.stamp-10,self.case.stamp+100)
        self.assertEqual(other_report['queues'][0]['visits'],1)
        self.assertEqual(self.case.client(menus=('users',)).get(url).status_code,403)
        overlap=self.admin.post('/api/organization/access',json={'operation':'assign_queue','unit_id':first,'queue':'8001','start':self.case.stamp},headers=self.header)
        self.assertEqual(overlap.status_code,409)
        with patch('sanequeue.security.unit_scope.UnitScopeStore.still_current',return_value=False):
            self.assertEqual(self.admin.get(url).status_code,409)

    def test_access_changes_are_audited_atomically_and_hidden_from_other_roles(self):
        org=self.post(operation='create',kind='organization',name='Private')
        url='/api/organization/access/changes'
        self.assertEqual(self.case.client().get(url).status_code,403)
        rows=self.admin.get(url).json['rows']
        self.assertEqual([(row['operation'],row['target']) for row in rows],[('create',org)])
        self.assertEqual(rows[0]['unit_name'],'Private')
        from sanequeue.security.unit_scope import UnitScopeStore
        store=UnitScopeStore(self.case.archive.path.parent/'unit-scope.sqlite3')
        with store._db(write=True) as db:
            db.execute("CREATE TRIGGER fail_unit_audit BEFORE INSERT ON unit_change_audit BEGIN SELECT RAISE(ABORT,'test'); END")
        result=self.admin.post('/api/organization/access',json={'operation':'create','kind':'department','name':'Fail','parent':org},headers=self.header)
        self.assertNotEqual(result.status_code,201)
        self.assertEqual(len(store.inventory()['units']),1)
        self.assertEqual(len(store.list_change_audit()),1)

    def test_ai_requires_both_permissions_and_rechecks_revocation(self):
        org=self.post(operation='create',kind='organization',name='Org')
        dept=self.post(operation='create',kind='department',name='Dept',parent=org)
        unit=self.post(operation='create',kind='unit',name='Site',parent=dept)
        self.post(operation='assign',unit_id=unit,endpoint='PJSIP/100',start=self.case.stamp-10)
        self.post(operation='grant',unit_id=unit,username='test',capability='summary')
        url='/api/organization/reports/ai?from=2026-10-24&to=2026-10-25'
        data={'question':'تعداد تماس‌ها چقدر است؟'}
        with patch('sanequeue.api.reports.ai_report.parse',return_value={'metric':'count','direction':'all'}) as parser:
            self.assertEqual(self.admin.post(url,json=data,headers=self.header).status_code,403)
            parser.assert_not_called()
            grant=self.post(operation='grant',unit_id=unit,username='test',capability='ai_report')
            response=self.admin.post(url,json=data,headers=self.header)
            self.assertEqual(response.status_code,200,response.get_data(as_text=True))
            self.assertEqual(response.json['value'],1)
            def revoke(_):
                self.post(operation='revoke',id=grant)
                return {'metric':'count','direction':'all'}
            parser.side_effect=revoke
            self.assertEqual(self.admin.post(url,json=data,headers=self.header).status_code,403)

    def test_scoped_details_mask_numbers_and_invalidate_cursor(self):
        org=self.post(operation='create',kind='organization',name='Org')
        dept=self.post(operation='create',kind='department',name='Dept',parent=org)
        unit=self.post(operation='create',kind='unit',name='Site',parent=dept)
        self.post(operation='assign',unit_id=unit,endpoint='PJSIP/100',start=self.case.stamp-10)
        self.post(operation='grant',unit_id=unit,username='test',capability='call_details')
        self.case.archive.append([Event('cdr','unit-row2',self.case.stamp+2,'CDR',dict(
            src='09121111111',dst='100',channel='PJSIP/provider-000000aa',
            dstchannel='PJSIP/100-000000bb',duration=10,billsec=5,disposition='ANSWERED'))])
        while project_batch(self.case.archive,inventory=dict(observed_at=self.case.stamp,endpoints=[
            dict(technology='PJSIP',endpoint='100',category='extension'),
            dict(technology='PJSIP',endpoint='provider',category='trunk')]))['processed']:pass
        url='/api/organization/reports/cdr?from=2026-10-24&to=2026-10-25&limit=1'
        client=self.case.client()
        first=client.get(url);self.assertEqual(first.status_code,200,first.get_data(as_text=True))
        self.assertNotIn('09121111111',first.get_data(as_text=True))
        self.assertNotIn('unit-row',first.get_data(as_text=True))
        token=first.json['next'];self.assertIsNotNone(token)
        second=client.get(url+'&cursor='+token)
        self.assertEqual(second.status_code,200,second.get_data(as_text=True))
        self.assertNotEqual(first.json['rows'][0]['ts'],second.json['rows'][0]['ts'])
        self.assertEqual(client.get(url+'&direction=inbound&cursor='+token).status_code,409)
        self.post(operation='grant',unit_id=unit,username='test',capability='full_numbers')
        self.assertEqual(client.get(url+'&cursor='+token).status_code,409)
        full=client.get(url);self.assertIn('09121111111',full.get_data(as_text=True))
        viewer=self.case.client(role='viewer').get(url)
        self.assertEqual(viewer.status_code,200)
        self.assertNotIn('09121111111',viewer.get_data(as_text=True))
        self.assertFalse(full.json['audio_available'])

    def test_direct_recording_separates_permissions_and_rejects_transfer(self):
        org=self.post(operation='create',kind='organization',name='Org')
        dept=self.post(operation='create',kind='department',name='Dept',parent=org)
        unit=self.post(operation='create',kind='unit',name='Site',parent=dept)
        self.post(operation='assign',unit_id=unit,endpoint='PJSIP/100',start=self.case.stamp-10)
        self.post(operation='grant',unit_id=unit,username='test',capability='call_details')
        play_grant=self.post(operation='grant',unit_id=unit,username='test',capability='recording_play')
        self.case.archive.append([Event('cdr','unit-audio',self.case.stamp+20,'CDR',dict(
            uniqueid='unit-audio-id',linkedid='unit-audio-id',src='09123456789',dst='100',channel='PJSIP/provider-000000aa',
            dstchannel='PJSIP/100-000000bb',duration=10,billsec=5,disposition='ANSWERED',recordingfile='test.wav'))])
        while project_batch(self.case.archive,inventory=dict(observed_at=self.case.stamp,endpoints=[
            dict(technology='PJSIP',endpoint='100',category='extension'),dict(technology='PJSIP',endpoint='provider',category='trunk')]))['processed']:pass
        audio=self.case.root/'audio';audio.mkdir();(audio/'test.wav').write_bytes(b'RIFF'+b'0'*150000)
        url='/api/organization/reports/cdr?from=2026-10-24&to=2026-10-25'
        result=self.admin.get(url);recording=next(row['recording'] for row in result.json['rows'] if row.get('recording'))
        self.assertTrue(recording['play']);self.assertFalse(recording['download'])
        path='/api/organization/reports/recording/'+recording['ref']
        self.assertEqual(self.case.client(role='viewer').get(path).status_code,403)
        from sanequeue.security.unit_scope import UnitScopeStore,ScopeConflict
        store=UnitScopeStore(self.case.archive.path.parent/'unit-scope.sqlite3')
        with self.assertRaises(ScopeConflict):store.load_recording_ref('another-user',recording['ref'])
        with patch('sanequeue.api.reports.recording_ownership',return_value=False):
            self.assertEqual(self.admin.get(path).status_code,403)
        with patch('sanequeue.api.reports.recording_ownership',return_value=frozenset({'8001'})):
            self.assertEqual(self.admin.get(path).status_code,403)
        from sanequeue.reporting.recording_scope import ownership
        with patch('sanequeue.api.reports.recording_ownership',wraps=ownership):
            self.assertEqual(self.admin.get(path).status_code,200)
            self.assertEqual(self.admin.get(path+'?download=1').status_code,403)
            self.post(operation='grant',unit_id=unit,username='test',capability='recording_download')
            self.assertNotEqual(self.admin.get(path).status_code,200)
            result=self.admin.get(url);recording=next(row['recording'] for row in result.json['rows'] if row.get('recording'))
            path='/api/organization/reports/recording/'+recording['ref']
            self.assertTrue(recording['download']);self.assertEqual(self.admin.get(path+'?download=1').status_code,200)
            stream=self.admin.get(path,buffered=False);chunks=iter(stream.response)
            self.assertEqual(len(next(chunks)),65536)
            self.post(operation='revoke',id=play_grant)
            self.assertEqual(list(chunks),[]);stream.close()
            self.post(operation='grant',unit_id=unit,username='test',capability='recording_play')
            self.post(operation='grant',unit_id=unit,username='test',capability='api')
            issued=self.admin.post('/api/organization/tokens',base_url='https://localhost',json={'days':30},headers=self.header)
            bearer=issued.json['token'];auth={'Authorization':'Bearer '+bearer};anonymous=self.admin.application.test_client()
            api_cdr='/api/organization/integration/cdr?from=2026-10-24&to=2026-10-25'
            api_rows=anonymous.get(api_cdr,headers=auth,base_url='https://localhost').json['rows']
            api_ref=next(row['recording']['ref'] for row in api_rows if row.get('recording'))
            api_audio='/api/organization/integration/recording/'+api_ref
            self.assertEqual(anonymous.get(api_audio,headers=auth).status_code,403)
            self.assertEqual(anonymous.get(api_audio,base_url='https://localhost').status_code,401)
            from sanequeue.security.unit_scope import ScopeUnavailable
            with patch('sanequeue.security.unit_scope.UnitScopeStore.audit_api',side_effect=ScopeUnavailable('storage')):
                blocked=anonymous.get(api_audio,headers=auth,base_url='https://localhost')
            self.assertEqual(blocked.status_code,503);self.assertNotIn(b'RIFF',blocked.data)
            streamed=anonymous.get(api_audio,headers=auth,base_url='https://localhost',buffered=False)
            self.assertEqual(streamed.status_code,200);iterator=iter(streamed.response)
            self.assertEqual(len(next(iterator)),65536)
            audit=self.admin.get('/api/organization/access/audit').json['rows']
            self.assertEqual(audit[0]['dataset'],'recording_play');self.assertNotIn(bearer,str(audit))
            self.admin.post('/api/organization/tokens/revoke',base_url='https://localhost',json={'id':issued.json['id']},headers=self.header)
            self.assertEqual(list(iterator),[]);streamed.close()
            self.assertEqual(anonymous.get(api_audio,headers=auth,base_url='https://localhost').status_code,401)
            result=self.admin.get(url);recording=next(row['recording'] for row in result.json['rows'] if row.get('recording'))
            path='/api/organization/reports/recording/'+recording['ref']
            with self.case.archive.writer() as db:
                db.execute('INSERT INTO report_cel_transfers VALUES(?,?,?,?,?,?,?)',(self.case.archive.pbx,'transfer','unit-audio-id','unit-audio-id','',self.case.stamp+21,'BLINDTRANSFER'))
            self.assertEqual(self.admin.get(path).status_code,403)

    def test_date_inputs_and_ai_budget_fail_closed(self):
        from sanequeue.security.unit_scope import UnitScopeStore, ScopeConflict
        org=self.post(operation='create',kind='organization',name='Org')
        dept=self.post(operation='create',kind='department',name='Dept',parent=org)
        unit=self.post(operation='create',kind='unit',name='Site',parent=dept)
        ident=self.post(operation='assign',unit_id=unit,endpoint='PJSIP/100',start_date='2026-10-24',end_date=None)
        self.post(operation='close',id=ident,end_date='2026-10-25',membership=False)
        result=self.admin.post('/api/organization/access',json={'operation':'member','unit_id':unit,
            'username':'test','end_date':'2026-10-25'},headers=self.header)
        self.assertEqual(result.status_code,400)
        self.post(operation='grant',unit_id=unit,username='test',capability='ai_report')
        store=UnitScopeStore(self.case.archive.path.parent/'unit-scope.sqlite3')
        scope=store.resolve('test','ai_report',self.case.stamp,self.case.stamp+86400)
        for _ in range(20):store.consume_ai_budget('test',scope)
        with self.assertRaises(ScopeConflict):store.consume_ai_budget('test',scope)

    def test_unit_export_requires_independent_grant_and_masks_numbers(self):
        org=self.post(operation='create',kind='organization',name='Org')
        dept=self.post(operation='create',kind='department',name='Dept',parent=org)
        unit=self.post(operation='create',kind='unit',name='Site',parent=dept)
        self.post(operation='assign',unit_id=unit,endpoint='PJSIP/100',start=self.case.stamp-10)
        self.post(operation='grant',unit_id=unit,username='test',capability='call_details')
        url='/api/organization/reports/cdr/export.csv?from=2026-10-24&to=2026-10-25'
        self.assertEqual(self.admin.post(url,headers=self.header).status_code,403)
        grant=self.post(operation='grant',unit_id=unit,username='test',capability='export')
        self.assertEqual(self.admin.post(url).status_code,403)
        result=self.admin.post(url,headers=self.header)
        self.assertEqual(result.status_code,200,result.get_data(as_text=True))
        self.assertIn('timestamp',result.get_data(as_text=True))
        self.assertNotIn('09123456789',result.get_data(as_text=True))
        excel=self.admin.post(url.replace('export.csv','export.xlsx'),headers=self.header)
        self.assertEqual(excel.status_code,200,excel.data[:200])
        with ZipFile(BytesIO(excel.data)) as workbook:
            self.assertNotIn(b'09123456789',workbook.read('xl/worksheets/sheet1.xml'))
        pdf=self.admin.post(url.replace('export.csv','export.pdf'),headers=self.header)
        self.assertEqual(pdf.status_code,200,pdf.data[:200]);self.assertTrue(pdf.data.startswith(b'%PDF-'))
        self.post(operation='grant',unit_id=unit,username='test',capability='full_numbers')
        self.assertIn('09123456789',self.admin.post(url,headers=self.header).get_data(as_text=True))
        excel=self.admin.post(url.replace('export.csv','export.xlsx'),headers=self.header)
        with ZipFile(BytesIO(excel.data)) as workbook:
            self.assertIn(b'09123456789',workbook.read('xl/worksheets/sheet1.xml'))
        from sanequeue.reporting.unit_cdr import export_csv
        def revoked(*args,**kwargs):
            value=export_csv(*args,**kwargs)
            self.post(operation='revoke',id=grant)
            return value
        with patch('sanequeue.api.reports.unit_cdr.export_csv',side_effect=revoked):
            denied=self.admin.post(url,headers=self.header)
        self.assertEqual(denied.status_code,403)
        self.assertNotIn('09123456789',denied.get_data(as_text=True))
        grant=self.post(operation='grant',unit_id=unit,username='test',capability='export')
        with patch('sanequeue.api.reports.unit_cdr.export_csv',side_effect=revoked):
            denied=self.admin.post(url.replace('export.csv','export.xlsx'),headers=self.header)
        self.assertIn(denied.status_code,(403,409))
        self.assertFalse(denied.data.startswith(b'PK'))
        grant=self.post(operation='grant',unit_id=unit,username='test',capability='export')
        with patch('sanequeue.api.reports.unit_cdr.export_csv',side_effect=revoked):
            denied=self.admin.post(url.replace('export.csv','export.pdf'),headers=self.header)
        self.assertIn(denied.status_code,(403,409))
        self.assertFalse(denied.data.startswith(b'%PDF'))

    def test_ai_rate_excludes_unknown_outcomes_and_talk_reports_sample_count(self):
        org=self.post(operation='create',kind='organization',name='Org')
        dept=self.post(operation='create',kind='department',name='Dept',parent=org)
        unit=self.post(operation='create',kind='unit',name='Site',parent=dept)
        self.post(operation='assign',unit_id=unit,endpoint='PJSIP/100',start=self.case.stamp-10)
        self.post(operation='grant',unit_id=unit,username='test',capability='summary')
        self.post(operation='grant',unit_id=unit,username='test',capability='ai_report')
        self.case.archive.append([Event('cdr','unknown-status',self.case.stamp+4,'CDR',dict(
            src='09000000000',dst='100',channel='PJSIP/provider-000000aa',dstchannel='PJSIP/100-000000bb',
            duration=10,billsec=None,disposition='UNKNOWN'))])
        while project_batch(self.case.archive,inventory=dict(observed_at=self.case.stamp,endpoints=[
            dict(technology='PJSIP',endpoint='100',category='extension'),
            dict(technology='PJSIP',endpoint='provider',category='trunk')]))['processed']:pass
        url='/api/organization/reports/ai?from=2026-10-24&to=2026-10-25'
        with patch('sanequeue.api.reports.ai_report.parse',return_value={'metric':'answer_rate','direction':'all'}):
            result=self.admin.post(url,json={'question':'rate'},headers=self.header)
        self.assertEqual(result.status_code,200,result.get_data(as_text=True))
        self.assertEqual((result.json['value'],result.json['denominator'],result.json['unit']),(100,1,'percent'))
        with patch('sanequeue.api.reports.ai_report.parse',return_value={'metric':'average_talk','direction':'all'}):
            result=self.admin.post(url,json={'question':'talk'},headers=self.header)
        self.assertEqual((result.json['value'],result.json['known_samples']),(5,1))
        with patch('sanequeue.api.reports.ai_report.parse',return_value={'metric':'answer_rate','direction':'outbound'}):
            empty=self.admin.post(url,json={'question':'rate'},headers=self.header)
        self.assertEqual(empty.json['denominator'],0)
        self.assertIsNone(empty.json['value'])

    def test_unit_trend_is_scoped_and_checks_revocation(self):
        org=self.post(operation='create',kind='organization',name='Org')
        dept=self.post(operation='create',kind='department',name='Dept',parent=org)
        site=self.post(operation='create',kind='unit',name='Site',parent=dept)
        other=self.post(operation='create',kind='unit',name='Other',parent=dept)
        self.post(operation='assign',unit_id=site,endpoint='PJSIP/100',start=self.case.stamp-10)
        self.post(operation='assign',unit_id=other,endpoint='PJSIP/200',start=self.case.stamp-10)
        url='/api/organization/reports/cdr/trend?from=2026-10-24&to=2026-10-25&bucket=day'
        self.assertEqual(self.case.client().get(url).status_code,403)
        grant=self.post(operation='grant',unit_id=site,username='test',capability='summary')
        self.case.archive.append([Event('cdr','other-unit',self.case.stamp+2,'CDR',dict(
            src='09000000000',dst='200',channel='PJSIP/provider-000000aa',
            dstchannel='PJSIP/200-000000bb',duration=10,billsec=5,disposition='ANSWERED'))])
        while project_batch(self.case.archive,inventory=dict(observed_at=self.case.stamp,endpoints=[
            dict(technology='PJSIP',endpoint='100',category='extension'),
            dict(technology='PJSIP',endpoint='200',category='extension'),
            dict(technology='PJSIP',endpoint='provider',category='trunk')]))['processed']:pass
        result=self.case.client().get(url)
        self.assertEqual(result.status_code,200,result.get_data(as_text=True))
        self.assertEqual(sum(row['inbound'] for row in result.json['rows']),1)
        self.assertEqual(result.json['scope'],'organization_unit')
        self.assertNotIn('09000000000',result.get_data(as_text=True))
        self.assertEqual(self.case.client().get(url+'&src=09000000000').status_code,403)
        from sanequeue.reporting.cdr_trend import report
        def revoke(*args,**kwargs):
            result=report(*args,**kwargs);self.post(operation='revoke',id=grant);return result
        with patch('sanequeue.reporting.unit_cdr.cdr_trend.report',side_effect=revoke):
            denied=self.case.client().get(url)
        self.assertEqual(denied.status_code,409)
        self.assertNotIn('rows',denied.json)

    def test_ai_comparison_uses_historical_scope_for_both_periods(self):
        org=self.post(operation='create',kind='organization',name='Org')
        dept=self.post(operation='create',kind='department',name='Dept',parent=org)
        site=self.post(operation='create',kind='unit',name='Site',parent=dept)
        other=self.post(operation='create',kind='unit',name='Other',parent=dept)
        self.post(operation='assign',unit_id=site,endpoint='PJSIP/100',start=self.case.stamp-300000,end=self.case.stamp-86400)
        self.post(operation='assign',unit_id=other,endpoint='PJSIP/100',start=self.case.stamp-86400)
        self.post(operation='grant',unit_id=site,username='test',capability='summary')
        self.post(operation='grant',unit_id=site,username='test',capability='ai_report')
        self.case.archive.append([Event('cdr','previous-unit',self.case.stamp-172800,'CDR',dict(
            src='09000000000',dst='100',channel='PJSIP/provider-000000aa',
            dstchannel='PJSIP/100-000000bb',duration=10,billsec=5,disposition='ANSWERED'))])
        while project_batch(self.case.archive,inventory=dict(observed_at=self.case.stamp,endpoints=[
            dict(technology='PJSIP',endpoint='100',category='extension'),
            dict(technology='PJSIP',endpoint='provider',category='trunk')]))['processed']:pass
        url='/api/organization/reports/ai?from=2026-10-24&to=2026-10-25'
        with patch('sanequeue.api.reports.ai_report.parse',return_value={'metric':'compare_count','direction':'all'}):
            result=self.admin.post(url,json={'question':'compare'},headers=self.header)
        self.assertEqual(result.status_code,200,result.get_data(as_text=True))
        self.assertEqual(result.json['value'],0)
        self.assertEqual(result.json['comparison']['value'],1)
        self.assertEqual(result.json['comparison']['difference'],-1)
        self.assertNotIn('09000000000',result.get_data(as_text=True))

    def test_bearer_api_is_tls_scoped_masked_and_revocable(self):
        org=self.post(operation='create',kind='organization',name='Org')
        dept=self.post(operation='create',kind='department',name='Dept',parent=org)
        unit=self.post(operation='create',kind='unit',name='Site',parent=dept)
        self.post(operation='assign_queue',unit_id=unit,queue='8001',start=self.case.stamp-10)
        self.post(operation='assign',unit_id=unit,endpoint='PJSIP/100',start=self.case.stamp-10)
        self.post(operation='grant',unit_id=unit,username='test',capability='summary')
        self.post(operation='grant',unit_id=unit,username='test',capability='call_details')
        self.assertEqual(self.admin.post('/api/organization/tokens',json={'days':30},headers=self.header).status_code,403)
        self.assertEqual(self.admin.post('/api/organization/tokens',base_url='https://localhost',json={'days':30},headers=self.header).status_code,403)
        api_grant=self.post(operation='grant',unit_id=unit,username='test',capability='api')
        issued=self.admin.post('/api/organization/tokens',base_url='https://localhost',json={'days':30},headers=self.header)
        self.assertEqual(issued.status_code,201,issued.get_data(as_text=True))
        token=issued.json['token'];ident=issued.json['id']
        listed=self.admin.get('/api/organization/tokens',base_url='https://localhost')
        self.assertNotIn(token,listed.get_data(as_text=True));self.assertEqual(len(listed.json['tokens']),1)
        anonymous=self.admin.application.test_client()
        url='/api/organization/integration/cdr?from=2026-10-24&to=2026-10-25'
        authorization={'Authorization':'Bearer '+token}
        self.assertEqual(anonymous.get(url,headers=authorization).status_code,403)
        self.assertEqual(anonymous.get(url,base_url='https://localhost').status_code,401)
        result=anonymous.get(url,headers=authorization,base_url='https://localhost')
        self.assertEqual(result.status_code,200,result.get_data(as_text=True))
        self.assertEqual(len(result.json['rows']),1);self.assertNotIn('09123456789',result.get_data(as_text=True))
        audit=self.admin.get('/api/organization/access/audit')
        self.assertEqual(audit.status_code,200);self.assertEqual(audit.json['rows'][0]['dataset'],'cdr')
        self.assertNotIn(token,audit.get_data(as_text=True));self.assertNotIn('09123456789',audit.get_data(as_text=True))
        from sanequeue.security.unit_scope import ScopeUnavailable
        with patch('sanequeue.security.unit_scope.UnitScopeStore.audit_api',side_effect=ScopeUnavailable('storage')):
            unavailable=anonymous.get(url,headers=authorization,base_url='https://localhost')
        self.assertEqual(unavailable.status_code,503)
        self.assertNotIn('rows',unavailable.json)
        self.assertEqual(self.case.client().get('/api/organization/access/audit').status_code,403)
        full_grant=self.post(operation='grant',unit_id=unit,username='test',capability='full_numbers')
        viewer=self.case.client(role='viewer').application.test_client()
        visible=viewer.get(url,headers=authorization,base_url='https://localhost')
        self.assertEqual(visible.status_code,200);self.assertNotIn('09123456789',visible.get_data(as_text=True))
        result=anonymous.get(url.replace('/cdr?','/summary?'),headers=authorization,base_url='https://localhost')
        self.assertEqual(result.status_code,200);self.assertEqual(result.json['totals']['segments_started'],1)
        queue_result=anonymous.get(url.replace('/cdr?','/queues?'),headers=authorization,base_url='https://localhost')
        self.assertEqual(queue_result.status_code,200);self.assertEqual(queue_result.json['queues'][0]['visits'],1)
        self.assertNotIn('09123456789',queue_result.get_data(as_text=True))
        trend=anonymous.get(url.replace('/cdr?','/trend?')+'&bucket=day',headers=authorization,base_url='https://localhost')
        self.assertEqual(trend.status_code,200);self.assertEqual(sum(r['inbound'] for r in trend.json['rows']),1)
        export_url=url.replace('/cdr?','/export.csv?')
        self.assertEqual(anonymous.get(export_url,headers=authorization,base_url='https://localhost').status_code,403)
        self.post(operation='grant',unit_id=unit,username='test',capability='export')
        self.assertEqual(viewer.get(export_url,headers=authorization,base_url='https://localhost').status_code,403)
        self.post(operation='revoke',id=full_grant)
        masked=anonymous.get(export_url,headers=authorization,base_url='https://localhost')
        self.assertEqual(masked.status_code,200);self.assertNotIn('09123456789',masked.get_data(as_text=True))
        self.post(operation='grant',unit_id=unit,username='test',capability='full_numbers')
        exported=anonymous.get(export_url,headers=authorization,base_url='https://localhost')
        self.assertEqual(exported.status_code,200,exported.get_data(as_text=True))
        self.assertIn('09123456789',exported.get_data(as_text=True))
        for fmt,prefix in [('xlsx',b'PK'),('pdf',b'%PDF')]:
            output=anonymous.get(export_url.replace('export.csv','export.'+fmt),headers=authorization,base_url='https://localhost')
            self.assertEqual(output.status_code,200,output.data[:160]);self.assertTrue(output.data.startswith(prefix))
        other=self.post(operation='create',kind='unit',name='Other',parent=dept)
        extra=self.post(operation='grant',unit_id=other,username='test',capability='summary')
        self.assertEqual(anonymous.get(url.replace('/cdr?','/summary?'),headers=authorization,base_url='https://localhost').status_code,403)
        self.post(operation='revoke',id=extra)
        filtered=anonymous.get(url+'&src=09123456789',headers=authorization,base_url='https://localhost')
        self.assertEqual(filtered.status_code,200)
        self.assertEqual(len(filtered.json['rows']),1)
        from sanequeue.reporting.unit_cdr import summary
        def revoke_during_summary(*args,**kwargs):
            data=summary(*args,**kwargs);self.post(operation='revoke',id=api_grant);return data
        with patch('sanequeue.api.reports.unit_cdr.summary',side_effect=revoke_during_summary):
            rejected=anonymous.get(url.replace('/cdr?','/summary?'),headers=authorization,base_url='https://localhost')
        self.assertEqual(rejected.status_code,403)
        self.assertNotIn('totals',rejected.json)
        self.post(operation='grant',unit_id=unit,username='test',capability='api')
        from sanequeue.reporting.unit_cdr import export_csv
        def revoke_during_export(*args,**kwargs):
            data=export_csv(*args,**kwargs)
            revoked=self.admin.post('/api/organization/tokens/revoke',base_url='https://localhost',json={'id':ident},headers=self.header)
            self.assertEqual(revoked.status_code,200)
            return data
        with patch('sanequeue.api.reports.unit_cdr.export_csv',side_effect=revoke_during_export):
            blocked=anonymous.get(export_url,headers=authorization,base_url='https://localhost')
        self.assertEqual(blocked.status_code,403)
        self.assertNotIn('09123456789',blocked.get_data(as_text=True))
        self.assertEqual(anonymous.get(url,headers=authorization,base_url='https://localhost').status_code,401)

