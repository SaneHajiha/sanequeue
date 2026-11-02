"""Operator catalog, immutable snapshots and real process-death registration."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from sanequeue.reporting.archive_catalog import Catalog,CatalogError,Conflict,Budget
from sanequeue.reporting.backup import backup,BackupError
from sanequeue.reporting.store import Archive,Event

class ArchiveCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.archive=Archive(self.root/'live.sqlite3',min_free_bytes=0);self.archive.initialize()
        self.archive.append([Event('cel','one',10,'ANSWER',{'uniqueid':'one'})])
        self.catalog=Catalog(self.root/'catalog');self.catalog.initialize()
    def create(self,**kwargs):return self.catalog.create(self.archive.path,'2026-10','monthly-test',min_free_bytes=0,**kwargs)
    def test_create_list_verify_and_restore_preserve_live_wal_and_all_months(self):
        self.archive.append([Event('cel','two',1793010000,'ANSWER',{'uniqueid':'two'})])
        entry=self.create();self.assertEqual(entry['event_high_watermark'],2)
        self.assertEqual(self.catalog.verify(entry['id']),entry)
        page=self.catalog.list();self.assertFalse(page['verified_now']);self.assertEqual(page['entries'],[entry])
        self.assertNotIn(str(self.root),json.dumps(page));self.assertNotIn('request_key',json.dumps(page))
        result=self.catalog.restore(entry['id'],self.root/'restored',min_free_bytes=0)
        self.assertTrue(result['restored']);self.assertEqual(len(Archive(self.root/'restored'/'archive.sqlite3').page()),2)
        self.assertEqual(len(self.archive.page()),2)
        with self.assertRaises(FileExistsError):self.catalog.restore(entry['id'],self.root/'restored',min_free_bytes=0)
    def test_same_request_replays_original_snapshot_after_source_grows(self):
        entry=self.create();self.archive.append([Event('cel','new',30,'ANSWER',{})])
        self.assertEqual(self.create(),entry)
        with self.assertRaises(Conflict):self.catalog.create(self.archive.path,'2026-11','monthly-test',min_free_bytes=0)
        with self.assertRaises(Conflict):self.catalog.create(self.root/'other.sqlite3','2026-10','monthly-test',min_free_bytes=0)
        self.assertEqual(self.catalog.status()['completed'],1)
    def test_immutable_catalog_and_bounded_list(self):
        entry=self.create()
        with self.catalog.db(True) as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('UPDATE catalog_entries SET month=? WHERE id=?',('2026-11',entry['id']))
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM catalog_intents')
        for n in (0,101,True):
            with self.assertRaises(ValueError):self.catalog.list(limit=n)
        self.assertEqual(self.catalog.list(before=entry['sequence'])['entries'],[])
    def test_real_process_death_after_complete_bundle_recovers_same_id(self):
        code='''import os,sys
from sanequeue.reporting.archive_catalog import Catalog
c=Catalog(sys.argv[1]);c.initialize()
c._publish=lambda *a,**k:os._exit(29)
c.create(sys.argv[2],'2026-10','monthly-test',min_free_bytes=0)
'''
        process=subprocess.run([sys.executable,'-c',code,str(self.catalog.root),str(self.archive.path)],capture_output=True,timeout=30)
        self.assertEqual(process.returncode,29,process.stderr.decode(errors='replace'))
        status=self.catalog.status();self.assertEqual(status['completed'],0);self.assertEqual(status['pending'][0]['state'],'ready_for_registration_unverified')
        ident=status['pending'][0]['id'];before=(self.catalog.bundle(ident)/'archive.sqlite3').read_bytes()
        result=self.create();self.assertEqual(result['id'],ident);self.assertEqual((self.catalog.bundle(ident)/'archive.sqlite3').read_bytes(),before)
        self.assertEqual(self.catalog.status()['completed'],1)
    def test_incomplete_bundle_is_retained_never_reused_or_registered(self):
        budget=Budget(5,1024**3,0);fingerprint=__import__('hashlib').sha256(('create:'+str(self.archive.path.absolute())).encode()).hexdigest()
        ident=self.catalog._reserve('2026-10','monthly-test',fingerprint,budget)
        bundle=self.catalog.bundle(ident);bundle.mkdir(mode=0o700);part=bundle/'archive.sqlite3';part.write_bytes(b'incomplete evidence')
        with self.assertRaisesRegex(CatalogError,'incomplete'):self.create()
        self.assertEqual(part.read_bytes(),b'incomplete evidence');self.assertEqual(self.catalog.status()['pending'][0]['state'],'incomplete')
        self.assertEqual(self.catalog.list()['entries'],[])
    def test_registered_missing_bundle_is_not_silently_rebuilt(self):
        entry=self.create();self.catalog.bundle(entry['id']).rename(self.root/'forensic')
        with self.assertRaises(FileNotFoundError):self.create()
        self.assertFalse(self.catalog.bundle(entry['id']).exists());self.assertEqual(self.catalog.get(entry['id']),entry)
    def test_register_only_uuid_under_catalog_and_verify_corruption(self):
        ident='a'*32;backup(self.archive.path,self.catalog.bundle(ident),min_free_bytes=0)
        entry=self.catalog.register(ident,'2026-09','import-test');self.assertEqual(entry['id'],ident)
        self.assertEqual(self.catalog.register(ident,'2026-09','import-test'),entry)
        with self.assertRaises(ValueError):self.catalog.register('../outside','2026-09','bad')
        path=self.catalog.bundle(ident)/'archive.sqlite3';data=bytearray(path.read_bytes());data[-1]^=1;path.write_bytes(data)
        with self.assertRaises(BackupError):self.catalog.verify(ident)
        self.assertEqual(self.catalog.get(ident),entry)
    def test_bundle_and_parent_symlinks_are_denied(self):
        if os.name=='nt':self.skipTest('Unix symlink safety runs in Linux CI')
        link=self.root/'linked';link.symlink_to(self.catalog.root,target_is_directory=True)
        with self.assertRaises(CatalogError):Catalog(link).initialize()
        ident='b'*32;self.catalog.bundle(ident).symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(BackupError):self.catalog.register(ident,'2026-10','symlink')
    def test_bounds_bad_month_low_disk_and_size_do_not_publish(self):
        for label in ('2026-13','2026-1','../../etc','2200-01'):
            with self.assertRaises(ValueError):self.catalog.create(self.archive.path,label,'bad',min_free_bytes=0)
        with self.assertRaises(ValueError):self.create(seconds=0)
        with self.assertRaises(BackupError):self.create(max_bytes=4096)
        with self.assertRaises(BackupError):self.catalog.create(self.archive.path,'2026-10','low-disk',min_free_bytes=10**30)
        self.assertEqual(self.catalog.list()['entries'],[])
        self.assertGreaterEqual(len(self.catalog.status()['pending']),1)
    def test_intent_quota_bounds_failed_attempts_without_deleting_evidence(self):
        with self.catalog.db(True) as db:
            db.executemany('INSERT INTO catalog_intents VALUES(?,?,?,?,?)',[(format(n,'032x'),'key-'+str(n),'2026-10','f'*64,0) for n in range(1000)])
        with self.assertRaisesRegex(CatalogError,'entry_limit'):self.create()
        status=self.catalog.status();self.assertEqual(status['intents'],1000);self.assertEqual(len(status['pending']),100)
    def test_database_public_permissions_fail_closed(self):
        if os.name=='nt':self.skipTest('Unix permissions run in Linux CI')
        self.catalog.path.chmod(0o644)
        with self.assertRaises(CatalogError):self.catalog.list()

if __name__=='__main__':unittest.main()
