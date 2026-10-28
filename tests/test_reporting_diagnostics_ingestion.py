"""Real importer/projection paths with a deterministic read-only SQL transport."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest

from sanequeue.reporting.correlate import relations
from sanequeue.reporting.facts import project_batch
from sanequeue.reporting.journey import explain
from sanequeue.reporting.queries import Scope, visits
from sanequeue.reporting.sql_source import SQLSource
from sanequeue.reporting.store import Archive, Event


class FixtureCursor:
    """Only source responses are mocked; SQLSource builds/executes its real SQL."""
    def __init__(self, rows, *, userdeftype=True):
        self.rows=rows;self.calls=[];self.sql='';self.args=()
        self.cel_fields={'id','eventtime','eventtype','uniqueid','linkedid','channame','peer',
                         'eventextra','context','appname','appdata'}
        if userdeftype:self.cel_fields.add('userdeftype')

    def __enter__(self):return self
    def __exit__(self,*args):return False
    def execute(self,sql,args=()):self.sql=sql;self.args=args;self.calls.append((sql,args))
    def fetchone(self):
        if self.sql.startswith('SELECT VERSION()'):return {'version':'10.3.39-MariaDB'}
        rows=self.fetchall();return rows[0] if rows else None

    def fetchall(self):
        cel='.`cel`' in self.sql
        if self.sql.startswith('SHOW COLUMNS'):
            fields=self.cel_fields if cel else {'calldate','uniqueid'}
            return [dict(Field=name,Type='int' if name=='id' else 'varchar(255)') for name in fields]
        if self.sql.startswith('SHOW INDEX'):
            return [dict(Column_name=name,Seq_in_index=1) for name in (('id',) if cel else ('calldate','uniqueid'))]
        if not self.sql.startswith('SELECT') or not cel:return []
        rows=[row for row in self.rows if row['id']>self.args[0]] if 'WHERE `id`>%s' in self.sql else [row for row in self.rows if row['id']==self.args[0]]
        select=self.sql.split(' FROM ',1)[0][7:]
        result=[]
        for row in rows:
            projected={}
            for expression in select.split(','):
                name=re.findall(r'`([^`]+)`',expression)[-1]
                projected[name]=None if expression.startswith('NULL AS ') else row.get(name)
            result.append(projected)
        return result


class FixtureConnection:
    def __init__(self,cursor):self.fixture=cursor;self.closed=False
    def cursor(self):return self.fixture
    def close(self):self.closed=True


class DiagnosticsIngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.archive=Archive(Path(self.temp.name)/'archive.db',min_free_bytes=0);self.archive.initialize()
        self.stamp=datetime(2026,10,25,10,tzinfo=timezone.utc)

    def source(self,rows,*,userdeftype=True):
        cursor=FixtureCursor(rows,userdeftype=userdeftype);connection=FixtureConnection(cursor)
        return SQLSource({},connect=lambda:connection),cursor,connection

    def row(self,**changes):
        return dict(id=1,eventtime=self.stamp,eventtype='USER_DEFINED',uniqueid='caller',
                    channame='PJSIP/example-00000001',linkedid='caller',peer='',
                    eventextra='{"digit":"2","ivr_id":"3"}',context='ivr-3',
                    appname='',appdata='',userdeftype='IVRSelection',**changes)

    def test_sql_custom_ivr_type_survives_actual_ingestion_and_semantic_journey(self):
        stamp=self.stamp.timestamp()
        self.archive.append([
            Event('queue_log','enter',stamp-1,'ENTERQUEUE',dict(callid='caller',queue='8001',agent='NONE',values=['','0000000000'])),
            Event('queue_log','answer',stamp+1,'CONNECT',dict(callid='caller',queue='8001',agent='PJSIP/100',values=['2','','0'])),
            Event('queue_log','end',stamp+20,'COMPLETECALLER',dict(callid='caller',queue='8001',agent='PJSIP/100',values=['2','19']))])
        source,cursor,connection=self.source([self.row()])
        result=source.ingest(self.archive,now=stamp+30)
        self.assertEqual(result['cel_rows'],1);self.assertTrue(connection.closed)
        self.assertEqual(self.archive.page(source='cel')[0]['payload']['userdeftype'],'IVRSelection')
        self.assertTrue(any('`appdata`,`userdeftype` FROM' in sql for sql,_ in cursor.calls))
        while project_batch(self.archive)['processed']:pass
        visit=visits(self.archive,Scope(('8001',)),stamp-10,stamp+30)['rows'][0]
        journey=explain(self.archive,Scope(('8001',)),stamp-10,stamp+30,visit['id'])
        self.assertEqual([e['digit'] for e in journey['events'] if e['kind']=='IVR_SELECTION'],['2'])
        self.assertFalse(journey['audio_granted']);self.assertIsNone(journey['final_hangup'])

    def test_missing_optional_userdeftype_column_imports_null_without_required_schema_change(self):
        source,cursor,_=self.source([self.row()],userdeftype=False)
        self.assertEqual(source.ingest(self.archive)['cel_rows'],1)
        self.assertIsNone(self.archive.page(source='cel')[0]['payload']['userdeftype'])
        self.assertTrue(any('NULL AS `userdeftype` FROM' in sql for sql,_ in cursor.calls))
        self.assertFalse(any(re.search(r'\b(?:ALTER|CREATE|UPDATE|DELETE|INSERT)\b',sql,re.I) for sql,_ in cursor.calls))

    def test_old_cursor_anchor_migrates_atomically_with_present_or_absent_optional_column(self):
        for present in (True,False):
            with self.subTest(userdeftype=present):
                source,cursor,_=self.source([self.row()],userdeftype=present)
                old_row={key:value for key,value in self.row().items() if key!='userdeftype'}
                old_event=source._event('cel',old_row)
                old_hash=hashlib.sha256(json.dumps(old_event.payload,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
                self.archive.append([],checkpoint_source='sql:cel:',checkpoint=dict(after_id=1,anchor=old_hash))
                self.assertEqual(source.ingest(self.archive)['cel_rows'],0)
                checkpoint=self.archive.checkpoint('sql:cel:')
                self.assertEqual(checkpoint['after_id'],1);self.assertEqual(checkpoint['anchor_version'],2)
                current=dict(self.row());current['userdeftype']='IVRSelection' if present else None
                self.assertEqual(checkpoint['anchor'],source._anchor(source._event('cel',current)))
                self.assertEqual(self.archive.page(source='cel'),[])

    def test_v2_anchor_still_detects_custom_type_mutation_without_advancing_cursor(self):
        rows=[self.row()];source,_,_=self.source(rows)
        source.ingest(self.archive)
        before=self.archive.checkpoint('sql:cel:')
        rows[0]['userdeftype']='Other'
        with self.assertRaisesRegex(ValueError,'cel_source_reset_requires_new_generation'):source.ingest(self.archive)
        self.assertEqual(self.archive.checkpoint('sql:cel:'),before)

    def test_local_optimize_end_adds_only_explicit_valid_relation_and_is_duplicate_safe(self):
        payload=dict(uniqueid='local-one',channame='Local/100@from-queue-00000001;1',
                     eventextra={'local_two':'Local/100@from-queue-00000001;2'})
        event=Event('cel','end',100,'LOCAL_OPTIMIZE_END',payload)
        self.archive.append([event]);self.archive.append([event])
        rows=relations(self.archive,'local-one')
        self.assertEqual([(row['relation'],row['to_kind'],row['to_id']) for row in rows],
                         [('local_optimize_end','channel','Local/100@from-queue-00000001;2')])
        with self.archive.reader() as db:
            self.assertIsNone(db.execute('SELECT ended FROM legs WHERE uid=?',('local-one',)).fetchone()[0])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM transfers').fetchone()[0],0)

    def test_local_optimize_end_missing_invalid_or_self_target_does_not_infer_relation(self):
        channel='Local/100@from-queue-00000001;1'
        for index,target in enumerate((None,{},[],42,'other-uid','PJSIP/100-00000001',
                                       'Local/100;3','Local/100;2\n',channel,'Local/'+'x'*512+';2')):
            with self.subTest(target=target):
                uid='source-'+str(index)
                self.archive.append([Event('cel',str(index),100,'LOCAL_OPTIMIZE_END',
                    dict(uniqueid=uid,channame=channel,extra={'local_two':target,'hangupsource':channel}))])
                self.assertEqual(relations(self.archive,uid),[])
