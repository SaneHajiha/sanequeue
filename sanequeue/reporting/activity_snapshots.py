"""Versioned activity and atomically paired visit/activity worker snapshots.

DDL/bootstrap run only inside the reporting projector transaction. Page readers
never initialize schema or hold a transaction between pages. Raw bounds remain
available for clipping and censoring proofs; assignment cutoffs limit overlap.
"""
import json
import math
import re
import sqlite3

from . import visit_snapshots
from .queries import Scope, _where
from .snapshot_schema import FIELDS as VISIT_FIELDS
from .store import Archive

FIELDS = ('pbx', 'source_key', 'event_id', 'queue', 'agent', 'state', 'reason',
          'starts', 'ends', 'on_duty', 'coverage', 'canonical_agent')
COLUMNS = ','.join(FIELDS)
SCHEMA = '''
CREATE TABLE IF NOT EXISTS report_activity_snapshot_meta(
 pbx TEXT PRIMARY KEY,generation TEXT NOT NULL,ready INTEGER NOT NULL DEFAULT 0,
 bootstrap_after TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS report_activity_versions(
 seq INTEGER PRIMARY KEY,pbx TEXT,source_key TEXT,event_id INTEGER,queue TEXT,
 agent TEXT,state TEXT,reason TEXT,starts REAL,ends REAL,on_duty INTEGER,
 coverage TEXT,canonical_agent TEXT,deleted INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS rav_identity ON report_activity_versions(pbx,source_key,seq DESC);
CREATE INDEX IF NOT EXISTS rav_range ON report_activity_versions(pbx,queue,starts,source_key,seq);
'''
for operation, prefix in (('INSERT', 'NEW'), ('DELETE', 'OLD'), ('UPDATE', 'NEW')):
    SCHEMA += f'''CREATE TRIGGER IF NOT EXISTS report_activity_snapshot_{operation.lower()}
 AFTER {operation} ON report_activity BEGIN
 INSERT INTO report_activity_versions({COLUMNS},deleted)
 VALUES({','.join(prefix+'.'+field for field in FIELDS)},{int(operation=='DELETE')}); END;
'''
SCHEMA += f'''CREATE TRIGGER IF NOT EXISTS report_activity_snapshot_identity_change
 AFTER UPDATE ON report_activity WHEN OLD.pbx<>NEW.pbx OR OLD.source_key<>NEW.source_key BEGIN
 INSERT INTO report_activity_versions({COLUMNS},deleted)
 VALUES({','.join('OLD.'+field for field in FIELDS)},1); END;
'''
SnapshotUnavailable = visit_snapshots.SnapshotUnavailable


def install(db):
    """Install within the caller's transaction, without executescript COMMIT."""
    statement = ''
    for line in SCHEMA.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            db.execute(statement)
            statement = ''
    if statement.strip():
        raise RuntimeError('incomplete_activity_snapshot_schema')


def bootstrap(db, pbx, *, limit=500):
    """Capture no more than 500 legacy rows in one projector cycle."""
    if type(limit) is not int or limit < 1:
        raise ValueError('invalid_activity_bootstrap_limit')
    limit = min(limit, 500)
    db.execute('INSERT OR IGNORE INTO report_activity_snapshot_meta(pbx,generation) '
               'VALUES(?,lower(hex(randomblob(16))))', (pbx,))
    state = db.execute('SELECT ready,bootstrap_after FROM report_activity_snapshot_meta WHERE pbx=?', (pbx,)).fetchone()
    if state[0]:
        return
    rows = db.execute('SELECT '+COLUMNS+' FROM report_activity WHERE pbx=? AND source_key>? '
                      'ORDER BY source_key LIMIT ?', (pbx, state[1], limit)).fetchall()
    for row in rows:
        if not db.execute('SELECT 1 FROM report_activity_versions WHERE pbx=? AND source_key=? LIMIT 1',
                          (pbx, row[1])).fetchone():
            db.execute('INSERT INTO report_activity_versions('+COLUMNS+',deleted) VALUES('+
                       ','.join('?' for unused in FIELDS)+',0)', tuple(row))
    db.execute('UPDATE report_activity_snapshot_meta SET bootstrap_after=?,ready=? WHERE pbx=?',
               (rows[-1][1] if rows else state[1], int(len(rows) < limit), pbx))


def validate_token(token):
    visit_snapshots.validate_token(token)


def validate(db, pbx, token):
    validate_token(token)
    state = db.execute('SELECT generation,ready FROM report_activity_snapshot_meta WHERE pbx=?', (pbx,)).fetchone()
    if state is None or not state[1] or state[0] != token['generation']:
        raise SnapshotUnavailable('activity_snapshot_unavailable')
    latest = db.execute('SELECT COALESCE(MAX(seq),0) FROM report_activity_versions').fetchone()[0]
    if latest < token['sequence']:
        raise SnapshotUnavailable('activity_snapshot_unavailable')


def validate_pair_token(token, pbx=None):
    from .facts import PROJECTION_VERSION
    if (not isinstance(token, dict) or set(token) !=
            {'pbx', 'visits', 'activity', 'projection_version', 'watermark', 'activity_observed'}
            or not isinstance(token['pbx'], str) or not 0 < len(token['pbx']) <= 128
            or not token['pbx'].isprintable() or pbx is not None and token['pbx'] != pbx
            or type(token['watermark']) is not int or token['watermark'] < 0
            or type(token['projection_version']) is not int or token['projection_version'] != PROJECTION_VERSION
            or type(token['activity_observed']) not in (int, float)
            or not math.isfinite(token['activity_observed']) or token['activity_observed'] < 0):
        raise ValueError('invalid_agent_snapshot')
    validate_token(token['activity'])
    visit_snapshots.validate_token(token['visits'])


def validate_pair(db, pbx, token):
    validate_pair_token(token, pbx)
    version = db.execute('SELECT version FROM report_projection_version WHERE pbx=?', (pbx,)).fetchone()
    projection = db.execute('SELECT after_id FROM report_projection WHERE pbx=?', (pbx,)).fetchone()
    if (not version or version[0] != token['projection_version'] or not projection
            or projection[0] < token['watermark']):
        raise SnapshotUnavailable('agent_snapshot_projection_unavailable')
    visit_snapshots.validate(db, pbx, token['visits'])
    validate(db, pbx, token['activity'])


def capture(archive):
    from .facts import PROJECTION_VERSION
    try:
        with archive.reader() as db:
            activity = db.execute('SELECT generation,ready FROM report_activity_snapshot_meta WHERE pbx=?', (archive.pbx,)).fetchone()
            visits = db.execute('SELECT generation,ready FROM report_snapshot_meta WHERE pbx=?', (archive.pbx,)).fetchone()
            projection = db.execute('SELECT after_id FROM report_projection WHERE pbx=?', (archive.pbx,)).fetchone()
            version = db.execute('SELECT version FROM report_projection_version WHERE pbx=?', (archive.pbx,)).fetchone()
            head = db.execute('SELECT COALESCE(MAX(id),0) FROM events WHERE pbx=?', (archive.pbx,)).fetchone()[0]
            if (not activity or not activity[1] or not visits or not visits[1] or not projection
                    or not version or version[0] != PROJECTION_VERSION or projection[0] != head):
                raise SnapshotUnavailable('agent_snapshot_initializing')
            row = db.execute("SELECT value FROM checkpoints WHERE pbx=? AND source='activity_cache'", (archive.pbx,)).fetchone()
            if not row or len(row[0]) > 8192:
                raise SnapshotUnavailable('activity_heartbeat_unavailable')
            heartbeat = json.loads(row[0])
            observed = heartbeat.get('observed') if isinstance(heartbeat, dict) else None
            result = dict(pbx=archive.pbx, projection_version=PROJECTION_VERSION, watermark=head,
                          activity_observed=observed,
                          visits=dict(generation=visits[0], sequence=db.execute('SELECT COALESCE(MAX(seq),0) FROM report_visit_versions').fetchone()[0]),
                          activity=dict(generation=activity[0], sequence=db.execute('SELECT COALESCE(MAX(seq),0) FROM report_activity_versions').fetchone()[0]))
            validate_pair_token(result, archive.pbx)
            return result
    except (sqlite3.Error, ValueError, TypeError) as error:
        raise SnapshotUnavailable('agent_snapshot_unavailable') from error


def _page_reader(archive):
    return Archive(archive.path, pbx=archive.pbx, read_seconds=min(2, archive.read_seconds)).reader()


def _limit(value):
    if type(value) is not int or not 1 <= value <= 200:
        raise ValueError('invalid_agent_snapshot_page_limit')
    return value


def page(archive, token, scope, start, end, *, after=None, limit=200):
    limit = _limit(limit)
    _where(archive.pbx, scope, start, end)
    if after is not None and (not isinstance(after, str) or len(after) > 1024 or not after.isprintable()):
        raise ValueError('invalid_activity_snapshot_cursor')
    first = max(float(start), scope.not_before)
    if not math.isfinite(first):
        raise ValueError('invalid_activity_snapshot_cutoff')
    clause = 'v.pbx=?'
    args = [archive.pbx]
    if scope.queues:
        clause += ' AND v.queue IN ('+','.join('?' for unused in scope.queues)+')'
        args.extend(scope.queues)
    else:
        clause += ' AND 0'
    if scope.self_only:
        if scope.agents:
            marks = ','.join('?' for unused in scope.agents)
            clause += ' AND (v.agent IN ('+marks+') OR v.canonical_agent IN ('+marks+'))'
            args.extend((*scope.agents, *scope.agents))
        else:
            clause += ' AND 0'
    clause += ' AND v.source_key>? AND v.starts<? AND (v.ends IS NULL OR v.ends>?)'
    args.extend((after or '', min(float(end), token['activity_observed']), first))
    with _page_reader(archive) as db:
        validate_pair(db, archive.pbx, token)
        return [dict(row) for row in db.execute('SELECT '+','.join('v.'+f for f in FIELDS)+
            ' FROM report_activity_versions v INDEXED BY rav_identity WHERE '+clause+'''
            AND v.seq<=? AND v.deleted=0 AND NOT EXISTS (
              SELECT 1 FROM report_activity_versions newer WHERE newer.pbx=v.pbx
              AND newer.source_key=v.source_key AND newer.seq>v.seq AND newer.seq<=?)
            ORDER BY v.source_key LIMIT ?''', (*args, token['activity']['sequence'], token['activity']['sequence'], limit))]


def visit_page(archive, token, scope, start, end, queue, *, after=None, limit=200):
    limit = _limit(limit)
    if queue not in scope.queues:
        raise ValueError('agent_snapshot_queue_not_scoped')
    clause, args = _where(archive.pbx, Scope((queue,), scope.agents, scope.self_only, scope.not_before), start, end)
    if after is not None:
        if (not isinstance(after, (tuple, list)) or len(after) != 2 or type(after[0]) not in (int, float)
                or not math.isfinite(after[0]) or not isinstance(after[1], str)
                or not re.fullmatch('[0-9a-f]{64}', after[1])):
            raise ValueError('invalid_agent_snapshot_visit_cursor')
        clause += ' AND (entered>? OR (entered=? AND id>?))'
        args.extend((after[0], after[0], after[1]))
    with _page_reader(archive) as db:
        validate_pair(db, archive.pbx, token)
        return [dict(row) for row in db.execute('SELECT '+','.join('v.'+f for f in VISIT_FIELDS)+
            ' FROM report_visit_versions v WHERE '+clause+'''
            AND v.seq<=? AND v.deleted=0 AND NOT EXISTS (
              SELECT 1 FROM report_visit_versions newer WHERE newer.pbx=v.pbx
              AND newer.id=v.id AND newer.seq>v.seq AND newer.seq<=?)
            ORDER BY v.entered,v.id LIMIT ?''', (*args, token['visits']['sequence'], token['visits']['sequence'], limit))]
