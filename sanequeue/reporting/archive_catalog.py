"""Operator-only immutable catalog of monthly-labelled full archive snapshots.

No event partitioning, source deletion, live cutover or installation recovery.
Completed bundles survive process death before catalog publication. Unfinished
bundles are preserved as incomplete, never accepted or overwritten.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import time
import uuid

from . import backup

ID=re.compile(r'[a-f0-9]{32}\Z')
KEY=re.compile(r'[A-Za-z0-9_.:-]{1,100}\Z')
MONTH=re.compile(r'(?:19[7-9][0-9]|20[0-9]{2}|2100)-(?:0[1-9]|1[0-2])\Z')

class CatalogError(RuntimeError):pass
class Conflict(CatalogError):pass

class Budget:
    def __init__(self,seconds,max_bytes,reserve):
        if isinstance(seconds,bool) or not isinstance(seconds,(int,float)) or not math.isfinite(seconds) or not 0<seconds<=300 or type(max_bytes) is not int or not 4096<=max_bytes<=8*1024**3 or type(reserve) is not int or reserve<0:raise ValueError('invalid_catalog_limits')
        self.end=time.monotonic()+seconds;self.maximum=max_bytes;self.reserve=reserve
    def remaining(self):
        left=self.end-time.monotonic()
        if left<=0:raise CatalogError('catalog_deadline')
        return left
    def kwargs(self):return dict(seconds=self.remaining(),max_bytes=self.maximum)

class Catalog:
    def __init__(self,root):
        self.root=Path(root).absolute();self.bundles=self.root/'bundles';self.path=self.root/'catalog.sqlite3'
    def _directories(self):
        for path in (self.root,self.bundles):
            for parent in (path,*path.parents):
                if parent.is_symlink():raise CatalogError('catalog_symlink_directory')
            meta=path.stat()
            if not stat.S_ISDIR(meta.st_mode) or os.name!='nt' and (meta.st_uid!=os.geteuid() or meta.st_mode&0o077):raise CatalogError('catalog_private_directory_required')
    def initialize(self):
        # Only an operator CLI calls this. Existing directory permissions are
        # never silently relaxed or repaired.
        for path in (self.root,self.bundles):
            for parent in (path,*path.parents):
                if parent.is_symlink():raise CatalogError('catalog_symlink_directory')
            path.mkdir(exist_ok=True,mode=0o700)
        self._directories()
        if self.path.is_symlink():raise CatalogError('catalog_symlink_database')
        fd=os.open(self.path,os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0)|getattr(os,'O_NONBLOCK',0),0o600)
        try:
            meta=os.fstat(fd)
            if not stat.S_ISREG(meta.st_mode):raise CatalogError('catalog_regular_database_required')
            if os.name!='nt' and (meta.st_uid!=os.geteuid() or meta.st_mode&0o077):raise CatalogError('catalog_private_database_required')
        finally:os.close(fd)
        with self.db(write=True) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name IN ('events','feedback') LIMIT 1").fetchone():raise CatalogError('catalog_wrong_database')
            db.commit();db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''CREATE TABLE IF NOT EXISTS catalog_intents(
              id TEXT PRIMARY KEY,request_key TEXT UNIQUE NOT NULL,month TEXT NOT NULL,
              source_fingerprint TEXT NOT NULL,created REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS catalog_entries(
              sequence INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,
              month TEXT NOT NULL,bytes INTEGER NOT NULL,sha256 TEXT NOT NULL,
              event_high_watermark INTEGER NOT NULL,registered REAL NOT NULL);
              CREATE TRIGGER IF NOT EXISTS ce_no_update BEFORE UPDATE ON catalog_entries BEGIN SELECT RAISE(ABORT,'immutable');END;
              CREATE TRIGGER IF NOT EXISTS ce_no_delete BEFORE DELETE ON catalog_entries BEGIN SELECT RAISE(ABORT,'immutable');END;
              CREATE TRIGGER IF NOT EXISTS ci_no_update BEFORE UPDATE ON catalog_intents BEGIN SELECT RAISE(ABORT,'immutable');END;
              CREATE TRIGGER IF NOT EXISTS ci_no_delete BEFORE DELETE ON catalog_intents BEGIN SELECT RAISE(ABORT,'immutable');END;''')
        backup._sync(self.root)
    @contextmanager
    def db(self,write=False,budget=None):
        self._directories()
        if self.path.is_symlink() or not self.path.is_file():raise CatalogError('catalog_database_unavailable')
        if os.name!='nt' and self.path.stat().st_mode&0o077:raise CatalogError('catalog_private_database_required')
        remaining=budget.remaining() if budget else .5;deadline=time.monotonic()+min(.5,remaining)
        db=sqlite3.connect(self.path.as_uri()+('?mode=rw' if write else '?mode=ro'),uri=True,timeout=min(.05,remaining));db.row_factory=sqlite3.Row
        try:
            db.execute('PRAGMA trusted_schema=OFF');db.execute('PRAGMA cache_size=-1024');db.set_progress_handler(lambda:int(time.monotonic()>=deadline),100)
            if write:db.execute('PRAGMA synchronous=FULL');db.execute('BEGIN IMMEDIATE')
            else:db.execute('PRAGMA query_only=ON')
            with db:yield db
        finally:db.close()
    @staticmethod
    def _label(month,key):
        if not isinstance(month,str) or not MONTH.fullmatch(month) or not isinstance(key,str) or not KEY.fullmatch(key):raise ValueError('invalid_catalog_label_or_key')
    def bundle(self,ident):
        if not isinstance(ident,str) or not ID.fullmatch(ident):raise ValueError('invalid_catalog_id')
        self._directories();return self.bundles/ident
    def _reserve(self,month,key,fingerprint,budget,ident=None):
        self._label(month,key)
        if ident is not None:self.bundle(ident)
        with self.db(True,budget) as db:
            row=db.execute('SELECT * FROM catalog_intents WHERE request_key=?',(key,)).fetchone()
            if row:
                if row['month']!=month or row['source_fingerprint']!=fingerprint or ident is not None and row['id']!=ident:raise Conflict('catalog_request_conflict')
                return row['id']
            if db.execute('SELECT COUNT(*) FROM catalog_intents').fetchone()[0]>=1000:raise CatalogError('catalog_entry_limit')
            ident=ident or uuid.uuid4().hex
            if db.execute('SELECT 1 FROM catalog_intents WHERE id=?',(ident,)).fetchone():raise Conflict('catalog_bundle_already_reserved')
            db.execute('INSERT INTO catalog_intents VALUES(?,?,?,?,?)',(ident,key,month,fingerprint,time.time()))
            return ident
    def get(self,ident,budget=None):
        self.bundle(ident)
        with self.db(budget=budget) as db:row=db.execute('SELECT * FROM catalog_entries WHERE id=?',(ident,)).fetchone()
        if row is None:raise FileNotFoundError('catalog_entry_not_registered')
        return dict(row)
    def _publish(self,ident,month,manifest,budget):
        wanted=(month,manifest['bytes'],manifest['sha256'],manifest['event_high_watermark'])
        with self.db(True,budget) as db:
            prior=db.execute('SELECT * FROM catalog_entries WHERE id=?',(ident,)).fetchone()
            if prior:
                if tuple(prior[k] for k in ('month','bytes','sha256','event_high_watermark'))!=wanted:raise Conflict('catalog_entry_integrity_conflict')
                return dict(prior)
            intent=db.execute('SELECT month FROM catalog_intents WHERE id=?',(ident,)).fetchone()
            if intent is None or intent['month']!=month:raise Conflict('catalog_intent_missing')
            db.execute('INSERT INTO catalog_entries(id,month,bytes,sha256,event_high_watermark,registered) VALUES(?,?,?,?,?,?)',(ident,*wanted,time.time()))
            return dict(db.execute('SELECT * FROM catalog_entries WHERE id=?',(ident,)).fetchone())
    def create(self,source,month,key,*,seconds=60,max_bytes=1024**3,min_free_bytes=64*1024**2):
        budget=Budget(seconds,max_bytes,min_free_bytes);source=Path(source).absolute()
        # The source path is operator input only and is never returned publicly.
        fingerprint=hashlib.sha256(('create:'+str(source)).encode()).hexdigest()
        ident=self._reserve(month,key,fingerprint,budget);bundle=self.bundle(ident)
        try:self.get(ident,budget)
        except FileNotFoundError:pass
        else:return self.verify(ident,budget=budget)
        if bundle.exists() or bundle.is_symlink():
            if not bundle.is_dir() or bundle.is_symlink() or not (bundle/'manifest.json').is_file():raise CatalogError('catalog_bundle_incomplete')
        else:backup.backup(source,bundle,min_free_bytes=budget.reserve,**budget.kwargs())
        manifest=backup.verify(bundle,**budget.kwargs())
        return self._publish(ident,month,manifest,budget)
    def register(self,ident,month,key,*,seconds=60,max_bytes=1024**3):
        budget=Budget(seconds,max_bytes,0);self.bundle(ident)
        self._reserve(month,key,hashlib.sha256(('register:'+ident).encode()).hexdigest(),budget,ident=ident)
        manifest=backup.verify(self.bundle(ident),**budget.kwargs())
        return self._publish(ident,month,manifest,budget)
    def verify(self,ident,*,seconds=60,max_bytes=1024**3,budget=None):
        budget=budget or Budget(seconds,max_bytes,0);entry=self.get(ident,budget)
        manifest=backup.verify(self.bundle(ident),**budget.kwargs())
        if any(entry[k]!=manifest[k] for k in ('bytes','sha256','event_high_watermark')):raise CatalogError('catalog_bundle_changed')
        return entry
    def restore(self,ident,destination,*,seconds=60,max_bytes=1024**3,min_free_bytes=64*1024**2):
        budget=Budget(seconds,max_bytes,min_free_bytes);entry=self.verify(ident,budget=budget)
        result=backup.restore(self.bundle(ident),destination,min_free_bytes=budget.reserve,**budget.kwargs())
        if any(entry[k]!=result[k] for k in ('bytes','sha256','event_high_watermark')):raise CatalogError('catalog_restore_changed')
        return dict(id=ident,month=entry['month'],restored=True,**result)
    def list(self,*,before=None,limit=50):
        if type(limit) is not int or not 1<=limit<=100 or before is not None and (type(before) is not int or before<1):raise ValueError('invalid_catalog_page')
        with self.db() as db:
            rows=[dict(row) for row in db.execute('SELECT * FROM catalog_entries'+(' WHERE sequence<?' if before else '')+' ORDER BY sequence DESC LIMIT ?',((before,limit+1) if before else (limit+1,)))]
        return dict(entries=rows[:limit],next=rows[limit-1]['sequence'] if len(rows)>limit else None,verified_now=False,unit='monthly_labelled_full_archive_snapshot')
    def status(self):
        # Bounded metadata status, not a checksum/integrity scan.
        with self.db() as db:
            totals=dict(db.execute('SELECT (SELECT COUNT(*) FROM catalog_entries) completed,(SELECT COUNT(*) FROM catalog_intents) intents').fetchone())
            pending=[dict(row) for row in db.execute('SELECT i.id,i.month,i.created FROM catalog_intents i LEFT JOIN catalog_entries e ON e.id=i.id WHERE e.id IS NULL ORDER BY i.created,i.id LIMIT 100')]
        for row in pending:
            path=self.bundle(row['id'])
            manifest=path/'manifest.json'
            marker=not path.is_symlink() and not manifest.is_symlink() and manifest.is_file()
            row['state']='ready_for_registration_unverified' if marker else 'incomplete' if path.exists() or path.is_symlink() else 'not_started'
        return dict(**totals,pending=pending,pending_limit=100,verified_now=False)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',required=True)
    parser.add_argument('--seconds',type=float,default=60);parser.add_argument('--max-mib',type=int,default=1024);parser.add_argument('--reserve-mib',type=int,default=64)
    commands=parser.add_subparsers(dest='command',required=True)
    create=commands.add_parser('create');create.add_argument('source');create.add_argument('--month',required=True);create.add_argument('--key',required=True)
    register=commands.add_parser('register');register.add_argument('id');register.add_argument('--month',required=True);register.add_argument('--key',required=True)
    page=commands.add_parser('list');page.add_argument('--before',type=int);page.add_argument('--limit',type=int,default=50)
    commands.add_parser('status');verify=commands.add_parser('verify');verify.add_argument('id')
    restore=commands.add_parser('restore');restore.add_argument('id');restore.add_argument('destination')
    args=parser.parse_args();store=Catalog(args.root)
    try:
        store.initialize();common=dict(seconds=args.seconds,max_bytes=args.max_mib*1024**2)
        if args.command=='create':result=store.create(args.source,args.month,args.key,min_free_bytes=args.reserve_mib*1024**2,**common)
        elif args.command=='register':result=store.register(args.id,args.month,args.key,**common)
        elif args.command=='verify':result=store.verify(args.id,**common)
        elif args.command=='restore':result=store.restore(args.id,args.destination,min_free_bytes=args.reserve_mib*1024**2,**common)
        elif args.command=='list':result=store.list(before=args.before,limit=args.limit)
        else:result=store.status()
    except (OSError,ValueError,sqlite3.Error,CatalogError,backup.BackupError):
        parser.exit(1,'Catalog operation failed; retained private evidence was not deleted and no live database was replaced.\n')
    print(json.dumps(result,sort_keys=True))

if __name__=='__main__':main()
