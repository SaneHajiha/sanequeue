"""Real SQLite WAL preservation and bounded, non-destructive recovery drills."""
import errno
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from sanequeue.reporting.backup import backup, verify, restore, BackupError
import sanequeue.reporting.backup as backup_module
from sanequeue.reporting.store import Archive, Event


class ArchiveBackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.archive = Archive(self.root/'live.sqlite3', min_free_bytes=0)
        self.archive.initialize()
        self.bundle = self.root/'bundle'
        self.restored = self.root/'restored'

    def event(self, key):
        return Event('cel', key, 10, 'ANSWER', {'uniqueid': key})

    def create(self):
        return backup(self.archive.path, self.bundle, min_free_bytes=0)

    def test_online_wal_snapshot_preserves_events_checkpoints_and_original(self):
        # Keep a writer open: a file-copy of the database alone would miss WAL.
        with self.archive.writer() as writer:
            writer.execute('PRAGMA wal_autocheckpoint=0')
            self.archive.append([self.event('first')], checkpoint_source='cel', checkpoint={'id': 1})
            self.assertGreater(Path(str(self.archive.path)+'-wal').stat().st_size, 0)
            saved = self.create()
            self.archive.append([self.event('later')], checkpoint_source='cel', checkpoint={'id': 2})
            self.assertEqual(verify(self.bundle), saved)
            result = restore(self.bundle, self.restored, min_free_bytes=0)
        restored = Archive(self.restored/'archive.sqlite3', min_free_bytes=0)
        self.assertEqual(result['event_high_watermark'], 1)
        self.assertEqual(len(restored.page()), 1)
        self.assertEqual(restored.checkpoint('cel'), {'id': 1})
        self.assertEqual(len(self.archive.page()), 2)
        self.assertEqual(self.archive.checkpoint('cel'), {'id': 2})
        if os.name != 'nt':
            self.assertEqual(self.bundle.stat().st_mode & 0o077, 0)
            self.assertEqual((self.restored/'archive.sqlite3').stat().st_mode & 0o077, 0)

    def test_existing_destinations_are_never_overwritten_or_reused(self):
        self.create()
        before = (self.bundle/'archive.sqlite3').read_bytes()
        with self.assertRaises(FileExistsError): self.create()
        with self.assertRaises(FileExistsError): restore(self.bundle, self.root, min_free_bytes=0)
        self.assertEqual((self.bundle/'archive.sqlite3').read_bytes(), before)
        self.assertTrue(self.archive.path.is_file())

    def test_modified_content_and_changed_boundary_reject_restore_before_destination(self):
        self.create()
        manifest = self.bundle/'manifest.json'
        original = manifest.read_text()
        data = json.loads(original); data['event_high_watermark'] += 1
        manifest.write_text(json.dumps(data))
        with self.assertRaisesRegex(BackupError, 'boundary_mismatch'): restore(self.bundle, self.restored, min_free_bytes=0)
        self.assertFalse(self.restored.exists())
        manifest.write_text(original)
        with (self.bundle/'archive.sqlite3').open('r+b') as stream:
            stream.seek(4096); stream.write(b'corrupt')
        with self.assertRaisesRegex(BackupError, 'checksum_mismatch'): restore(self.bundle, self.restored, min_free_bytes=0)
        self.assertFalse(self.restored.exists())

    def test_incomplete_bundle_and_unsealed_wal_are_refused(self):
        incomplete = self.root/'incomplete'; incomplete.mkdir()
        (incomplete/'archive.sqlite3').write_bytes(b'partial')
        with self.assertRaises(OSError): verify(incomplete)
        self.create()
        Path(str(self.bundle/'archive.sqlite3')+'-wal').write_bytes(b'unknown')
        with self.assertRaisesRegex(BackupError, 'unsealed_database'): verify(self.bundle)

    def test_wrong_schema_is_refused_without_changing_source(self):
        other = self.root/'other.sqlite3'
        with closing(sqlite3.connect(other)) as db:
            with db: db.execute('CREATE TABLE unrelated(id INTEGER)')
        before = other.read_bytes()
        with self.assertRaisesRegex(BackupError, 'not_reporting_archive'):
            backup(other, self.bundle, min_free_bytes=0)
        self.assertEqual(other.read_bytes(), before)
        self.assertFalse((self.bundle/'manifest.json').exists())

    def test_size_disk_and_deadline_limits_leave_no_completion_marker(self):
        with self.assertRaisesRegex(BackupError, 'size_limit'):
            backup(self.archive.path, self.bundle, max_bytes=4096, min_free_bytes=0)
        self.assertFalse((self.bundle/'manifest.json').exists())
        low = self.root/'low'
        usage = type('Usage', (), {'free': 0})()
        with patch('sanequeue.reporting.backup.shutil.disk_usage', return_value=usage):
            with self.assertRaisesRegex(BackupError, 'disk_pressure'):
                backup(self.archive.path, low)
        self.assertFalse((low/'manifest.json').exists())
        late = self.root/'late'
        with self.assertRaisesRegex(BackupError, 'deadline'):
            backup(self.archive.path, late, seconds=1e-12, min_free_bytes=0)
        self.assertFalse((late/'manifest.json').exists())

    def test_io_failure_keeps_source_and_unfinished_private_bundle(self):
        before = self.archive.path.read_bytes()
        with patch('sanequeue.reporting.backup._write_json', side_effect=OSError(errno.ENOSPC, 'full')):
            with self.assertRaises(OSError): self.create()
        self.assertEqual(self.archive.path.read_bytes(), before)
        self.assertFalse((self.bundle/'manifest.json').exists())
        self.assertTrue((self.bundle/'archive.sqlite3').exists())

    def test_cli_roundtrip_and_safe_failure_output(self):
        command = [sys.executable, '-m', 'sanequeue.reporting.backup']
        for args in ([ 'backup',str(self.archive.path),str(self.bundle),'--reserve-mib','0'],
                     ['verify',str(self.bundle)],
                     ['restore',str(self.bundle),str(self.restored),'--reserve-mib','0']):
            result = subprocess.run(command+args, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('sha256', json.loads(result.stdout))
        failed = subprocess.run(command+['restore',str(self.bundle),str(self.restored)], capture_output=True, text=True, timeout=15)
        self.assertEqual(failed.returncode, 1)
        self.assertNotIn(str(self.root), failed.stderr)
        self.assertNotIn('Traceback', failed.stderr)

    def test_real_process_death_never_marks_incomplete_backup_as_complete(self):
        script = '''import os,sys
import sanequeue.reporting.backup as module
module._write_json=lambda *args:os._exit(29)
module.backup(sys.argv[1],sys.argv[2],min_free_bytes=0)
'''
        result = subprocess.run([sys.executable,'-c',script,str(self.archive.path),str(self.bundle)],
                                capture_output=True,timeout=15)
        self.assertEqual(result.returncode,29)
        self.assertTrue((self.bundle/'archive.sqlite3').is_file())
        self.assertFalse((self.bundle/'manifest.json').exists())
        with self.assertRaises(OSError): verify(self.bundle)
        self.archive.append([self.event('after-crash')])
        self.assertEqual(len(self.archive.page()),1)

    def test_restore_completion_marker_failure_does_not_touch_verified_bundle(self):
        saved=self.create()
        with patch('sanequeue.reporting.backup._write_json',side_effect=OSError(errno.ENOSPC,'full')):
            with self.assertRaises(OSError):restore(self.bundle,self.restored,min_free_bytes=0)
        self.assertFalse((self.restored/'restore.json').exists())
        self.assertEqual(verify(self.bundle),saved)
        with self.assertRaises(FileExistsError):restore(self.bundle,self.restored,min_free_bytes=0)

    def test_marker_fsync_failure_does_not_publish_valid_json_as_complete(self):
        original = backup_module._write_json
        def fail_marker(path,value):
            with patch('sanequeue.reporting.backup.os.fsync',side_effect=OSError(errno.ENOSPC,'sync failed')):
                return original(path,value)
        with patch('sanequeue.reporting.backup._write_json',side_effect=fail_marker):
            with self.assertRaises(OSError):self.create()
        self.assertTrue((self.bundle/'archive.sqlite3').is_file())
        self.assertFalse((self.bundle/'manifest.json').exists())
        with self.assertRaises(OSError):verify(self.bundle)

    def test_post_publication_sync_failure_retires_only_own_completion_marker(self):
        original = backup_module._write_json
        def fail_publish_sync(path,value):
            with patch('sanequeue.reporting.backup._sync',side_effect=[None,OSError(errno.EIO,'sync failed'),None]):
                return original(path,value)
        with patch('sanequeue.reporting.backup._write_json',side_effect=fail_publish_sync):
            with self.assertRaises(OSError):self.create()
        self.assertFalse((self.bundle/'manifest.json').exists())
        self.assertTrue((self.bundle/'archive.sqlite3').is_file())
        with self.assertRaises(OSError):verify(self.bundle)

    @unittest.skipIf(os.name == 'nt', 'Linux symlink behaviour covered in CI')
    def test_symlink_source_bundle_and_destination_parents_are_refused(self):
        link = self.root/'link.sqlite3'; link.symlink_to(self.archive.path)
        with self.assertRaises(BackupError): backup(link, self.bundle, min_free_bytes=0)
        self.create()
        linked = self.root/'linked'; linked.symlink_to(self.bundle, target_is_directory=True)
        with self.assertRaises(BackupError): verify(linked)
        with self.assertRaises(BackupError): restore(self.bundle, linked/'child', min_free_bytes=0)


if __name__ == '__main__':
    unittest.main()
