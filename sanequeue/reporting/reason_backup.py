"""Operator-only CDR classification backup; restore to a new directory only.

The bundle contains private human-entered labels. SHA-256 detects corruption,
not malicious modification. No live database is replaced and no retention or
automatic scheduling is performed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from .backup import BackupError,_Budget,_regular,_private_directory,_open_read,_digest,_sync,_write_json


def _facts(db,budget,*,integrity=True):
    budget.check()
    if integrity and db.execute('PRAGMA quick_check(1)').fetchone()!=('ok',):raise BackupError('backup_integrity_failed')
    required={'cdr_reason_meta':{'pbx','revision'},
              'cdr_reason_current':{'pbx','source_key','reason','subreason','outcome','actor','updated'},
              'cdr_reason_audit':{'pbx','source_key','reason','subreason','outcome','actor','updated'}}
    for table,columns in required.items():
        if db.execute('SELECT type FROM sqlite_master WHERE name=?',(table,)).fetchone()!=('table',):raise BackupError('backup_not_cdr_reasons')
        if not columns<={row[1] for row in db.execute('PRAGMA table_info('+table+')')}:raise BackupError('backup_not_cdr_reasons')
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='events'").fetchone():raise BackupError('backup_not_cdr_reasons')
    result=dict(labels=db.execute('SELECT COUNT(*) FROM cdr_reason_current').fetchone()[0],
                audit_entries=db.execute('SELECT COUNT(*) FROM cdr_reason_audit').fetchone()[0])
    budget.check();return result


def backup(source,destination,*,seconds=30,max_bytes=1024**3,min_free_bytes=64*1024**2):
    budget=_Budget(seconds,max_bytes,min_free_bytes);source=Path(source).absolute();_regular(source)
    output=_private_directory(destination);target=output/'cdr-reasons.sqlite3';src=dst=None
    try:
        src=_open_read(source,budget);_facts(src,budget,integrity=False)
        page_size=src.execute('PRAGMA page_size').fetchone()[0];pages=src.execute('PRAGMA page_count').fetchone()[0]
        if page_size*pages>max_bytes:raise BackupError('backup_size_limit')
        budget.check(output,page_size*pages)
        fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_RDWR,0o600);os.close(fd)
        dst=sqlite3.connect(target,timeout=.05)
        def progress(status,remaining,total):
            if total*page_size>max_bytes:raise BackupError('backup_size_limit')
            budget.check(output,remaining*page_size)
            if remaining:time.sleep(.005)
        src.backup(dst,pages=64,progress=progress,sleep=.01)
        dst.execute('PRAGMA journal_mode=DELETE');dst.close();dst=None;src.close();src=None
        checked=_open_read(target,budget)
        try:facts=_facts(checked,budget)
        finally:checked.close()
        size,digest=_digest(target,budget)
        fd=os.open(target,os.O_RDWR|getattr(os,'O_NOFOLLOW',0))
        try:os.fsync(fd)
        finally:os.close(fd)
        manifest=dict(format='sanequeue-cdr-reasons',version=1,created_at=time.time(),bytes=size,sha256=digest,**facts)
        _write_json(output/'manifest.json',manifest);return manifest
    finally:
        if dst is not None:dst.close()
        if src is not None:src.close()


def _verify(bundle,budget):
    bundle=Path(bundle).absolute()
    if any(parent.is_symlink() for parent in (bundle,*bundle.parents)):raise BackupError('backup_symlink_directory')
    meta=_regular(bundle/'manifest.json')
    if meta.st_size>4096:raise BackupError('backup_invalid_manifest')
    try:manifest=json.loads((bundle/'manifest.json').read_text(encoding='utf-8'))
    except (ValueError,OSError):raise BackupError('backup_invalid_manifest') from None
    if (not isinstance(manifest,dict) or manifest.get('format')!='sanequeue-cdr-reasons' or
        type(manifest.get('version')) is not int or manifest['version']!=1 or
        type(manifest.get('bytes')) is not int or manifest['bytes']<4096 or
        type(manifest.get('labels')) is not int or manifest['labels']<0 or
        type(manifest.get('audit_entries')) is not int or manifest['audit_entries']<0 or
        not isinstance(manifest.get('sha256'),str) or len(manifest['sha256'])!=64):raise BackupError('backup_invalid_manifest')
    path=bundle/'cdr-reasons.sqlite3'
    if any(Path(str(path)+suffix).exists() or Path(str(path)+suffix).is_symlink() for suffix in ('-wal','-shm','-journal')):raise BackupError('backup_unsealed_database')
    size,digest=_digest(path,budget)
    if size!=manifest['bytes'] or digest!=manifest['sha256']:raise BackupError('backup_checksum_mismatch')
    db=_open_read(path,budget)
    try:facts=_facts(db,budget)
    finally:db.close()
    if any(manifest[key]!=value for key,value in facts.items()):raise BackupError('backup_boundary_mismatch')
    return path,manifest


def verify(bundle,*,seconds=30,max_bytes=1024**3):return _verify(bundle,_Budget(seconds,max_bytes,0))[1]


def restore(bundle,destination,*,seconds=30,max_bytes=1024**3,min_free_bytes=64*1024**2):
    budget=_Budget(seconds,max_bytes,min_free_bytes);source,manifest=_verify(bundle,budget)
    output=_private_directory(destination);budget.check(output,manifest['bytes']);target=output/'cdr-reasons.sqlite3'
    src=os.open(source,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0));digest=hashlib.sha256();total=0
    try:dst=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
    except BaseException:os.close(src);raise
    with os.fdopen(src,'rb') as reader,os.fdopen(dst,'wb') as writer:
        while True:
            budget.check(output);block=reader.read(256*1024)
            if not block:break
            total+=len(block)
            if total>manifest['bytes']:raise BackupError('backup_source_changed')
            writer.write(block);digest.update(block)
        writer.flush();os.fsync(writer.fileno())
    if total!=manifest['bytes'] or digest.hexdigest()!=manifest['sha256']:raise BackupError('backup_source_changed')
    db=_open_read(target,budget)
    try:facts=_facts(db,budget)
    finally:db.close()
    if any(manifest[key]!=value for key,value in facts.items()):raise BackupError('backup_boundary_mismatch')
    _sync(output);result=dict(format='sanequeue-cdr-reasons-restore',version=1,bytes=total,sha256=digest.hexdigest(),**facts)
    _write_json(output/'restore.json',result);return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('backup','verify','restore'))
    parser.add_argument('source');parser.add_argument('destination',nargs='?');args=parser.parse_args()
    if (args.command!='verify')!=(args.destination is not None):parser.error('backup/restore require a new destination')
    try:result=verify(args.source) if args.command=='verify' else backup(args.source,args.destination) if args.command=='backup' else restore(args.source,args.destination)
    except (BackupError,OSError,sqlite3.Error,ValueError):parser.exit(1,'CDR reason backup operation failed.\n')
    print(json.dumps(result,ensure_ascii=True,sort_keys=True))


if __name__=='__main__':main()
