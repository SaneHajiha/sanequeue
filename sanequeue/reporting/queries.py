"""Read-only, scoped queries over local facts. No source imports or AMI here."""
from dataclasses import dataclass
import math
from .facts import _endpoint


@dataclass(frozen=True)
class Scope:
    queues: tuple
    agents: tuple = ()
    self_only: bool = False
    not_before: float = 0


def _where(pbx, scope, start, end):
    start, end = float(start), float(end)
    if not all(math.isfinite(n) for n in (start, end)) or start < 0 or end <= start or end - start > 366 * 86400:
        raise ValueError('invalid_report_range')
    if len(scope.queues) > 256 or len(scope.agents) > 64:
        raise ValueError('report_scope_limit')
    queues = tuple(dict.fromkeys(scope.queues))
    clause = 'pbx=? AND entered>=? AND entered<?'
    args = [pbx, max(start, scope.not_before), end]
    if not queues:
        return clause + ' AND 0', args
    clause += ' AND queue IN (' + ','.join('?' for _ in queues) + ')'
    args.extend(queues)
    if scope.self_only:
        if not scope.agents:
            return clause + ' AND 0', args
        clause += ' AND agent IN (' + ','.join('?' for _ in scope.agents) + ')'
        args.extend(scope.agents)
    return clause, args


def queues(archive):
    with archive.reader() as db:
        return [r[0] for r in db.execute('SELECT DISTINCT queue FROM report_visits WHERE pbx=? ORDER BY queue LIMIT 257', (archive.pbx,))]


def overview(archive, scope, start, end, *, sla_seconds=20):
    sla_seconds = float(sla_seconds)
    if not math.isfinite(sla_seconds) or not 1 <= sla_seconds <= 3600:
        raise ValueError('invalid_sla_seconds')
    clause, args = _where(archive.pbx, scope, start, end)
    with archive.reader() as db:
        rows = [dict(r) for r in db.execute('''SELECT queue,COUNT(*) visits,
          SUM(answered IS NOT NULL OR outcome='answered') answered,
          SUM(outcome='abandoned') abandoned,SUM(outcome='transferred') transferred,
          SUM(coverage<>'observed') incomplete,
          MIN(entered) first_entry,MAX(COALESCE(ended,answered,entered)) last_evidence,
          AVG(wait_seconds) average_wait_seconds,AVG(talk_seconds) average_talk_seconds,
          SUM((answered IS NOT NULL OR outcome='answered') AND wait_seconds IS NOT NULL) sla_known,
          SUM((answered IS NOT NULL OR outcome='answered') AND wait_seconds<=?) sla_met
          FROM report_visits WHERE ''' + clause + ' GROUP BY queue ORDER BY queue', (sla_seconds, *args))]
        projection = db.execute('SELECT after_id,updated FROM report_projection WHERE pbx=?', (archive.pbx,)).fetchone()
    for row in rows:
        # Explicit answered-call denominator. This is not Asterisk's live SLA
        # denominator, which depends on queue configuration and exclusions.
        row['sla_percent'] = 100 * row['sla_met'] / row['sla_known'] if row['sla_known'] else None
    return dict(start=float(start), end=float(end), queues=rows,
                sla_seconds=sla_seconds, sla_definition='answered_with_known_wait',
                unit='queue_visit', projection=dict(projection) if projection else None,
                retention='no_automatic_deletion')


def visits(archive, scope, start, end, *, before=None, limit=100, queue=None, outcome=None):
    clause, args = _where(archive.pbx, scope, start, end)
    if queue:
        clause += ' AND queue=?'
        args.append(str(queue))
    if outcome:
        if outcome not in ('answered', 'abandoned', 'waiting', 'connected', 'transferred',
                           'exitwithtimeout', 'exitempty', 'exitwithkey', 'unknown', 'reentered_without_end'):
            raise ValueError('invalid_report_outcome')
        clause += ' AND outcome=?'
        args.append(outcome)
    if before:
        stamp, ident = float(before[0]), str(before[1])
        if not math.isfinite(stamp) or len(ident) != 64:
            raise ValueError('invalid_report_cursor')
        clause += ' AND (entered<? OR (entered=? AND id<?))'
        args.extend((stamp, stamp, ident))
    limit = max(1, min(200, int(limit)))
    with archive.reader() as db:
        rows = [dict(r) for r in db.execute('SELECT * FROM report_visits WHERE ' + clause +
                                           ' ORDER BY entered DESC,id DESC LIMIT ?', (*args, limit + 1))]
    more = len(rows) > limit
    rows = rows[:limit]
    return dict(rows=rows, next=[rows[-1]['entered'], rows[-1]['id']] if rows and more else None)


def detail(archive, scope, start, end, visit_id):
    clause, args = _where(archive.pbx, scope, start, end)
    with archive.reader() as db:
        row = db.execute('SELECT * FROM report_visits WHERE ' + clause + ' AND id=?', (*args, visit_id)).fetchone()
        if row is None:
            return None
        row = dict(row)
        # Return typed fields, never the raw ENTERQUEUE payload/caller number.
        events = [dict(r) for r in db.execute('''SELECT ts,kind,agent FROM report_queue_events
          WHERE pbx=? AND queue=? AND callid=? AND ts>=? AND (? IS NULL OR ts<=?)
          ORDER BY ts,event_id LIMIT 1000''', (archive.pbx, row['queue'], row['callid'],
                                             row['entered'], row['ended'], row['ended']))]
        if row['outcome'] == 'transferred':
            proofs = db.execute('''SELECT ts,kind,channel FROM report_cel_transfers
              WHERE pbx=? AND (uid=? OR linkedid=?) AND ts=? LIMIT 1001''',
                                (archive.pbx, row['callid'], row['callid'], row['ended'])).fetchall()
            for proof in proofs:
                if _endpoint(row['agent']) and _endpoint(proof['channel']) == _endpoint(row['agent']):
                    events.append(dict(ts=proof['ts'], kind=proof['kind'], agent=row['agent'], source='cel'))
            events.sort(key=lambda event: event['ts'])
        recording_rows = [dict(r) for r in db.execute('''SELECT source_key id,ts,uid,linkedid,billsec,
          disposition,recording FROM report_cdr WHERE pbx=? AND (uid=? OR linkedid=?) AND recording<>''
          ORDER BY ts,source_key LIMIT 100''', (archive.pbx, row['callid'], row['callid']))]
        # Several CDR legs can reference the same MixMonitor file. Keep one
        # authorized opaque reference, without exposing private storage paths.
        recordings, seen = [], set()
        for recording in recording_rows:
            reference = recording.pop('recording')
            if reference not in seen:
                seen.add(reference)
                recordings.append(recording)
    return dict(visit=row, timeline=events, recordings=recordings,
                hangup_evidence='queue_segment_only' if row['segment_ended_by'] else 'unknown',
                final_conversation_ended_by=None)


def agents(archive, scope, start, end):
    clause, args = _where(archive.pbx, scope, start, end)
    with archive.reader() as db:
        rows = [dict(r) for r in db.execute('''SELECT queue,agent,
          SUM(answered IS NOT NULL OR outcome='answered') answered,
          SUM(outcome='transferred') transferred,
          AVG(talk_seconds) average_talk_seconds,AVG(wait_seconds) average_wait_seconds,
          SUM(talk_seconds) talk_seconds,
          SUM(segment_ended_by='caller') caller_segment_hangup,
          SUM(segment_ended_by='agent') agent_segment_hangup,
          SUM(segment_ended_by IS NULL) unknown_segment_hangup,
          MIN(entered) first_visit,MAX(ended) last_end
          FROM report_visits WHERE ''' + clause + " AND agent<>'' AND agent<>'NONE' GROUP BY queue,agent ORDER BY queue,agent LIMIT 501", args)]
    return dict(rows=rows[:500], limited=len(rows)>500, unit='agent_queue_segment',
                work_time_source='collector_intervals_required', final_hangup_source='separate_conversation_evidence_required')
