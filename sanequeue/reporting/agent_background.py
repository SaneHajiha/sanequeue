"""Operator-only bounded agent aggregation over a verified sealed backup.

Not an HTTP fallback: live visit snapshots do not freeze activity identity.
Input must be an archive-backup bundle. Output and work storage are private and
new. Membership intervals are unioned across queues, never added as person time.
"""
import argparse
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import time

from . import backup
from .agent_rankings import _ENDPOINT, _number
from .agent_metrics import _KNOWN
from .facts import PROJECTION_VERSION
from .queries import Scope, _where

PAGE = 200
MAX_ROWS = 250000
MAX_AGENTS = 2000
MAX_SCRATCH = 64 * 1024**2
IDENTITY_INDEX_SQL = ("CREATE INDEX identity_at ON identity_spans(queue,alias,starts,ends,canonical) "
                      "WHERE coverage='observed'")
IDENTITY_SQL = ("SELECT DISTINCT canonical FROM identity_spans INDEXED BY identity_at "
                "WHERE queue=? AND alias=? AND coverage='observed' AND starts<=? AND ends>? LIMIT 2")


class AggregationError(RuntimeError):
    pass


class Budget:
    def __init__(self, seconds, rows):
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 300:
            raise ValueError('invalid_aggregation_seconds')
        if type(rows) is not int or not 1 <= rows <= MAX_ROWS:
            raise ValueError('invalid_aggregation_rows')
        self.deadline = time.monotonic() + seconds
        self.maximum = rows
        self.rows = 0

    def check(self, directory=None, count=0):
        self.rows += count
        if self.rows > self.maximum:
            raise AggregationError('aggregation_row_limit')
        if time.monotonic() >= self.deadline:
            raise AggregationError('aggregation_deadline')
        if directory and shutil.disk_usage(directory).free < MAX_SCRATCH:
            raise AggregationError('aggregation_disk_pressure')


@contextmanager
def _reader(path, budget):
    budget.check()
    # Only a sealed, verified operator-owned backup is accepted by run().
    db = sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True, timeout=.05)
    db.row_factory = sqlite3.Row
    deadline = min(budget.deadline, time.monotonic() + 5)
    db.execute('PRAGMA query_only=ON')
    db.execute('PRAGMA trusted_schema=OFF')
    db.execute('PRAGMA cache_size=-1024')
    db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
    try:
        yield db
    finally:
        db.close()


def _activity(path, pbx, scope, first, last, observed, work, budget, output):
    after = ''
    while scope.queues and (not scope.self_only or scope.agents) and first < min(last, observed):
        budget.check(output)
        # The primary key provides a bounded continuation even for old carry-in
        # intervals. Scanned rows, including out-of-scope rows, count to the cap.
        with _reader(path, budget) as db:
            rows = db.execute('SELECT source_key,queue,agent,canonical_agent,state,starts,ends,on_duty,coverage '
                              'FROM report_activity WHERE pbx=? AND source_key>? ORDER BY source_key LIMIT ?',
                              (pbx, after, PAGE)).fetchall()
        budget.check(output, len(rows))
        if not rows:
            break
        accepted = []
        for row in rows:
            if row['queue'] not in scope.queues:
                continue
            if scope.self_only and row['agent'] not in scope.agents and row['canonical_agent'] not in scope.agents:
                continue
            end = min(last, observed, row['ends'] if row['ends'] is not None else observed)
            start = max(first, row['starts'])
            if start >= end:
                continue
            agent = row['canonical_agent'] or row['agent']
            if not isinstance(agent, str) or not 0 < len(agent) <= 256:
                raise AggregationError('aggregation_identity_unavailable')
            accepted.append((row['queue'], row['agent'], agent, start, end,
                             row['state'], bool(row['on_duty']), row['coverage']))
        with work:
            work.executemany('INSERT INTO activity VALUES(?,?,?,?,?,?,?,?)', accepted)
        after = rows[-1]['source_key']
    work.execute("CREATE INDEX identity_source ON activity(queue,alias,canonical,starts,ends) WHERE coverage='observed'")
    work.execute('CREATE INDEX union_time ON activity(canonical,starts,ends)')
    work.commit()
    _identities(work, budget)


def _identities(work, budget):
    """Coalesce identity evidence independently of availability/pause state.

    A month of adjacent state transitions must not be scanned for every visit.
    Different canonical identities are never merged, including their overlaps.
    """
    work.execute('CREATE TABLE identity_spans(queue,alias,canonical,starts REAL,ends REAL,coverage)')
    source = work.execute("SELECT queue,alias,canonical,starts,ends FROM activity INDEXED BY identity_source "
                          "WHERE coverage='observed' ORDER BY queue,alias,canonical,starts,ends")
    pending = None
    batch = []
    def flush():
        if batch:
            with work:
                work.executemany("INSERT INTO identity_spans VALUES(?,?,?,?,?,'observed')", batch)
            batch.clear()
    while True:
        rows = source.fetchmany(PAGE)
        budget.check()
        if not rows:
            break
        for queue, alias, canonical, first, last in rows:
            key = (queue, alias, canonical)
            if pending is not None and tuple(pending[:3]) == key and first <= pending[4]:
                pending[4] = max(pending[4], last)
            else:
                if pending is not None:
                    batch.append(tuple(pending))
                pending = [queue, alias, canonical, first, last]
            if len(batch) >= PAGE:
                flush()
    if pending is not None:
        batch.append(tuple(pending))
    flush()
    work.execute(IDENTITY_INDEX_SQL)
    work.commit()


def _visits(path, pbx, scope, first, last, work, budget, output):
    agents = {}
    if first >= last:
        return agents
    for queue in dict.fromkeys(scope.queues):
        entered, ident = first, ''
        while True:
            budget.check(output)
            clause, args = _where(pbx, Scope((queue,), scope.agents, scope.self_only, scope.not_before), first, last)
            with _reader(path, budget) as db:
                rows = db.execute('SELECT id,agent,entered,answered,ended,talk_seconds,coverage,outcome '
                                  'FROM report_visits INDEXED BY rv_queue_time WHERE ' + clause +
                                  ' AND (entered>? OR (entered=? AND id>?)) ORDER BY entered,id LIMIT ?',
                                  (*args, entered, entered, ident, PAGE)).fetchall()
            budget.check(output, len(rows))
            if not rows:
                break
            for row in rows:
                if not (_number(row['answered']) and row['entered'] <= row['answered'] < last
                        and row['coverage'] in ('observed', 'missing_end')):
                    continue
                agent = row['agent']
                if not isinstance(agent, str) or not _ENDPOINT.fullmatch(agent):
                    # DISTINCT may otherwise choose union_time and scan all
                    # unrelated canonical identities for every Local leg.
                    candidates = work.execute(IDENTITY_SQL,
                                              (queue, agent, row['answered'], row['answered'])).fetchall()
                    if len(candidates) != 1 or not _ENDPOINT.fullmatch(candidates[0][0]):
                        raise AggregationError('agent_identity_unresolved')
                    agent = candidates[0][0]
                if agent not in agents:
                    if len(agents) >= MAX_AGENTS:
                        raise AggregationError('aggregation_agent_limit')
                    agents[agent] = dict(agent=agent, answered_count=0, talk_known_count=0, talk_sum=0.0)
                item = agents[agent]
                item['answered_count'] += 1
                ended, talk = row['ended'], row['talk_seconds']
                if (row['coverage'] == 'observed' and row['outcome'] == 'answered' and _number(ended)
                        and row['answered'] <= ended <= last and _number(talk) and talk <= 315360000
                        and abs(ended - row['answered'] - talk) <= 2):
                    item['talk_known_count'] += 1
                    item['talk_sum'] = math.fsum((item['talk_sum'], talk))
            entered, ident = rows[-1]['entered'], rows[-1]['id']
    return agents


def _rank(agents, metric, samples, top):
    rows = []
    for item in agents.values():
        count = item['talk_known_count']
        average = item['talk_sum'] / count if count else None
        sample = item['answered_count'] if metric == 'answered_count' else count
        if sample < samples:
            continue
        rows.append(dict(agent=item['agent'], answered_count=item['answered_count'], talk_known_count=count,
                         talk_unknown_count=item['answered_count'] - count, avg_queue_talk_seconds=average,
                         sample_count=sample, value=item['answered_count'] if metric == 'answered_count' else average))
    rows.sort(key=lambda r: (-r['value'] if metric == 'answered_count' else r['value'], r['agent']))
    rank = 0
    previous = None
    for i, row in enumerate(rows, 1):
        if i == 1 or row['value'] != previous:
            rank = i
        row['rank'] = rank
        previous = row['value']
    return dict(rows=rows[:top], eligible_agent_count=len(rows), known_endpoint_count=len(agents),
                top_truncated=len(rows) > top,
                tie_at_boundary=len(rows) > top and rows[top-1]['value'] == rows[top]['value'])


def _presence(work, first, last, budget):
    agents = {}
    cursor = work.execute('SELECT canonical,starts,ends,state,on_duty,coverage FROM activity '
                          'INDEXED BY union_time ORDER BY canonical,starts,ends')
    while True:
        rows = cursor.fetchmany(PAGE)
        budget.check()
        if not rows:
            break
        for agent, start, end, state, duty, coverage in rows:
            if agent not in agents:
                if len(agents) >= MAX_AGENTS:
                    raise AggregationError('aggregation_agent_limit')
                agents[agent] = dict(agent=agent, totals={}, ends={}, unknown_intervals=0, unknown_states=0)
            item = agents[agent]
            if state not in _KNOWN:
                item['unknown_states'] += 1
            if coverage != 'observed':
                item['unknown_intervals'] += 1
                continue
            kinds = ['observed']
            if duty:
                kinds.append('on_duty')
            if state in ('on_call', 'hold'):
                kinds.append('on_call')
            if state in ('wrap_up', 'wrapup', 'after_call_work'):
                kinds.append('acw')
            if state == 'paused':
                kinds.append('paused')
            for kind in kinds:
                previous = item['ends'].get(kind, start)
                item['totals'][kind] = item['totals'].get(kind, 0) + max(0, end - max(start, previous))
                item['ends'][kind] = max(previous, end)
    result = []
    for agent, item in sorted(agents.items()):
        totals = item['totals']
        observed = totals.get('observed', 0)
        result.append(dict(agent=agent, observed_seconds=observed,
                           unique_on_duty_seconds=totals.get('on_duty', 0),
                           unique_on_call_seconds=totals.get('on_call', 0),
                           unique_paused_seconds=totals.get('paused', 0),
                           explicit_acw_seconds=totals.get('acw'),
                           unknown_interval_count=item['unknown_intervals'],
                           unknown_state_interval_count=item['unknown_states'],
                           coverage_complete=last>first and abs(observed - (last-first)) < 1e-6
                           and not item['unknown_intervals'] and not item['unknown_states']))
    return result


def run(bundle, destination, scope, start, end, *, pbx='primary', seconds=120,
        max_rows=MAX_ROWS, min_samples=5, top=10):
    """Write private JSON only after both input checksum validations succeed.

    Trusted local operator API, not user/HTTP authorization. Never point a web
    request at this function. Output does not grant anyone access to its contents.
    """
    if not isinstance(scope, Scope):
        raise ValueError('invalid_aggregation_scope')
    _where(pbx, scope, start, end)
    if (type(scope.not_before) not in (int, float) or not math.isfinite(scope.not_before)
            or scope.not_before < 0 or type(scope.self_only) is not bool
            or any(not isinstance(q, str) or not 0 < len(q) <= 128 for q in scope.queues)
            or any(not isinstance(a, str) or not 0 < len(a) <= 256 for a in scope.agents)):
        raise ValueError('invalid_aggregation_scope')
    if type(min_samples) is not int or not 1 <= min_samples <= 100 or type(top) is not int or not 1 <= top <= 20:
        raise ValueError('invalid_aggregation_ranking')
    if end - start > 31 * 86400:
        raise ValueError('aggregation_range_limit')
    budget = Budget(seconds, max_rows)
    bundle = Path(bundle).absolute()
    manifest = backup.verify(bundle, seconds=min(30, seconds))
    path = bundle / 'archive.sqlite3'
    with _reader(path, budget) as db:
        projection = db.execute('SELECT after_id FROM report_projection WHERE pbx=?', (pbx,)).fetchone()
        version = db.execute('SELECT version FROM report_projection_version WHERE pbx=?', (pbx,)).fetchone()
        head = db.execute('SELECT COALESCE(MAX(id),0) FROM events WHERE pbx=?', (pbx,)).fetchone()[0]
        if not version or version[0] != PROJECTION_VERSION or not projection or projection[0] != head:
            raise AggregationError('projection_not_current')
        raw = db.execute("SELECT value FROM checkpoints WHERE pbx=? AND source='activity_cache'", (pbx,)).fetchone()
        observed = json.loads(raw[0]).get('observed', 0) if raw else 0
        if not _number(observed):
            raise AggregationError('activity_heartbeat_unavailable')
    output = backup._private_directory(destination)
    work = sqlite3.connect(output / 'work.sqlite3')
    try:
        os.chmod(output / 'work.sqlite3', 0o600)
        work.execute('PRAGMA cache_size=-1024')
        work.execute('PRAGMA page_size=4096')
        work.execute('PRAGMA temp_store=MEMORY')
        work.execute('PRAGMA max_page_count=16384')
        work.set_progress_handler(lambda: int(time.monotonic() >= budget.deadline), 1000)
        work.execute('CREATE TABLE activity(queue,alias,canonical,starts REAL,ends REAL,state,on_duty,coverage)')
        first = max(float(start), scope.not_before)
        _activity(path, pbx, scope, first, end, observed, work, budget, output)
        agents = _visits(path, pbx, scope, first, end, work, budget, output)
        result = dict(format='sanequeue-private-agent-background-v1', start=float(start), end=float(end),
                      effective_start=first, pbx=pbx, queues=list(scope.queues),
                      scope=dict(agents=list(scope.agents), self_only=scope.self_only, not_before=scope.not_before),
                      source_sha256=manifest['sha256'], projection_version=PROJECTION_VERSION,
                      source_watermark=head, observed_until=observed or None,
                      rankings={metric: _rank(agents, metric, min_samples, top)
                                for metric in ('answered_count', 'avg_queue_talk_seconds')},
                      presence=_presence(work, first, end, budget),
                      contract=dict(unit='queue_visit', unique_conversations=False, ranking_is_quality=False,
                                    presence='union_observed_intervals_across_selected_queue_memberships',
                                    aht_occupancy_included=False, missing_acw_is_zero=False,
                                    complete_source_history=False, private_operator_result=True,
                                    live_permissions_not_checked=True, interactive_limits_unchanged=True),
                      limits=dict(page_rows=PAGE, maximum_scanned_rows=max_rows, scanned_rows=budget.rows,
                                  scratch_max_bytes=MAX_SCRATCH, seconds=seconds))
        budget.check(output)
        if backup.verify(bundle, seconds=min(30, max(.001, budget.deadline-time.monotonic()))) != manifest:
            raise AggregationError('aggregation_source_changed')
        budget.check(output)
        payload = json.dumps(result, ensure_ascii=True, allow_nan=False, sort_keys=True).encode('utf-8')
        if len(payload) > 2 * 1024**2:
            raise AggregationError('aggregation_result_limit')
        backup._write_json(output / 'result.json', result)
        return result
    finally:
        work.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('bundle', 'destination', 'start', 'end'):
        parser.add_argument('--' + key, required=True, type=float if key in ('start', 'end') else str)
    parser.add_argument('--queue', action='append', required=True)
    parser.add_argument('--pbx', default='primary')
    parser.add_argument('--seconds', type=float, default=120)
    args = parser.parse_args()
    run(args.bundle, args.destination, Scope(tuple(args.queue)), args.start, args.end,
        pbx=args.pbx, seconds=args.seconds)
    print('Private background result completed; interactive reporting limits unchanged.')


if __name__ == '__main__':
    main()
