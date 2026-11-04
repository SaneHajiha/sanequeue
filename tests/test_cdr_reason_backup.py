from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from sanequeue.reporting.cdr_reasons import Reasons
from sanequeue.reporting.reason_backup import backup,verify,restore
from sanequeue.reporting.backup import BackupError


class CDRReasonBackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.source=self.root/'source.sqlite3'
        self.labels=Reasons(self.source);self.labels.initialize()
        self.labels.set('segment','پشتیبانی','نصب','حل شد','admin')
        self.labels.set('segment','پشتیبانی','نصب','پیگیری','admin')
        self.labels.set_catalog('پشتیبانی','نصب',True,'admin')

    def test_private_backup_and_restore_preserve_labels_and_history(self):
        bundle=self.root/'bundle';dest=self.root/'restore'
        with closing(sqlite3.connect(self.source)) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('INSERT INTO cdr_reason_current VALUES(?,?,?,?,?,?,?)',('primary','wal-segment','فروش','','','admin',1))
            db.commit()
            self.assertTrue(Path(str(self.source)+'-wal').exists())
            result=backup(self.source,bundle,min_free_bytes=0)
        self.assertEqual((result['labels'],result['audit_entries']),(2,2))
        self.assertEqual(verify(bundle)['sha256'],result['sha256'])
        restored=restore(bundle,dest,min_free_bytes=0)
        self.assertEqual(restored['sha256'],result['sha256'])
        self.assertEqual(Reasons(dest/'cdr-reasons.sqlite3').get('segment')['outcome'],'پیگیری')
        self.assertEqual(Reasons(dest/'cdr-reasons.sqlite3').get('wal-segment')['reason'],'فروش')
        self.assertEqual(Reasons(dest/'cdr-reasons.sqlite3').catalog(),[{'reason':'پشتیبانی','subreason':'نصب'}])
        with self.assertRaises(FileExistsError):restore(bundle,dest,min_free_bytes=0)

    def test_corruption_is_rejected_without_publishing_restore(self):
        bundle=self.root/'bundle';backup(self.source,bundle,min_free_bytes=0)
        target=bundle/'cdr-reasons.sqlite3'
        with target.open('r+b') as stream:stream.seek(128);stream.write(b'broken')
        with self.assertRaises(BackupError):verify(bundle)
        dest=self.root/'restore'
        with self.assertRaises(BackupError):restore(bundle,dest,min_free_bytes=0)
        self.assertFalse(dest.exists())


if __name__=='__main__':unittest.main()
