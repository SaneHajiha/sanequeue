"""Bounded operator-only archive backup and restore into new private directories.

No HTTP routes, PBX access, retention deletion or live database replacement.
SHA-256 detects corruption; it is not authentication against a malicious owner.
Directories are trusted administrator-controlled local storage, not remote input.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import time
import uuid


class BackupError(RuntimeError):
    pass


class _Budget:
    def __init__(self, seconds, max_bytes, min_free_bytes):
        if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
                or not math.isfinite(seconds) or not 0 < seconds <= 300
                or type(max_bytes) is not int or not 4096 <= max_bytes <= 1024**4
                or type(min_free_bytes) is not int or min_free_bytes < 0):
            raise ValueError('invalid_backup_limits')
        self.end = time.monotonic() + seconds
        self.maximum = max_bytes
        self.reserve = min_free_bytes

    def check(self, directory=None, remaining=0):
        if time.monotonic() >= self.end:
            raise BackupError('backup_deadline')
        if directory is not None and shutil.disk_usage(directory).free < self.reserve + remaining:
            raise BackupError('backup_disk_pressure')


def _regular(path):
    meta = path.lstat()
    if not stat.S_ISREG(meta.st_mode):
        raise BackupError('backup_regular_file_required')
    return meta


def _private_directory(path):
    # Refuse existing directories too: an interrupted bundle is never reused.
    path = Path(path).absolute()
    for parent in (path.parent, *path.parent.parents):
        if parent.is_symlink():
            raise BackupError('backup_symlink_directory')
    if not path.parent.is_dir():
        raise BackupError('backup_parent_missing')
    path.mkdir(mode=0o700)
    _sync(path.parent)
    return path


def _open_read(path, budget):
    for parent in path.parents:
        if parent.is_symlink():
            raise BackupError('backup_symlink_directory')
    before = _regular(path)
    if before.st_size > budget.maximum:
        raise BackupError('backup_size_limit')
    for suffix in ('-wal', '-shm', '-journal'):
        sidecar = Path(str(path) + suffix)
        if sidecar.is_symlink():
            raise BackupError('backup_symlink_sidecar')
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=.05)
    try:
        after = _regular(path)
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise BackupError('backup_source_changed')
        db.execute('PRAGMA trusted_schema=OFF')
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA cache_size=-1024')
        db.set_progress_handler(lambda: int(time.monotonic() >= budget.end), 1000)
        return db
    except BaseException:
        db.close()
        raise


def _facts(db, budget, *, integrity=True):
    budget.check()
    if integrity and db.execute('PRAGMA quick_check(1)').fetchone() != ('ok',):
        raise BackupError('backup_integrity_failed')
    required = {
        'events': {'id', 'event_key', 'pbx', 'source', 'source_key', 'ts', 'kind', 'payload', 'imported'},
        'source_items': {'pbx', 'source', 'source_key', 'event_id'},
        'checkpoints': {'pbx', 'source', 'value', 'updated'},
    }
    for table, columns in required.items():
        row = db.execute('SELECT type FROM sqlite_master WHERE name=?', (table,)).fetchone()
        if row != ('table',) or not columns <= {r[1] for r in db.execute('PRAGMA table_info(' + table + ')')}:
            raise BackupError('backup_not_reporting_archive')
    # A checkpoint boundary is useful without scanning events or exposing numbers.
    maximum = db.execute('SELECT COALESCE(MAX(id),0) FROM events').fetchone()[0]
    budget.check()
    return {'event_high_watermark': maximum}


def _sync(directory):
    if os.name != 'nt':
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | getattr(os, 'O_NOFOLLOW', 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _write_json(path, value):
    temporary = path.parent / ('.' + path.name + '.' + uuid.uuid4().hex + '.pending')
    published = False
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, sort_keys=True, ensure_ascii=True, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        _sync(path.parent)
        os.link(temporary, path, follow_symlinks=False)
        published = True
        _sync(path.parent)
    except BaseException:
        # A reported failure must not leave our completion marker accepted.
        # Only retire our own hardlink; retain the database for investigation.
        if published:
            try:
                if os.path.samestat(temporary.lstat(), path.lstat()):
                    path.unlink()
                    _sync(path.parent)
            except OSError:
                pass  # Storage may be unavailable; durability is indeterminate.
        raise
    finally:
        try:
            temporary.unlink()
        except OSError:
            pass  # Unpublished private temporary marker is never accepted.


def _digest(path, budget):
    meta = _regular(path)
    if meta.st_size > budget.maximum:
        raise BackupError('backup_size_limit')
    digest = hashlib.sha256()
    total = 0
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    with os.fdopen(fd, 'rb') as stream:
        while True:
            budget.check()
            block = stream.read(256 * 1024)
            if not block:
                break
            total += len(block)
            if total > budget.maximum:
                raise BackupError('backup_size_limit')
            digest.update(block)
    return total, digest.hexdigest()


def backup(source, destination, *, seconds=30, max_bytes=1024**3, min_free_bytes=64*1024**2):
    """SQLite online backup includes committed WAL, without checkpointing source."""
    budget = _Budget(seconds, max_bytes, min_free_bytes)
    source = Path(source).absolute()
    _regular(source)
    output = _private_directory(destination)
    target = output / 'archive.sqlite3'
    src = dst = None
    try:
        budget.check(output)
        src = _open_read(source, budget)
        _facts(src, budget, integrity=False)
        page_size = src.execute('PRAGMA page_size').fetchone()[0]
        page_count = src.execute('PRAGMA page_count').fetchone()[0]
        if page_count * page_size > budget.maximum:
            raise BackupError('backup_size_limit')
        budget.check(output, page_count * page_size)
        fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.close(fd)
        dst = sqlite3.connect(target, timeout=.05)
        dst.execute('PRAGMA cache_size=-1024')
        def progress(status, remaining, total):
            if total * page_size > budget.maximum:
                raise BackupError('backup_size_limit')
            budget.check(output, remaining * page_size)
            if remaining:
                time.sleep(.005)  # Yield between short backup steps, outside PBX.
        src.backup(dst, pages=64, progress=progress, sleep=.01)
        dst.execute('PRAGMA journal_mode=DELETE')
        dst.close(); dst = None
        src.close(); src = None
        checked = _open_read(target, budget)
        try:
            facts = _facts(checked, budget)
        finally:
            checked.close()
        size, digest = _digest(target, budget)
        fd = os.open(target, os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        manifest = dict(format='sanequeue-reporting-archive', version=1,
                        created_at=time.time(), bytes=size, sha256=digest, **facts)
        budget.check(output)
        # Manifest is the final completion marker. Failure leaves private evidence.
        _write_json(output/'manifest.json', manifest)
        return manifest
    finally:
        if dst is not None: dst.close()
        if src is not None: src.close()


def _verify(bundle, budget):
    bundle = Path(bundle).absolute()
    for parent in (bundle, *bundle.parents):
        if parent.is_symlink():
            raise BackupError('backup_symlink_directory')
    manifest_file = bundle/'manifest.json'
    meta = _regular(manifest_file)
    if meta.st_size > 4096:
        raise BackupError('backup_invalid_manifest')
    manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
    if (not isinstance(manifest, dict) or manifest.get('format') != 'sanequeue-reporting-archive'
            or type(manifest.get('version')) is not int or manifest['version'] != 1
            or type(manifest.get('bytes')) is not int or manifest['bytes'] < 4096
            or type(manifest.get('event_high_watermark')) is not int
            or manifest['event_high_watermark'] < 0
            or not isinstance(manifest.get('sha256'), str) or len(manifest['sha256']) != 64):
        raise BackupError('backup_invalid_manifest')
    path = bundle/'archive.sqlite3'
    if any(Path(str(path)+suffix).exists() or Path(str(path)+suffix).is_symlink()
           for suffix in ('-wal', '-shm', '-journal')):
        raise BackupError('backup_unsealed_database')
    size, digest = _digest(path, budget)
    if size != manifest['bytes'] or digest != manifest['sha256']:
        raise BackupError('backup_checksum_mismatch')
    db = _open_read(path, budget)
    try:
        facts = _facts(db, budget)
    finally:
        db.close()
    if facts['event_high_watermark'] != manifest['event_high_watermark']:
        raise BackupError('backup_boundary_mismatch')
    return path, manifest


def verify(bundle, *, seconds=30, max_bytes=1024**3):
    """Verify local bundle integrity, schema and event boundary, without writes."""
    return _verify(bundle, _Budget(seconds, max_bytes, 0))[1]


def restore(bundle, destination, *, seconds=30, max_bytes=1024**3, min_free_bytes=64*1024**2):
    """Restore only to a new directory. Never switch or overwrite live stores."""
    budget = _Budget(seconds, max_bytes, min_free_bytes)
    source, manifest = _verify(bundle, budget)
    output = _private_directory(destination)
    budget.check(output, manifest['bytes'])
    target = output/'archive.sqlite3'
    digest = hashlib.sha256()
    total = 0
    src_fd = os.open(source, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        dst_fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except BaseException:
        os.close(src_fd)
        raise
    with os.fdopen(src_fd, 'rb') as src, os.fdopen(dst_fd, 'wb') as dst:
        while True:
            budget.check(output)
            block = src.read(256*1024)
            if not block: break
            total += len(block)
            if total > manifest['bytes']: raise BackupError('backup_source_changed')
            dst.write(block); digest.update(block)
            time.sleep(.005)
        dst.flush(); os.fsync(dst.fileno())
    if total != manifest['bytes'] or digest.hexdigest() != manifest['sha256']:
        raise BackupError('backup_source_changed')
    db = _open_read(target, budget)
    try:
        facts = _facts(db, budget)
    finally:
        db.close()
    if facts['event_high_watermark'] != manifest['event_high_watermark']:
        raise BackupError('backup_boundary_mismatch')
    budget.check(output)
    result = dict(format='sanequeue-reporting-restore', version=1,
                  restored_at=time.time(), bytes=total, sha256=digest.hexdigest(), **facts)
    _write_json(output/'restore.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('backup', 'verify', 'restore'))
    parser.add_argument('source')
    parser.add_argument('destination', nargs='?')
    parser.add_argument('--seconds', type=float, default=30)
    parser.add_argument('--max-mib', type=int, default=1024)
    parser.add_argument('--reserve-mib', type=int, default=64)
    args = parser.parse_args()
    if (args.command != 'verify') != (args.destination is not None):
        parser.error('backup/restore require destination; verify accepts only source')
    try:
        common = dict(seconds=args.seconds, max_bytes=args.max_mib*1024**2)
        if args.command == 'verify': result = verify(args.source, **common)
        else:
            operation = backup if args.command == 'backup' else restore
            result = operation(args.source, args.destination, min_free_bytes=args.reserve_mib*1024**2, **common)
    except (OSError, ValueError, sqlite3.Error, BackupError):
        # No source path, SQL or customer data in default command output.
        parser.exit(1, 'Archive operation failed; no live database was replaced. Check limits, storage and private bundle locally.\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
