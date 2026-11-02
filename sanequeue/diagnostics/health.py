"""Read existing ingestion heartbeats; an idle phone system is not a failure."""
import json
import math
from sanequeue.reporting.store import Archive


def _status(value, now, maximum_age, fields, mode):
    result = dict(state='unavailable', reason='source_heartbeat_missing', mode=mode,
                  checked_at=None, age_seconds=None, caught_up=None)
    if not isinstance(value, dict):
        return result
    checked = value.get('checked')
    if isinstance(checked, bool) or not isinstance(checked, (int, float)) or not math.isfinite(checked) or checked < 0 or checked > now + 5:
        result.update(state='unknown', reason='invalid_source_clock')
        return result
    age = max(0, now - checked)
    result.update(checked_at=checked, age_seconds=round(age, 3))
    if age > maximum_age:
        result.update(state='stale', reason='source_heartbeat_stale')
    elif value.get('ok') is False:
        result.update(state='error', reason='source_read_failed')
    elif value.get('ok') is not True:
        result.update(state='unknown', reason='source_result_unknown')
    else:
        progress = value.get('progress')
        flags = [progress.get(name) for name in fields] if isinstance(progress, dict) else []
        if any(flag is False for flag in flags):
            result.update(state='catching_up', reason='source_backlog', caught_up=False)
        elif len(flags) != len(fields) or any(type(flag) is not bool for flag in flags):
            result.update(state='unknown', reason='source_coverage_unknown')
        else:
            caught_up = all(flags)
            result.update(state=('snapshot' if mode == 'snapshot' else 'current') if caught_up else 'catching_up',
                          reason='snapshot_not_live_coverage' if caught_up and mode == 'snapshot' else 'source_poll_current' if caught_up else 'source_backlog',
                          caught_up=caught_up)
    return result


def source_health(archive, *, now, maximum_age=120):
    """No AMI, PBX SQL, systemctl, event scan, schema writes or source probes."""
    if isinstance(now, bool) or not isinstance(now, (int, float)) or not math.isfinite(now) or now < 0:
        raise ValueError('invalid_diagnostics_clock')
    if isinstance(maximum_age, bool) or not isinstance(maximum_age, (int, float)) or not 15 <= maximum_age <= 3600:
        raise ValueError('invalid_health_age')
    bounded = Archive(archive.path, pbx=archive.pbx, read_seconds=min(1, archive.read_seconds))
    with bounded.reader() as db:
        raw = db.execute("SELECT source,CASE WHEN length(CAST(value AS BLOB))<=8192 THEN value END AS value FROM checkpoints WHERE pbx=? AND source IN (?,?,?,?)",
                         (archive.pbx, 'health:sql', 'health:cel', 'health:cdr', 'health:queue_log')).fetchall()
    checkpoints = {}
    for row in raw:
        if not isinstance(row['value'], str):
            continue
        try:
            checkpoints[row['source']] = json.loads(row['value'])
        except (ValueError, TypeError):
            continue
    sql = checkpoints.get('health:sql')
    sources = {}
    for source in ('cel', 'cdr'):
        snapshot=_status(checkpoints.get('health:'+source),now,maximum_age,('caught_up',),'snapshot')
        if sql is not None:
            fields = (source + '_caught_up',) if source == 'cel' else ('cdr_caught_up', 'cdr_overlap_caught_up')
            sources[source] = _status(sql, now, maximum_age, fields, 'local_sql_poll')
            if 'health:'+source in checkpoints:
                sources[source]['alternatives']={'snapshot':snapshot}
                if sources[source]['state']=='stale' and snapshot['state']=='snapshot':
                    sources[source].update(state='unknown',reason='source_selection_unknown')
        else:
            sources[source] = snapshot
    sources['queue_log'] = _status(checkpoints.get('health:queue_log'), now, maximum_age, ('caught_up',), 'local_log_tail')
    return dict(sources=sources, assessed_at=now, maximum_heartbeat_age_seconds=maximum_age,
                live_media_coverage='unavailable', signaling_capture='not_enabled_by_diagnostics',
                quiet_traffic_is_not_failure=True,
                contract='Heartbeat assesses importer polling, not packet delivery, speech, or root cause.')
