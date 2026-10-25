"""Incremental, rebuildable reporting facts; raw evidence remains authoritative.

Run in a worker, never during an HTTP request. A queue visit is a queue entry,
not a CDR row or a unique customer conversation. Missing evidence stays NULL.
"""
import hashlib
import json
import math
import re
import time


SCHEMA = '''
CREATE TABLE IF NOT EXISTS report_projection(pbx TEXT PRIMARY KEY,after_id INTEGER,updated REAL);
CREATE TABLE IF NOT EXISTS report_projection_version(pbx TEXT PRIMARY KEY,version INTEGER);
CREATE TABLE IF NOT EXISTS report_queue_events(
 pbx TEXT,event_id INTEGER,callid TEXT,queue TEXT,agent TEXT,ts REAL,kind TEXT,data TEXT,
 PRIMARY KEY(pbx,event_id));
CREATE INDEX IF NOT EXISTS rq_call ON report_queue_events(pbx,queue,callid,ts,event_id);
CREATE INDEX IF NOT EXISTS rq_identity ON report_queue_events(pbx,callid,queue);
CREATE TABLE IF NOT EXISTS report_visits(
 pbx TEXT,id TEXT,callid TEXT,queue TEXT,entered REAL,answered REAL,ended REAL,
 caller TEXT,agent TEXT,outcome TEXT,wait_seconds REAL,talk_seconds REAL,
 segment_ended_by TEXT,coverage TEXT,PRIMARY KEY(pbx,id));
CREATE INDEX IF NOT EXISTS rv_queue_time ON report_visits(pbx,queue,entered,id);
CREATE INDEX IF NOT EXISTS rv_call ON report_visits(pbx,callid);
CREATE TABLE IF NOT EXISTS report_cdr(
 pbx TEXT,source_key TEXT,event_id INTEGER,ts REAL,uid TEXT,linkedid TEXT,
 src TEXT,dst TEXT,channel TEXT,dstchannel TEXT,duration REAL,billsec REAL,
 disposition TEXT,recording TEXT,PRIMARY KEY(pbx,source_key));
CREATE INDEX IF NOT EXISTS rc_time ON report_cdr(pbx,ts,source_key);
CREATE INDEX IF NOT EXISTS rc_uid ON report_cdr(pbx,uid);
CREATE INDEX IF NOT EXISTS rc_linked ON report_cdr(pbx,linkedid);
CREATE TABLE IF NOT EXISTS report_cel_transfers(
 pbx TEXT,source_key TEXT,uid TEXT,linkedid TEXT,channel TEXT,ts REAL,kind TEXT,
 PRIMARY KEY(pbx,source_key));
CREATE INDEX IF NOT EXISTS rct_link ON report_cel_transfers(pbx,linkedid,ts);
CREATE INDEX IF NOT EXISTS rct_uid ON report_cel_transfers(pbx,uid,ts);
'''
PROJECTION_VERSION = 2


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) and 0 <= result <= 315360000 else None
    except (ValueError, TypeError):
        return None


def _visit_id(pbx, queue, callid, event_id):
    return hashlib.sha256(json.dumps([pbx, queue, callid, event_id]).encode()).hexdigest()


def _endpoint(value):
    """Match only explicit SIP/PJSIP/Local endpoint identities, never substrings."""
    if re.fullmatch(r'[0-9]{1,20}', value):
        # queue_log can record a numeric membername instead of its interface.
        return value
    match = re.fullmatch(r'(?:PJSIP|SIP)/([A-Za-z0-9_.]+)(?:-[0-9a-fA-F]+)?', value)
    if not match:
        match = re.fullmatch(r'Local/([A-Za-z0-9_.]+)@[^/;]+(?:/n|-[0-9a-fA-F]+;[12])?', value)
    return match.group(1) if match else None


def _rebuild_visits(db, pbx, queue, callid):
    events = db.execute('''SELECT event_id,ts,kind,agent,data FROM report_queue_events
      WHERE pbx=? AND queue=? AND callid=? ORDER BY ts,event_id LIMIT 10001''',
                        (pbx, queue, callid)).fetchall()
    if len(events) > 10000:
        raise ValueError('queue_call_evidence_limit')
    # Only derived facts are replaced. No source history is removed.
    db.execute('DELETE FROM report_visits WHERE pbx=? AND queue=? AND callid=?', (pbx, queue, callid))
    visits = []
    current = None
    for event_id, ts, kind, agent, data in events:
        values = json.loads(data)
        if kind == 'ENTERQUEUE':
            if current and current['ended'] is None:
                current['outcome'] = 'reentered_without_end'
                current['coverage'] = 'missing_end'
            current = dict(id=_visit_id(pbx, queue, callid, event_id), entered=ts,
                           answered=None, ended=None, caller=str(values[1]) if len(values) > 1 else '',
                           agent='', outcome='waiting', wait_seconds=None, talk_seconds=None,
                           segment_ended_by=None, coverage='observed')
            visits.append(current)
        elif kind in ('CONNECT', 'COMPLETECALLER', 'COMPLETEAGENT', 'ABANDON',
                      'EXITWITHTIMEOUT', 'EXITEMPTY', 'EXITWITHKEY', 'TRANSFER',
                      'BLINDTRANSFER', 'ATTENDEDTRANSFER'):
            if (current and current['outcome'] == 'transferred'
                    and kind in ('COMPLETECALLER', 'COMPLETEAGENT')):
                # A redirected Queue application can complete after transfer.
                # Its duration spans the downstream conversation, not just
                # this agent's queue segment. Preserve raw evidence without
                # creating a second visit or attributing a final hangup.
                continue
            if current is None or current['ended'] is not None:
                current = dict(id=_visit_id(pbx, queue, callid, event_id), entered=ts,
                               answered=None, ended=None, caller='', agent='', outcome='unknown',
                               wait_seconds=None, talk_seconds=None, segment_ended_by=None,
                               coverage='missing_entry')
                visits.append(current)
            if kind == 'CONNECT':
                current.update(answered=ts, agent=agent, outcome='connected',
                               wait_seconds=number(values[0]) if values else None)
            elif kind in ('COMPLETECALLER', 'COMPLETEAGENT'):
                current.update(ended=ts, agent=agent, outcome='answered',
                               wait_seconds=number(values[0]) if values else None,
                               talk_seconds=number(values[1]) if len(values) > 1 else None,
                               segment_ended_by='caller' if kind == 'COMPLETECALLER' else 'agent')
            elif kind == 'ABANDON':
                current.update(ended=ts, outcome='abandoned', wait_seconds=number(values[2]) if len(values) > 2 else None)
            elif kind in ('EXITWITHTIMEOUT', 'EXITEMPTY', 'EXITWITHKEY'):
                current.update(ended=ts, outcome=kind.lower(), wait_seconds=number(values[2]) if len(values) > 2 else None)
            else:
                # Transfer ends this queue segment; it does not identify who
                # eventually hung up the entire transferred conversation.
                current.update(ended=ts, agent=agent, outcome='transferred')
    transfers = db.execute('''SELECT channel,ts FROM report_cel_transfers
      WHERE pbx=? AND (uid=? OR linkedid=?) ORDER BY ts LIMIT 1001''',
                           (pbx, callid, callid)).fetchall()
    if len(transfers) > 1000:
        raise ValueError('queue_transfer_evidence_limit')
    for channel, transfer_time in transfers:
        endpoint = _endpoint(channel)
        candidates = [v for v in visits if endpoint and _endpoint(v['agent']) == endpoint
                      and v['answered'] is not None and v['answered'] <= transfer_time
                      and (v['ended'] is None or transfer_time <= v['ended'])]
        if len(candidates) == 1:
            # A matching linkedid alone is insufficient: require the source
            # endpoint and this visit's active interval as well. CEL proves
            # transfer, but not consultation duration or final hangup party.
            candidates[0].update(outcome='transferred', ended=transfer_time,
                                 talk_seconds=None, segment_ended_by=None)
    for visit in visits:
        if visit['ended'] is None and visit['coverage'] == 'observed':
            visit['coverage'] = 'missing_end'
        db.execute('INSERT INTO report_visits VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (pbx, visit['id'], callid, queue, *(visit[k] for k in (
                       'entered', 'answered', 'ended', 'caller', 'agent', 'outcome',
                       'wait_seconds', 'talk_seconds', 'segment_ended_by', 'coverage'))))


def project_batch(archive, *, limit=500):
    """Atomically advance a projection cursor; replay/restart is idempotent."""
    limit = max(1, min(1000, int(limit)))
    with archive.writer() as db:
        db.executescript(SCHEMA)
        db.execute('BEGIN IMMEDIATE')
        previous = db.execute('SELECT after_id FROM report_projection WHERE pbx=?', (archive.pbx,)).fetchone()
        after = previous[0] if previous else 0
        version = db.execute('SELECT version FROM report_projection_version WHERE pbx=?', (archive.pbx,)).fetchone()
        if not version or version[0] != PROJECTION_VERSION:
            # Replay derived facts incrementally after an algorithm upgrade;
            # raw evidence and import checkpoints remain untouched.
            after = 0
            db.execute('INSERT OR REPLACE INTO report_projection_version VALUES(?,?)',
                       (archive.pbx, PROJECTION_VERSION))
        events = db.execute('''SELECT id,source,source_key,ts,kind,payload FROM events
            WHERE pbx=? AND id>? ORDER BY id LIMIT ?''', (archive.pbx, after, limit)).fetchall()
        dirty = set()
        for event_id, source, key, ts, kind, payload in events:
            row = json.loads(payload)
            if source == 'cdr':
                values = (archive.pbx, key, event_id, ts, *(str(row.get(k) or '') for k in (
                    'uniqueid', 'linkedid', 'src', 'dst', 'channel', 'dstchannel')),
                          number(row.get('duration')), number(row.get('billsec')),
                          str(row.get('disposition') or ''), str(row.get('recordingfile') or ''))
                db.execute('''INSERT INTO report_cdr VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(pbx,source_key) DO UPDATE SET event_id=excluded.event_id,
                  ts=excluded.ts,uid=excluded.uid,linkedid=excluded.linkedid,src=excluded.src,
                  dst=excluded.dst,channel=excluded.channel,dstchannel=excluded.dstchannel,
                  duration=excluded.duration,billsec=excluded.billsec,
                  disposition=excluded.disposition,recording=excluded.recording''', values)
            elif source == 'cel' and kind.upper() in ('ATTENDEDTRANSFER', 'BLINDTRANSFER'):
                uid, linkedid = str(row.get('uniqueid') or ''), str(row.get('linkedid') or '')
                previous_transfer = db.execute('SELECT uid,linkedid FROM report_cel_transfers WHERE pbx=? AND source_key=?',
                                               (archive.pbx, key)).fetchone()
                identities = {uid, linkedid} - {''}
                if previous_transfer:
                    identities.update(value for value in previous_transfer if value)
                db.execute('''INSERT INTO report_cel_transfers VALUES(?,?,?,?,?,?,?)
                  ON CONFLICT(pbx,source_key) DO UPDATE SET uid=excluded.uid,
                  linkedid=excluded.linkedid,channel=excluded.channel,ts=excluded.ts,kind=excluded.kind''',
                           (archive.pbx, key, uid, linkedid, str(row.get('channame') or ''), ts, kind.upper()))
                for identity in identities:
                    dirty.update(db.execute('SELECT DISTINCT queue,callid FROM report_queue_events WHERE pbx=? AND callid=?',
                                            (archive.pbx, identity)).fetchall())
            elif source.startswith('queue_log') and row.get('queue') and row.get('callid'):
                queue, callid = str(row['queue']), str(row['callid'])
                if queue in ('NONE', 'ALL') or callid in ('NONE', 'REALTIME'):
                    continue
                db.execute('INSERT OR IGNORE INTO report_queue_events VALUES(?,?,?,?,?,?,?,?)',
                           (archive.pbx, event_id, callid, queue, str(row.get('agent') or ''), ts,
                            kind.upper(), json.dumps(row.get('values') or [], ensure_ascii=False)))
                dirty.add((queue, callid))
        for queue, callid in dirty:
            _rebuild_visits(db, archive.pbx, queue, callid)
        cursor = events[-1][0] if events else after
        db.execute('INSERT OR REPLACE INTO report_projection VALUES(?,?,?)', (archive.pbx, cursor, time.time()))
    return dict(processed=len(events), after_id=cursor)
