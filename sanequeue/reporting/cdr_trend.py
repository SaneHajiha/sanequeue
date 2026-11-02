"""Bounded time buckets for observed PBX CDR segments, not unique calls."""
from datetime import datetime, timedelta

from . import cdr_queries
from .store import QueryDeadline
from .exports import persian_date

MAX_SEGMENTS = 50000
MAX_BUCKETS = 1000
_DIRECTIONS = ('inbound', 'outbound', 'internal', 'unknown')


def report(archive, start, end, filters=None, *, bucket='day', calendar='gregorian'):
    if bucket not in ('hour', 'day', 'week', 'month'):
        raise ValueError('invalid_cdr_trend_bucket')
    if calendar not in ('persian','gregorian'):
        raise ValueError('invalid_cdr_trend_calendar')
    clause, args, clean = cdr_queries._where(archive, start, end, filters)
    with archive.reader() as db:
        cdr_queries._functions(db)
        rows = db.execute('SELECT c.ts,' + cdr_queries._DIRECTION + ' direction ' +
                          cdr_queries._JOIN + ' WHERE ' + clause + ' LIMIT ?',
                          (*args, MAX_SEGMENTS + 1)).fetchall()
    if len(rows) > MAX_SEGMENTS:
        raise QueryDeadline('cdr_trend_segment_limit')
    groups = {}
    for row in rows:
        local = datetime.fromtimestamp(row['ts'], cdr_queries._ZONE)
        if bucket == 'hour':
            key = local.strftime('%Y-%m-%d %H:00')
        elif bucket == 'day':
            key = local.date().isoformat()
        elif bucket == 'week':
            key = (local.date() - timedelta(days=(local.weekday() + 2) % 7)).isoformat()
        else:
            if calendar=='persian' and not 1900<=local.year<=2099:
                raise ValueError('invalid_cdr_trend_calendar_range')
            key = persian_date(local.date())[:7] if calendar=='persian' else local.strftime('%Y-%m')
        if key not in groups:
            if len(groups) >= MAX_BUCKETS:
                raise QueryDeadline('cdr_trend_bucket_limit')
            groups[key] = dict.fromkeys(_DIRECTIONS, 0)
        direction = row['direction'] if row['direction'] in _DIRECTIONS else 'unknown'
        groups[key][direction] += 1
    return dict(bucket=bucket, start=float(start), end=float(end), filters=clean,
                unit='cdr_segment', scope='global_pbx', complete_history=False,
                timezone='Asia/Tehran', month_calendar=calendar, week_starts='Saturday',
                rows=[dict(period=key, **groups[key]) for key in sorted(groups)])
