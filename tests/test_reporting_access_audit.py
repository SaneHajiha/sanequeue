import base64
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import time
import unittest
from unittest.mock import patch

from sanequeue.reporting.access_audit import AuditStore,AuditUnavailable


class AccessAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'private'/'audio-audit.db'
        self.store=AuditStore(self.path);self.store.initialize()

    def test_fixed_bucket_dedup_is_per_user_recording_and_action(self):
        first=self.store.append('supervisor','opaque-a','play_request',now=31)
        duplicate=self.store.append('supervisor','opaque-a','play_request',now=59.9)
        self.assertTrue(first['created']);self.assertFalse(duplicate['created'])
        self.assertEqual(first['id'],duplicate['id']);self.assertEqual(duplicate['timestamp'],31)
        self.store.append('supervisor','opaque-a','play_request',now=60)
        self.store.append('supervisor','opaque-a','download_request',now=31)
        self.store.append('other','opaque-a','play_request',now=31)
        self.store.append('supervisor','opaque-b','play_request',now=31)
        self.assertEqual(len(self.store.page('opaque-a')['rows']),4)
        self.assertEqual(len(self.store.page('opaque-b')['rows']),1)

    def test_monotonic_cursor_survives_clock_rollback_and_new_insertions(self):
        expected=[]
        for now in (100,70,40,10):expected.append(self.store.append('user','recording','play_request',now=now)['id'])
        first=self.store.page('recording',limit=2)
        self.assertEqual([row['id'] for row in first['rows']],expected[::-1][:2])
        self.assertIsInstance(first['next'],str);self.assertEqual(len(first['next']),12)
        new=self.store.append('new-user','recording','play_request',now=1)
        second=self.store.page('recording',before=first['next'],limit=2)
        self.assertEqual([row['id'] for row in second['rows']],expected[::-1][2:])
        self.assertIsNone(second['next'])
        self.assertNotIn(new['id'],[row['id'] for row in second['rows']])
        self.assertEqual(self.store.page('another-recording',before=first['next'])['rows'],[])

    def test_page_limit_is_bounded_and_only_safe_columns_are_returned(self):
        for index in range(105):self.store.append('user','opaque','play_request',now=index*30)
        page=self.store.page('opaque',limit=10000)
        self.assertEqual(len(page['rows']),100);self.assertIsNotNone(page['next'])
        self.assertEqual(set(page['rows'][0]),{'id','user','timestamp','action'})
        self.assertEqual(len(self.store.page('opaque',before=page['next'])['rows']),5)
        for forbidden in ('recording','bucket','sequence','path','token','phone'):
            self.assertNotIn('"'+forbidden+'"',json.dumps(page))

    def test_invalid_arguments_do_not_write_and_cursor_is_strict(self):
        for owner,recording,action in (('', 'r','play_request'),('u'*129,'r','play_request'),
                                     ('u','r'*513,'play_request'),('u','r','played'),('u','r',[]),
                                     ('u\n','r','play_request'),('u','r\x00','download_request')):
            with self.assertRaises(ValueError):self.store.append(owner,recording,action,now=1)
        for now in (float('nan'),float('inf'),-1,True,'1'):
            with self.assertRaises(ValueError):self.store.append('u','r','play_request',now=now)
        for cursor in ('',1,'../audio.db','A'*12,base64.urlsafe_b64encode(b'\x01'+b'\x00'*8).decode()):
            with self.assertRaises(ValueError):self.store.page('r',before=cursor)
        for limit in (0,-1,True,1.5,'bad',None):
            with self.assertRaises(ValueError):self.store.page('r',limit=limit)
        self.assertEqual(self.store.page('r')['rows'],[])

    def test_missing_startup_database_fails_without_creating_a_file(self):
        missing=self.path.with_name('missing.db');store=AuditStore(missing)
        with self.assertRaises(AuditUnavailable):store.append('u','r','play_request',now=1)
        with self.assertRaises(AuditUnavailable):store.page('r')
        self.assertFalse(missing.exists())

    def test_busy_writer_fails_closed_and_dedup_does_not_bypass_contention(self):
        self.store.append('u','r','play_request',now=31)
        blocker=sqlite3.connect(self.path,timeout=.1)
        try:
            blocker.execute('BEGIN IMMEDIATE')
            started=time.monotonic()
            with self.assertRaises(AuditUnavailable):self.store.append('u','r','play_request',now=32)
            self.assertLess(time.monotonic()-started,.8)
            # WAL readers can still inspect committed requests during a writer.
            self.assertEqual(len(self.store.page('r')['rows']),1)
        finally:blocker.rollback();blocker.close()
        self.assertTrue(self.store.append('u','r','download_request',now=31)['created'])

    def test_read_deadline_interrupts_query_and_does_not_break_later_requests(self):
        for index in range(105):self.store.append('u','r','play_request',now=index*30)
        with patch('sanequeue.reporting.access_audit.time.monotonic',side_effect=[0]+[10]*100):
            with self.assertRaises(AuditUnavailable):self.store.page('r',limit=100)
        self.assertEqual(len(self.store.page('r',limit=1)['rows']),1)

    def test_private_regular_file_wal_and_symlink_guards(self):
        if os.name!='nt':self.assertEqual(stat.S_IMODE(self.path.stat().st_mode),0o600)
        db=sqlite3.connect(self.path)
        try:
            self.assertEqual(db.execute('PRAGMA journal_mode').fetchone()[0],'wal')
            indexes={row[1] for row in db.execute('PRAGMA index_list(recording_access)')}
            self.assertTrue({'ra_access_time','ra_access_cursor'}.issubset(indexes))
        finally:db.close()
        target=self.path.with_name('target.db');target.write_bytes(b'unchanged')
        link=self.path.with_name('link.db')
        try:link.symlink_to(target)
        except (OSError,NotImplementedError):return
        store=AuditStore(link)
        with self.assertRaises(AuditUnavailable):store.initialize()
        with self.assertRaises(AuditUnavailable):store.append('u','r','play_request',now=1)
        self.assertEqual(target.read_bytes(),b'unchanged')
