"""Incremental, rebuildable reporting facts; raw evidence remains authoritative.

Run in a worker, never during an HTTP request. A queue visit is a queue entry,
not a CDR row or a unique customer conversation. Missing evidence stays NULL.
"""
import hashlib
import json
import math
import re
import time
import os
import unicodedata
from .identity import parties, canonical
from .snapshot_schema import SCHEMA as SNAPSHOT_SCHEMA, bootstrap as bootstrap_snapshots
from sanequeue.realtime.local_inventory import read_snapshot


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
CREATE INDEX IF NOT EXISTS rv_queue_ended ON report_visits(pbx,queue,ended,entered) WHERE ended IS NOT NULL;
CREATE INDEX IF NOT EXISTS rv_queue_open ON report_visits(pbx,queue,entered) WHERE ended IS NULL;
CREATE INDEX IF NOT EXISTS rv_call ON report_visits(pbx,callid);
CREATE INDEX IF NOT EXISTS rv_caller_time ON report_visits(pbx,caller,entered,id);
CREATE TABLE IF NOT EXISTS report_cdr(
 pbx TEXT,source_key TEXT,event_id INTEGER,ts REAL,uid TEXT,linkedid TEXT,
 src TEXT,dst TEXT,channel TEXT,dstchannel TEXT,duration REAL,billsec REAL,
 disposition TEXT,recording TEXT,PRIMARY KEY(pbx,source_key));
CREATE INDEX IF NOT EXISTS rc_time ON report_cdr(pbx,ts,source_key);
CREATE INDEX IF NOT EXISTS rc_uid ON report_cdr(pbx,uid);
CREATE INDEX IF NOT EXISTS rc_linked ON report_cdr(pbx,linkedid);
CREATE TABLE IF NOT EXISTS report_cdr_extra(
 pbx TEXT,event_id INTEGER,source_key TEXT,source_channel TEXT,destination_channel TEXT,
 internal_caller_ext TEXT,outbound_cid TEXT,outbound_cid_source TEXT,did TEXT,trunk TEXT,
 trunk_provenance TEXT,inventory_observed REAL,PRIMARY KEY(pbx,event_id));
CREATE INDEX IF NOT EXISTS rce_source ON report_cdr_extra(pbx,source_key,event_id);
CREATE TABLE IF NOT EXISTS report_recording_refs(pbx TEXT,source_key TEXT,basename TEXT,
 PRIMARY KEY(pbx,source_key));
CREATE INDEX IF NOT EXISTS rrf_name ON report_recording_refs(pbx,basename);
CREATE TABLE IF NOT EXISTS report_identity_evidence(
 pbx TEXT,event_id INTEGER,agent TEXT,direction TEXT,inventory_observed REAL,
 provenance TEXT NOT NULL,PRIMARY KEY(pbx,event_id));
CREATE TABLE IF NOT EXISTS report_cel_transfers(
 pbx TEXT,source_key TEXT,uid TEXT,linkedid TEXT,channel TEXT,ts REAL,kind TEXT,
 PRIMARY KEY(pbx,source_key));
CREATE INDEX IF NOT EXISTS rct_link ON report_cel_transfers(pbx,linkedid,ts);
CREATE INDEX IF NOT EXISTS rct_uid ON report_cel_transfers(pbx,uid,ts);
CREATE TABLE IF NOT EXISTS report_cel_events(
 pbx TEXT,source_key TEXT,event_id INTEGER,uid TEXT,ts REAL,
 PRIMARY KEY(pbx,source_key));
CREATE INDEX IF NOT EXISTS rce_uid_time ON report_cel_events(pbx,uid,ts,event_id);
CREATE TABLE IF NOT EXISTS report_activity(
 pbx TEXT,source_key TEXT,event_id INTEGER,queue TEXT,agent TEXT,state TEXT,reason TEXT,
 starts REAL,ends REAL,on_duty INTEGER,coverage TEXT,canonical_agent TEXT,PRIMARY KEY(pbx,source_key));
CREATE INDEX IF NOT EXISTS ra_queue ON report_activity(pbx,queue,starts);
CREATE INDEX IF NOT EXISTS ra_queue_ended ON report_activity(pbx,queue,ends,starts) WHERE ends IS NOT NULL;
CREATE INDEX IF NOT EXISTS ra_queue_open ON report_activity(pbx,queue,starts) WHERE ends IS NULL;
CREATE INDEX IF NOT EXISTS ra_agent ON report_activity(pbx,agent,starts);
CREATE TABLE IF NOT EXISTS report_cdr_parties(
 pbx TEXT,source_key TEXT,agent TEXT,direction TEXT,inventory_observed REAL,
 PRIMARY KEY(pbx,source_key));
'''
PROJECTION_VERSION = 9


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) and 0 <= result <= 315360000 else None
    except (ValueError, TypeError):
        return None


def _cdr_number(value):
    """Normalize an explicit numeric source field, never infer it from src."""
    value=str(value if value is not None else '').strip()
    match=re.fullmatch(r'[^<>]*<([^<>]+)>',value)
    if match:value=match.group(1)
    value=''.join(str(unicodedata.digit(char)) if char.isdecimal() else char for char in value)
    value=re.sub(r'[\s().-]','',value)
    return value if re.fullmatch(r'\+?[0-9]{1,24}',value) else None


def _cdr_extra(db,pbx,event_id,key,row,evidence,inventory):
    if db.execute('SELECT 1 FROM report_cdr_extra WHERE pbx=? AND event_id=?',(pbx,event_id)).fetchone():return
    source=str(row.get('channel') or '');destination=str(row.get('dstchannel') or '')
    prior=db.execute('''SELECT source_channel,destination_channel,trunk,trunk_provenance,inventory_observed
      FROM report_cdr_extra WHERE pbx=? AND source_key=? AND event_id<? ORDER BY event_id DESC LIMIT 1''',
      (pbx,key,event_id)).fetchone()
    # Never apply a newer inventory epoch to an older frozen identity proof.
    verified=bool(inventory and inventory.get('observed_at') is not None and evidence[2]==inventory.get('observed_at'))
    endpoints={item['technology']+'/'+item['endpoint']:item['category'] for item in (inventory or {}).get('endpoints',[]) if verified}
    def trunk(channel):
        if endpoints.get(channel)=='trunk':return channel
        base,separator,suffix=channel.rpartition('-')
        return base if separator and re.fullmatch('[0-9a-fA-F]+',suffix) and endpoints.get(base)=='trunk' else None
    trunks={value for value in (trunk(source),trunk(destination)) if value}
    selected=next(iter(trunks)) if len(trunks)==1 else None
    provenance=('first_projection_inventory' if selected else 'ambiguous_trunk_pair' if len(trunks)>1
                else 'no_known_trunk' if verified else 'inventory_epoch_mismatch' if inventory else 'inventory_unavailable')
    observed=(inventory or {}).get('observed_at')
    if prior and (source,destination)==tuple(prior[:2]):selected,provenance,observed=prior[2:]
    origin=evidence[0].split('/',1)[1] if evidence[1] in ('outbound','internal') and evidence[0].startswith(('SIP/','PJSIP/')) else None
    cid_source=next((field for field in ('outbound_cnum','outbound_cid') if row.get(field) not in (None,'')),None)
    db.execute('INSERT INTO report_cdr_extra VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
      (pbx,event_id,key,source,destination,origin,_cdr_number(row.get(cid_source)) if cid_source else None,
       cid_source,_cdr_number(row.get('did')),selected,provenance,observed))


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
    existing = {row[1]:tuple(row) for row in db.execute(
        'SELECT * FROM report_visits WHERE pbx=? AND queue=? AND callid=?', (pbx,queue,callid))}
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
        values = (pbx, visit['id'], callid, queue, *(visit[k] for k in (
                       'entered', 'answered', 'ended', 'caller', 'agent', 'outcome',
                       'wait_seconds', 'talk_seconds', 'segment_ended_by', 'coverage')))
        if existing.get(visit['id']) != values:
            db.execute('INSERT OR REPLACE INTO report_visits VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)', values)
        existing.pop(visit['id'], None)
    for ident in existing:
        db.execute('DELETE FROM report_visits WHERE pbx=? AND id=?', (pbx,ident))


def project_batch(archive, *, limit=500, inventory=None):
    """Atomically advance a projection cursor; replay/restart is idempotent."""
    limit = max(1, min(1000, int(limit)))
    if inventory is None:
        inventory=read_snapshot(os.getenv('SANEQUEUE_LOCAL_INVENTORY','/run/sanequeue/inventory.json'))
    with archive.writer() as db:
        db.executescript(SCHEMA+SNAPSHOT_SCHEMA)
        db.execute('BEGIN IMMEDIATE')
        columns = {row[1] for row in db.execute('PRAGMA table_info(report_activity)')}
        if 'canonical_agent' not in columns:
            db.execute('ALTER TABLE report_activity ADD COLUMN canonical_agent TEXT')
            db.execute('UPDATE report_activity SET canonical_agent=agent')
        db.execute('CREATE INDEX IF NOT EXISTS ra_canonical ON report_activity(pbx,canonical_agent,starts)')
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
            if source=='cel':
                uid=row.get('uniqueid')
                if not isinstance(uid,str) or not 0<len(uid)<=512 or not uid.isprintable():uid=''
                db.execute('''INSERT INTO report_cel_events VALUES(?,?,?,?,?)
                  ON CONFLICT(pbx,source_key) DO UPDATE SET event_id=excluded.event_id,
                  uid=excluded.uid,ts=excluded.ts''',(archive.pbx,key,event_id,uid,ts))
            if source in ('activity','cdr'):
                evidence=db.execute('SELECT agent,direction,inventory_observed FROM report_identity_evidence WHERE pbx=? AND event_id=?',
                                    (archive.pbx,event_id)).fetchone()
                if evidence is None:
                    prior=db.execute('''SELECT e.payload,i.agent,i.direction,i.inventory_observed
                      FROM events e JOIN report_identity_evidence i ON i.pbx=e.pbx AND i.event_id=e.id
                      WHERE e.pbx=? AND e.source=? AND e.source_key=? AND e.id<? ORDER BY e.id DESC LIMIT 1''',
                      (archive.pbx,source,key,event_id)).fetchone()
                    identity_fields=('channel','dstchannel') if source=='cdr' else ('agent','canonical_agent')
                    unchanged=prior is not None and all(json.loads(prior[0]).get(field)==row.get(field) for field in identity_fields)
                    if source=='cdr':
                        identity=parties(str(row.get('channel') or ''),str(row.get('dstchannel') or ''),inventory)
                    else:
                        identity=dict(agent=row.get('canonical_agent') or canonical(row['agent'],inventory),
                                      direction='',inventory_observed=(inventory or {}).get('observed_at'))
                    # Legacy imports have no historical inventory. Freeze the
                    # first projection's evidence explicitly, never silently
                    # reinterpret it on rebuild with today's inventory.
                    provenance='source_canonical' if source=='activity' and row.get('canonical_agent') else 'first_projection_inventory'
                    evidence=(identity['agent'],identity['direction'],identity['inventory_observed'])
                    if unchanged:
                        evidence=tuple(prior[1:])
                        provenance='prior_identity_evidence'
                    db.execute('INSERT INTO report_identity_evidence VALUES(?,?,?,?,?,?)',
                               (archive.pbx,event_id,*evidence,provenance))
            if source == 'activity':
                db.execute('''INSERT INTO report_activity VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(pbx,source_key) DO UPDATE SET event_id=excluded.event_id,
                  queue=excluded.queue,agent=excluded.agent,state=excluded.state,reason=excluded.reason,
                  starts=excluded.starts,ends=excluded.ends,on_duty=excluded.on_duty,coverage=excluded.coverage,
                  canonical_agent=excluded.canonical_agent''',
                           (archive.pbx,key,event_id,row['queue'],row['agent'],row['state'],row['reason'],
                            row['starts'],row['ends'],int(row['on_duty']),row.get('coverage','observed'),evidence[0]))
            elif source == 'cdr':
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
                db.execute('INSERT OR REPLACE INTO report_cdr_parties VALUES(?,?,?,?,?)',
                           (archive.pbx,key,*evidence))
                _cdr_extra(db,archive.pbx,event_id,key,row,evidence,inventory)
                from pathlib import PurePosixPath
                db.execute('INSERT OR REPLACE INTO report_recording_refs VALUES(?,?,?)',
                           (archive.pbx,key,PurePosixPath(values[-1]).name if values[-1] else ''))
            elif source == 'cel' and kind.upper() in ('ATTENDEDTRANSFER', 'BLINDTRANSFER'):
                from .correlate import project as project_relations
                from .store import Event
                project_relations(db,archive.pbx,event_id,Event(source,key,ts,kind,row))
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
                if kind.upper()=='CONNECT':
                    from .correlate import project as project_relations
                    from .store import Event
                    project_relations(db,archive.pbx,event_id,Event(source,key,ts,kind,row))
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
        bootstrap_snapshots(db, archive.pbx, limit=limit)
    return dict(processed=len(events), after_id=cursor)
