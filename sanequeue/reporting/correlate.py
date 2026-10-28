"""Project explicit channel relations without guessing conversation membership.

Edges preserve provenance. Sharing a bridge or linkedid is not an instruction
to merge consultations, conferences and customers into one flat call.
"""
import json
import re


def project(db, pbx, event_id, event):
    row = {str(k).lower(): v for k, v in event.payload.items()}
    uid = str(row.get('uniqueid') or '')
    channel = str(row.get('channame') or row.get('channel') or '')
    linked = str(row.get('linkedid') or '')
    kind = event.kind.upper()
    if event.source.startswith('queue_log') and kind=='CONNECT':
        values=row.get('values');caller=row.get('callid');queue=row.get('queue');agent=row.get('agent')
        peer=values[1] if isinstance(values,list) and len(values)>1 else None
        valid=lambda value,maximum:isinstance(value,str) and 0<len(value)<=maximum and value.isprintable() and value not in ('NONE','<unknown>','REALTIME')
        if valid(caller,512) and valid(peer,512) and caller!=peer and valid(queue,128) and valid(agent,256):
            db.execute('INSERT OR IGNORE INTO evidence_edges VALUES(?,?,?,?,?,?,?,?,?)',
                (pbx,event_id,'queue_connect_peer','uniqueid',caller,'uniqueid',peer,event.timestamp,
                 json.dumps(dict(queue=queue,agent=agent),ensure_ascii=False,sort_keys=True)))
        return
    if uid and uid not in ('NONE', '<unknown>'):
        started = event.timestamp if kind in ('CHAN_START', 'CDR') else None
        answered = event.timestamp if kind == 'ANSWER' else None
        ended = event.timestamp if kind in ('HANGUP', 'CHAN_END') else None
        db.execute('''INSERT INTO legs VALUES(?,?,?,?,?,?,?) ON CONFLICT(pbx,uid) DO UPDATE SET
          channel=CASE WHEN excluded.channel<>'' THEN excluded.channel ELSE legs.channel END,
          linkedid=CASE WHEN excluded.linkedid<>'' THEN excluded.linkedid ELSE legs.linkedid END,
          started=CASE WHEN legs.started IS NULL THEN excluded.started WHEN excluded.started IS NULL THEN legs.started ELSE MIN(legs.started,excluded.started) END,
          answered=CASE WHEN legs.answered IS NULL THEN excluded.answered WHEN excluded.answered IS NULL THEN legs.answered ELSE MIN(legs.answered,excluded.answered) END,
          ended=CASE WHEN legs.ended IS NULL THEN excluded.ended WHEN excluded.ended IS NULL THEN legs.ended ELSE MAX(legs.ended,excluded.ended) END''',
                   (pbx, uid, channel, linked, started, answered, ended))

    def edge(relation, target_kind, target, details=None):
        if not uid or not target or str(target) == uid:
            return
        db.execute('INSERT OR IGNORE INTO evidence_edges VALUES(?,?,?,?,?,?,?,?,?)',
                   (pbx, event_id, relation, 'uniqueid', uid, target_kind, str(target), event.timestamp,
                    json.dumps(details or {}, ensure_ascii=False, sort_keys=True)))

    if linked:
        edge('linkedid_membership', 'linkedid', linked)
    extra = row.get('eventextra') or row.get('extra') or {}
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except (ValueError, TypeError):
            extra = {}
    if not isinstance(extra, dict):
        extra = {}
    if kind in ('LOCAL_OPTIMIZE', 'LOCAL_OPTIMIZE_BEGIN'):
        edge(kind.lower(), 'channel', extra.get('local_two'), {'primary_channel': channel})
    if kind=='LOCAL_OPTIMIZE_END':
        # Only an explicitly named, valid Local half supplies a relation.
        # Optimization completion itself does not establish ownership, final
        # hangup causality or the identity of an inferred replacement channel.
        target=extra.get('local_two')
        if (isinstance(target,str) and len(target)<=512 and target!=channel
            and re.fullmatch(r'Local/[A-Za-z0-9_.+@/-]+;[12]',target)):
            edge('local_optimize_end','channel',target,{'primary_channel':channel})
    if kind in ('BRIDGE_ENTER', 'BRIDGE_EXIT'):
        edge(kind.lower(), 'bridge', extra.get('bridge_id'))
    if kind in ('ATTENDEDTRANSFER', 'BLINDTRANSFER'):
        # CEL channel2_name is the second initiating channel, not the transfer
        # target (notably in bridge-app transfers). Rebuild only this event's
        # transfer projections so bounded replay also removes legacy fallback.
        db.execute('DELETE FROM evidence_edges WHERE pbx=? AND event_id=? AND relation IN (?,?,?)',
            (pbx,event_id,'attendedtransfer','blindtransfer','transfer_second_channel'))
        db.execute('DELETE FROM transfers WHERE pbx=? AND event_id=?',(pbx,event_id))
        target=extra.get('transfer_target_channel_name')
        target=target if isinstance(target,str) else ''
        if target:
            edge(kind.lower(), 'channel', target, extra)
        elif kind=='BLINDTRANSFER':
            # A dialplan destination is not the identity of an answered peer.
            context,extension=extra.get('context'),extra.get('extension')
            if isinstance(context,str) and context and isinstance(extension,str) and extension:
                target=context+'/'+extension
                edge(kind.lower(), 'destination', target, extra)
        if kind=='ATTENDEDTRANSFER' and isinstance(extra.get('channel2_name'),str):
            edge('transfer_second_channel','channel',extra['channel2_name'])
        db.execute('''INSERT OR IGNORE INTO transfers(pbx,event_id,transfer_type,from_uid,target,
                   consultation_started,consultation_ended,consultation_duration,handoff_at)
                   VALUES(?,?,?,?,?,NULL,NULL,NULL,?)''',
                   (pbx, event_id, 'attended' if kind == 'ATTENDEDTRANSFER' else 'blind', uid, target or '', event.timestamp))


def relations(archive, uid, *, limit=100):
    with archive.reader() as db:
        return [dict(r) for r in db.execute('''SELECT relation,to_kind,to_id,ts,details FROM evidence_edges
          WHERE pbx=? AND from_kind='uniqueid' AND from_id=? ORDER BY ts,event_id LIMIT ?''',
                                           (archive.pbx, str(uid), max(1, min(500, limit))))]
