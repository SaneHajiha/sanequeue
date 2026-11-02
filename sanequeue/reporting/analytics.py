"""Scoped queue trends over local facts with explicit metric denominators.

All queries share one bounded read snapshot. Unknown evidence is never filled
with zero and percentile ranks use the nearest-rank definition.
"""
from datetime import datetime, timedelta
import json
import math
from zoneinfo import ZoneInfo

from .queries import _where
from .store import QueryDeadline


ZONE = ZoneInfo('Asia/Tehran')


def _bucket(timestamp, interval):
    local = datetime.fromtimestamp(timestamp, ZONE)
    if interval == 'hour':
        return local.strftime('%Y-%m-%d %H:00')
    if interval == 'day':
        return local.date().isoformat()
    if interval == 'week':
        # Operational weeks start on Saturday, independent of UI language.
        return (local.date() - timedelta(days=(local.weekday()+2) % 7)).isoformat()
    return local.strftime('%Y-%m')


def dashboard(archive, scope, start, end, *, interval='day', sla_seconds=20,
              sla_basis='answered_known_wait', short_abandon_seconds=0, compare=False):
    if interval not in ('hour', 'day', 'week', 'month'):
        raise ValueError('invalid_report_interval')
    if sla_basis not in ('answered_known_wait', 'offered_known_wait'):
        raise ValueError('invalid_sla_basis')
    sla_seconds, short_abandon_seconds = float(sla_seconds), float(short_abandon_seconds)
    if (not all(math.isfinite(n) for n in (sla_seconds, short_abandon_seconds))
            or not 1 <= sla_seconds <= 3600 or not 0 <= short_abandon_seconds <= 3600):
        raise ValueError('invalid_metric_policy')
    clause, args = _where(archive.pbx, scope, start, end)
    # A known entry is required for offered metrics; orphaned completions are
    # still visible as incomplete evidence, never invented queue arrivals.
    measures = '''COUNT(*) visits,
      SUM(answered IS NOT NULL OR outcome='answered') answered,
      SUM(outcome='abandoned') abandoned,
      SUM(outcome='transferred') transferred,
      SUM(coverage<>'observed') incomplete,
      SUM(outcome IN ('waiting','connected','reentered_without_end')) unfinished,
      SUM(coverage<>'missing_entry') known_entries,
      SUM(coverage<>'missing_entry' AND outcome='abandoned') known_entry_abandoned,
      SUM(wait_seconds IS NULL) unknown_wait,
      SUM(outcome='abandoned' AND wait_seconds IS NOT NULL AND wait_seconds<?) short_abandoned,
      SUM((answered IS NOT NULL OR outcome='answered') AND wait_seconds IS NOT NULL) answered_known_wait,
      SUM((answered IS NOT NULL OR outcome='answered') AND wait_seconds<=?) sla_met,
      SUM(coverage<>'missing_entry' AND (answered IS NOT NULL OR outcome='answered') AND wait_seconds<=?) offered_sla_met,
      SUM(coverage<>'missing_entry' AND wait_seconds IS NOT NULL
          AND NOT(outcome='abandoned' AND wait_seconds<?)) offered_known_wait,
      COUNT(wait_seconds) known_wait_count,AVG(wait_seconds) average_wait_seconds,
      MAX(wait_seconds) longest_wait_seconds,
      AVG(CASE WHEN answered IS NOT NULL OR outcome='answered' THEN wait_seconds END) asa_seconds,
      COUNT(talk_seconds) known_talk_count,SUM(talk_seconds) talk_seconds,
      AVG(talk_seconds) average_talk_seconds'''

    def finish(row):
        row = dict(row)
        for key in ('answered', 'abandoned', 'transferred', 'incomplete', 'unfinished', 'known_entries',
                    'known_entry_abandoned', 'unknown_wait', 'short_abandoned', 'answered_known_wait',
                    'sla_met', 'offered_sla_met', 'offered_known_wait'):
            row[key] = row[key] or 0
        denominator = row[sla_basis]
        row['sla_denominator'] = denominator
        numerator = row['sla_met'] if sla_basis == 'answered_known_wait' else row['offered_sla_met']
        row['sla_numerator'] = numerator
        row['sla_percent'] = 100*numerator/denominator if denominator else None
        row['abandon_percent'] = 100*row['known_entry_abandoned']/row['known_entries'] if row['known_entries'] else None
        return row

    metric_args = (short_abandon_seconds, sla_seconds, sla_seconds, short_abandon_seconds)
    with archive.reader() as db:
        projection = db.execute('SELECT after_id,updated FROM report_projection WHERE pbx=?', (archive.pbx,)).fetchone()
        sources = {}
        for source in ('queue_log', 'sql'):
            stored = db.execute('SELECT value FROM checkpoints WHERE pbx=? AND source=?',
                                (archive.pbx, 'health:'+source)).fetchone()
            health = json.loads(stored[0]) if stored else {}
            sources[source] = {key: health.get(key) for key in ('ok', 'checked')}
        db.create_function('report_bucket', 1, lambda ts: _bucket(ts, interval), deterministic=True)
        db.create_function('report_weekday', 1, lambda ts: (datetime.fromtimestamp(ts, ZONE).weekday()+2) % 7,
                           deterministic=True)
        db.create_function('report_hour', 1, lambda ts: datetime.fromtimestamp(ts, ZONE).hour, deterministic=True)
        totals = finish(db.execute('SELECT '+measures+' FROM report_visits WHERE '+clause,
                                   (*metric_args, *args)).fetchone())
        trends = [finish(row) for row in db.execute('SELECT report_bucket(entered) bucket,'+measures+
                  ' FROM report_visits WHERE '+clause+' GROUP BY bucket ORDER BY bucket LIMIT 1001',
                  (*metric_args, *args))]
        if len(trends) > 1000:
            raise QueryDeadline('trend_bucket_limit_use_coarser_interval')
        queue_rows = [finish(row) for row in db.execute('SELECT queue,'+measures+
                      ' FROM report_visits WHERE '+clause+' GROUP BY queue ORDER BY queue', (*metric_args, *args))]
        quantiles = {row['queue']: dict(row) for row in db.execute('''WITH ranked AS (
          SELECT queue,wait_seconds,ROW_NUMBER() OVER(PARTITION BY queue ORDER BY wait_seconds) rank,
          COUNT(*) OVER(PARTITION BY queue) count FROM report_visits WHERE '''+clause+''' AND wait_seconds IS NOT NULL)
          SELECT queue,MAX(count) samples,
          MAX(CASE WHEN rank=CAST((count+1)/2 AS INTEGER) THEN wait_seconds END) p50_seconds,
          MAX(CASE WHEN rank=CAST((count*90+99)/100 AS INTEGER) THEN wait_seconds END) p90_seconds,
          MAX(CASE WHEN rank=CAST((count*95+99)/100 AS INTEGER) THEN wait_seconds END) p95_seconds
          FROM ranked GROUP BY queue''', args)}
        for row in queue_rows:
            row['wait_percentiles'] = quantiles.get(row['queue'])
        heatmap = [dict(row) for row in db.execute('''SELECT report_weekday(entered) weekday,
          report_hour(entered) hour,COUNT(*) visits,SUM(outcome='abandoned') abandoned
          FROM report_visits WHERE '''+clause+' GROUP BY weekday,hour ORDER BY weekday,hour', args)]
        previous = None
        if compare:
            previous_start = max(0, float(start)-(float(end)-float(start)))
            if previous_start < float(start):
                old_clause, old_args = _where(archive.pbx, scope, previous_start, float(start))
                previous = dict(start=previous_start, end=float(start), metrics=finish(db.execute(
                    'SELECT '+measures+' FROM report_visits WHERE '+old_clause, (*metric_args, *old_args)).fetchone()))
    return dict(start=float(start), end=float(end), timezone='Asia/Tehran', interval=interval,
                unit='queue_visit', totals=totals, queues=queue_rows, trends=trends, heatmap=heatmap,
                previous=previous, policy=dict(sla_seconds=sla_seconds, sla_basis=sla_basis,
                short_abandon_seconds=short_abandon_seconds, percentile='nearest_rank',
                range_basis='queue_entry', week_starts='Saturday',
                offered_denominator='known_entry_and_known_wait_excluding_short_abandon',
                aht=None, aht_reason='hold_and_after_call_work_not_fully_correlated'),
                projection=dict(projection) if projection else None, sources=sources,
                effective_start=max(float(start), scope.not_before))
