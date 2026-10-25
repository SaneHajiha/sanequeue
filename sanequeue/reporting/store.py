"""Append-only source versions with atomic checkpoints and short SQLite readers.

This archive deliberately has no retention DELETE. It is separate from the
bounded live activity cache. Readers return pages, never live cursors.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import time


@dataclass(frozen=True)
class Event:
    source: str
    key: str
    timestamp: float
    kind: str
    payload: dict


class QueryDeadline(RuntimeError):
    pass


class Archive:
    def __init__(self, path, *, pbx='primary', read_seconds=5, min_free_bytes=64 * 1024 * 1024):
        self.path = Path(path).absolute()
        self.pbx = str(pbx)
        if not self.pbx or len(self.pbx) > 128:
            raise ValueError('invalid_pbx_id')
        self.read_seconds = max(.001, min(5, float(read_seconds)))
        self.min_free_bytes = min_free_bytes

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            if self.path.is_symlink() or not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError('invalid_archive_file')
            if os.name != 'nt':
                os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        with self.writer() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS events(
                  id INTEGER PRIMARY KEY, event_key TEXT NOT NULL UNIQUE,
                  pbx TEXT NOT NULL, source TEXT NOT NULL, source_key TEXT NOT NULL,
                  ts REAL NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
                  imported REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS event_source ON events(pbx,source,source_key);
                CREATE INDEX IF NOT EXISTS event_time ON events(pbx,ts,id);
                CREATE INDEX IF NOT EXISTS event_cursor ON events(pbx,id);
                CREATE TABLE IF NOT EXISTS source_items(
                  pbx TEXT,source TEXT,source_key TEXT,event_id INTEGER,
                  PRIMARY KEY(pbx,source,source_key));
                CREATE TABLE IF NOT EXISTS checkpoints(
                  pbx TEXT,source TEXT,value TEXT,updated REAL,
                  PRIMARY KEY(pbx,source));
                CREATE TABLE IF NOT EXISTS activity_import_open(
                  pbx TEXT,source TEXT,row_id INTEGER,source_key TEXT,payload TEXT,
                  PRIMARY KEY(pbx,source,row_id));
                CREATE TABLE IF NOT EXISTS sql_cdr_pending(
                  pbx TEXT,uid TEXT,due REAL,attempts INTEGER,created REAL,
                  PRIMARY KEY(pbx,uid));
                CREATE TABLE IF NOT EXISTS sql_cdr_unresolved(
                  pbx TEXT,uid TEXT,attempts INTEGER,last_checked REAL,reason TEXT,
                  PRIMARY KEY(pbx,uid));
                CREATE TABLE IF NOT EXISTS archive_stats(
                  pbx TEXT PRIMARY KEY,events INTEGER NOT NULL DEFAULT 0,
                  rejected INTEGER NOT NULL DEFAULT 0,updated REAL);
                CREATE TABLE IF NOT EXISTS evidence_edges(
                  pbx TEXT,event_id INTEGER,relation TEXT,from_kind TEXT,from_id TEXT,
                  to_kind TEXT,to_id TEXT,ts REAL,details TEXT,
                  PRIMARY KEY(pbx,event_id,relation,from_id,to_id));
                CREATE INDEX IF NOT EXISTS edge_from ON evidence_edges(pbx,from_kind,from_id,ts);
                CREATE INDEX IF NOT EXISTS edge_to ON evidence_edges(pbx,to_kind,to_id,ts);
                CREATE TABLE IF NOT EXISTS legs(
                  pbx TEXT,uid TEXT,channel TEXT,linkedid TEXT,
                  started REAL,answered REAL,ended REAL,PRIMARY KEY(pbx,uid));
                CREATE TABLE IF NOT EXISTS transfers(
                  pbx TEXT,event_id INTEGER,transfer_type TEXT,from_uid TEXT,target TEXT,
                  consultation_started REAL,consultation_ended REAL,consultation_duration REAL,
                  handoff_at REAL,PRIMARY KEY(pbx,event_id));
            ''')

    @contextmanager
    def writer(self):
        if self.path.is_symlink():
            raise ValueError('archive_symlink_refused')
        if shutil.disk_usage(self.path.parent).free < self.min_free_bytes:
            raise OSError('reporting_disk_pressure')
        db = sqlite3.connect(self.path, timeout=.5)
        try:
            db.execute('PRAGMA trusted_schema=OFF')
            db.execute('PRAGMA cache_size=-2048')
            db.execute('PRAGMA wal_autocheckpoint=512')
            db.execute('PRAGMA journal_size_limit=16777216')
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def reader(self):
        if self.path.is_symlink():
            raise ValueError('archive_symlink_refused')
        db = sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True, timeout=.25)
        db.row_factory = sqlite3.Row
        deadline = time.monotonic() + self.read_seconds
        db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        try:
            db.execute('PRAGMA query_only=ON')
            db.execute('PRAGMA trusted_schema=OFF')
            db.execute('PRAGMA cache_size=-2048')
            yield db
        except sqlite3.OperationalError as error:
            if 'interrupt' in str(error).lower():
                raise QueryDeadline('report_query_deadline') from error
            raise
        finally:
            db.set_progress_handler(None, 0)
            db.close()

    def checkpoint(self, source):
        with self.reader() as db:
            row = db.execute('SELECT value FROM checkpoints WHERE pbx=? AND source=?', (self.pbx, source)).fetchone()
            return json.loads(row[0]) if row else {}

    def append(self, events, *, checkpoint_source=None, checkpoint=None, rejected=0, update_state=None):
        from .correlate import project
        rows = []
        total_bytes = 0
        for event in events:
            if len(rows) >= 1000:
                raise ValueError('report_batch_too_large')
            if (not isinstance(event, Event) or not isinstance(event.payload, dict)
                    or not isinstance(event.source, str) or not 1 <= len(event.source) <= 128
                    or not isinstance(event.key, str) or not 1 <= len(event.key) <= 512
                    or not isinstance(event.kind, str) or not 1 <= len(event.kind) <= 128):
                raise ValueError('invalid_report_event')
            payload = json.dumps(event.payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
            total_bytes += len(payload.encode())
            if len(payload.encode()) > 65536 or not 0 <= event.timestamp <= 32503680000:
                raise ValueError('invalid_report_payload')
            if total_bytes > 4 * 1024 * 1024:
                raise ValueError('report_batch_byte_limit')
            identity = json.dumps([self.pbx, event.source, event.key, event.timestamp, event.kind, payload], ensure_ascii=False)
            rows.append((event, payload, hashlib.sha256(identity.encode()).hexdigest()))
        inserted = 0
        with self.writer() as db:
            db.execute('BEGIN IMMEDIATE')
            for event, payload, fingerprint in rows:
                result = db.execute('INSERT OR IGNORE INTO events(event_key,pbx,source,source_key,ts,kind,payload,imported) VALUES(?,?,?,?,?,?,?,?)',
                                    (fingerprint, self.pbx, event.source, event.key, event.timestamp, event.kind, payload, time.time()))
                event_id = db.execute('SELECT id FROM events WHERE event_key=?', (fingerprint,)).fetchone()[0]
                if result.rowcount:
                    inserted += 1
                    project(db, self.pbx, event_id, event)
                # A replay of an older payload must not replace a newer source version.
                db.execute('INSERT INTO source_items VALUES(?,?,?,?) ON CONFLICT(pbx,source,source_key) DO UPDATE SET event_id=MAX(event_id,excluded.event_id)',
                           (self.pbx, event.source, event.key, event_id))
            if checkpoint_source is not None:
                value = json.dumps(checkpoint, allow_nan=False)
                if len(value) > 8192:
                    raise ValueError('invalid_checkpoint')
                db.execute('INSERT OR REPLACE INTO checkpoints VALUES(?,?,?,?)', (self.pbx, checkpoint_source, value, time.time()))
            db.execute('INSERT INTO archive_stats VALUES(?,?,?,?) ON CONFLICT(pbx) DO UPDATE SET events=events+excluded.events,rejected=rejected+excluded.rejected,updated=excluded.updated',
                       (self.pbx, inserted, max(0, rejected), time.time()))
            if update_state is not None:
                # Trusted importer bookkeeping shares this transaction. A
                # failure must roll back evidence, cursor and open-row state.
                update_state(db)
        return inserted

    def page(self, *, after=0, limit=100, source=None):
        limit = max(1, min(500, int(limit)))
        with self.reader() as db:
            sql = 'SELECT id,source,source_key,ts,kind,payload FROM events WHERE pbx=? AND id>?'
            args = [self.pbx, max(0, int(after))]
            if source:
                sql += ' AND source=?'
                args.append(source)
            rows = [dict(row) for row in db.execute(sql + ' ORDER BY id LIMIT ?', (*args, limit))]
        for row in rows:
            row['payload'] = json.loads(row['payload'])
        return rows

    def status(self):
        with self.reader() as db:
            row = db.execute('SELECT * FROM archive_stats WHERE pbx=?', (self.pbx,)).fetchone()
            checkpoints = [dict(r) for r in db.execute('SELECT source,updated FROM checkpoints WHERE pbx=?', (self.pbx,))]
        wal = Path(str(self.path) + '-wal')
        return dict(pbx=self.pbx, counters=dict(row) if row else {}, checkpoints=checkpoints,
                    wal_bytes=wal.stat().st_size if wal.exists() else 0, retention='no_automatic_deletion')

    def passive_checkpoint(self):
        with self.writer() as db:
            return tuple(db.execute('PRAGMA wal_checkpoint(PASSIVE)').fetchone())
