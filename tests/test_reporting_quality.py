from pathlib import Path
import math
import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from sanequeue.reporting.quality import QualityStore,QualityConflict,QualityUnavailable
from sanequeue.reporting.store import QueryDeadline


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'quality.db';self.store=QualityStore(self.path);self.store.initialize()
        self.criteria=[dict(id='opening',label='Greeting',max_score=5,weight=25),
                       dict(id='solution',label='Solution',max_score=10,weight=75)]
        self.form=self.store.save_form('Quality',self.criteria,'supervisor')

    def review(self,key='request-1',**changes):
        spec=dict(visit_id='visit-a',queue='8001',reviewer='supervisor',formid=self.form['id'],
                  formversion=1,scores=dict(opening=5,solution=5),comment='Plain text',request_key=key)
        spec.update(changes);return self.store.create_review(**spec)

    def test_weighted_score_and_immutable_form_versions(self):
        row=self.review();self.assertEqual(row['score'],62.5)
        revised=self.store.revise_form(self.form['id'],[dict(id='new',label='New',max_score=100,weight=1)],'other',name='Updated')
        self.assertEqual(revised['version'],2)
        self.assertEqual(self.store.get_form(self.form['id'],1),self.form)
        self.assertEqual(self.store.get_form(self.form['id'])['version'],2)
        self.assertEqual(self.store.get(row['id'],['8001'])['form_snapshot'],self.form)
        self.assertEqual(self.store.get(row['id'],['8001'])['score'],62.5)
        self.assertEqual(len(self.store.forms()),1)
        db=sqlite3.connect(self.path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('UPDATE quality_forms SET name=?',('changed',))
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM quality_reviews')
        finally:db.close()

    def test_idempotency_is_reviewer_scoped_and_conflicts_are_atomic(self):
        first=self.review();self.assertEqual(self.review()['id'],first['id'])
        with self.assertRaises(QualityConflict):self.review(comment='changed')
        other=self.review(reviewer='other');self.assertNotEqual(first['id'],other['id'])
        self.assertEqual(len(self.store.page(['8001'])['rows']),2)

    def test_scope_is_enforced_inside_sql_before_page_limit(self):
        visible=self.review('a')
        for index in range(102):self.review('secret-'+str(index),queue='8002',comment='hidden')
        result=self.store.page(['8001'],'visit-a',limit=100)
        self.assertEqual([r['id'] for r in result['rows']],[visible['id']])
        self.assertIsNone(result['next'])
        self.assertIsNone(self.store.get(visible['id'],['8002']))
        self.assertEqual(self.store.page([])['rows'],[])
        self.assertNotIn('hidden',str(result))

    def test_cursor_is_monotonic_even_when_created_times_are_equal(self):
        with patch('sanequeue.reporting.quality.time.time',return_value=100):
            for index in range(105):self.review(str(index))
        one=self.store.page(['8001'],limit=999);two=self.store.page(['8001'],before=one['next'])
        self.assertEqual((len(one['rows']),len(two['rows'])),(100,5))
        self.assertEqual(len({row['id'] for page in (one,two) for row in page['rows']}),105)
        with self.assertRaises(ValueError):self.store.page(['8001'],before='invalid')

    def test_missing_extra_nonfinite_boolean_and_out_of_range_scores_rejected(self):
        for scores in ({'opening':5},{'opening':5,'solution':5,'extra':1},
                       {'opening':True,'solution':5},{'opening':math.nan,'solution':5},
                       {'opening':5,'solution':math.inf},{'opening':-1,'solution':5},
                       {'opening':6,'solution':5},{'opening':'5','solution':5},
                       {'opening':10**1000,'solution':5}):
            with self.subTest(scores=scores),self.assertRaises(ValueError):self.review(scores=scores)
        self.assertEqual(self.store.page(['8001'])['rows'],[])

    def test_criterion_validation_is_bounded_and_strict(self):
        for values in ([],self.criteria*51,[dict(id='x',label='X',max_score=0,weight=1)],
            [dict(id='x',label='X',max_score=1,weight=0)],[dict(id='x',label='X',max_score=True,weight=1)],
            [dict(id='x',label='X',max_score=1,weight=101)],self.criteria+[self.criteria[0]]):
            with self.subTest(values=values),self.assertRaises(ValueError):self.store.save_form('Bad',values,'owner')

    def test_notes_and_comments_remain_plain_text_without_audio_paths(self):
        notes=[dict(offset_seconds=1.5,text='<script>text only</script>')]
        row=self.review(recording_id='generation:opaque-key',notes=notes,comment='<b>plain</b>')
        self.assertEqual(row['notes'],notes);self.assertEqual(row['comment'],'<b>plain</b>')
        for changes in (dict(notes=[dict(offset_seconds=True,text='x')]),
                        dict(notes=[dict(offset_seconds=14401,text='x')]),
                        dict(notes=[dict(offset_seconds=0,text='x')]*101),
                        dict(recording_id='/private/audio.wav')):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.review('bad',**changes)

    def test_aggregate_is_full_range_scoped_and_contains_no_private_comments(self):
        with patch('sanequeue.reporting.quality.time.time',return_value=100):
            for index in range(105):self.review(str(index))
            self.review('other',queue='8002',comment='private-secret')
        result=self.store.aggregate(['8001'],100,101,reviewers=True)
        self.assertEqual(result['totals']['count'],105)
        self.assertEqual(result['totals']['average_score'],62.5)
        self.assertEqual(result['reviewers'][0]['count'],105)
        self.assertNotIn('private-secret',str(result));self.assertNotIn('comment',str(result))
        empty=self.store.aggregate(['8001'],99,100)
        self.assertEqual(empty['totals']['count'],0);self.assertIsNone(empty['totals']['average_score'])
        with patch('sanequeue.reporting.quality.MAX_GROUPS',1),self.assertRaises(QueryDeadline):
            self.store.aggregate(['8001'],99,101,reviewers=True)
        with patch('sanequeue.reporting.quality.time.monotonic',side_effect=[0,1]),self.assertRaises(QueryDeadline):
            self.store.aggregate(['8001'],99,101)

    def test_storage_startup_and_contention_fail_safely(self):
        missing=QualityStore(Path(self.temp.name)/'missing.db')
        with self.assertRaises(QualityUnavailable):missing.page(['8001'])
        self.assertFalse(missing.path.exists())
        if os.name!='nt':self.assertEqual(self.path.stat().st_mode&0o777,0o600)
        db=sqlite3.connect(self.path);db.execute('BEGIN IMMEDIATE')
        try:
            with self.assertRaises(QualityUnavailable):self.review()
        finally:db.rollback();db.close()
        self.assertEqual(self.store.page(['8001'])['rows'],[])

    def test_pbx_isolation_and_missing_form_do_not_create_reviews(self):
        other=QualityStore(self.path,pbx='other')
        self.assertIsNone(other.get_form(self.form['id']))
        with self.assertRaises(ValueError):other.create_review('v','8001','reviewer',self.form['id'],1,dict(opening=5,solution=5),'','k')
        self.assertEqual(other.page(['8001'])['rows'],[])

    def test_recording_scope_is_frozen_validated_and_part_of_idempotency(self):
        row=self.review(recording_id='opaque-audio',recording_queues=['8002','8001','8001'])
        self.assertEqual(row['recording_queues'],['8001','8002'])
        repeated=self.review(recording_id='opaque-audio',recording_queues=['8001','8002'])
        self.assertEqual(row['id'],repeated['id'])
        with self.assertRaises(QualityConflict):self.review(recording_id='opaque-audio',recording_queues=['8001'])
        self.assertEqual(self.store.get(row['id'],['8001'])['recording_queues'],['8001','8002'])
        for changes in (dict(recording_queues=['8001']),
                        dict(recording_id='audio',recording_queues=[]),
                        dict(recording_id='audio',recording_queues=['8002']),
                        dict(recording_id='audio',recording_queues=['8001']*257)):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.review('invalid',**changes)
        legacy=self.review('unproven',recording_id='audio')
        self.assertEqual(legacy['recording_queues'],[])

    def test_startup_migrates_legacy_scope_without_rewriting_reviews(self):
        row=self.review(recording_id='opaque-audio')
        original=sqlite3.connect(self.path);original.row_factory=sqlite3.Row
        legacy_path=Path(self.temp.name)/'legacy.db';legacy=sqlite3.connect(legacy_path)
        try:
            for table in ('quality_forms','quality_reviews'):
                schema=original.execute('SELECT sql FROM sqlite_master WHERE type=\'table\' AND name=?',(table,)).fetchone()[0]
                schema=schema.replace("recording_queues TEXT NOT NULL DEFAULT '[]',",'')
                legacy.execute(schema)
                columns=[info[1] for info in legacy.execute('PRAGMA table_info('+table+')')]
                for item in original.execute('SELECT * FROM '+table):
                    values={name:item[name] for name in columns}
                    if table=='quality_reviews':
                        spec=[row['visit_id'],row['queue'],row['form_id'],row['form_version'],row['scores'],row['comment'],row['recording_id'],row['notes']]
                        values['spec_hash']=hashlib.sha256(json.dumps(spec,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
                    legacy.execute('INSERT INTO '+table+'('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',tuple(values[name] for name in columns))
            legacy.commit()
        finally:legacy.close();original.close()
        upgraded=QualityStore(legacy_path);upgraded.initialize()
        restored=upgraded.get(row['id'],['8001'])
        self.assertEqual(restored['recording_queues'],[])
        self.assertEqual(restored['form_snapshot'],row['form_snapshot'])
        self.assertEqual(restored['created'],row['created'])
        repeat=upgraded.create_review(row['visit_id'],row['queue'],row['reviewer'],row['form_id'],row['form_version'],
            row['scores'],row['comment'],'request-1',recording_id=row['recording_id'])
        self.assertEqual(repeat['id'],row['id'])


if __name__=='__main__':unittest.main()
