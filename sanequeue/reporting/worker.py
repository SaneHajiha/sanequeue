"""Low-priority bounded imports/projections, independent of the HTTP process.

JSONL inputs are immutable snapshots. Optional local SQL is read with indexed,
bounded queries. No ingestion runs in an HTTP request.
"""
import argparse
import json
import logging
import os
from pathlib import Path
import signal
import threading
import time

from .facts import project_batch
from .sources import QueueLog, import_json_lines
from .store import Archive
from .activity_source import ActivitySource
from .sql_source import SQLSource

LOG = logging.getLogger('sanequeue.reporting.worker')
SAFE_REASONS=frozenset(('reporting_source_index_required','reporting_cdr_identity_index_required',
    'reporting_source_schema_missing_fields','reporting_cel_integer_id_required',
    'cel_source_reset_requires_new_generation','cdr_pending_capacity','cdr_identity_fanout_limit',
    'cdr_timestamp_density_exceeds_batch','reporting_disk_pressure','sql_identity_limit'))


class SourceRunner:
    """Isolate source failures and back off without stopping other imports."""
    def __init__(self):
        self.failures={}
        self.due={}

    def run(self,archive,name,function,*,interval=0):
        now=time.time()
        if now<self.due.get(name,0):return dict(deferred=True)
        try:
            result=function()
        except Exception as error:
            count=self.failures.get(name,0)+1
            self.failures[name]=count
            self.due[name]=now+min(300,2**min(count,8))
            status=dict(ok=False,checked=now,error=type(error).__name__,retry_after=self.due[name])
            reason=str(error)
            status['reason']=reason if reason in SAFE_REASONS else 'source_unavailable'
        else:
            self.failures.pop(name,None)
            self.due[name]=now+interval
            status=dict(ok=True,checked=now,progress={key:value for key,value in result.items()
                        if key in ('cel_caught_up','cdr_caught_up','cdr_overlap_caught_up','caught_up','coverage_gap')})
        archive.append([],checkpoint_source='health:'+name,checkpoint=status)
        return result if status['ok'] else status


def cycle(archive, *, queue_log=None, cdr_json=None, cel_json=None, activity_cache=None, sql_source=None, runner=None):
    """One bounded cycle; source positions and facts survive cancellation."""
    result = {}
    runner=runner or SourceRunner()
    if queue_log:
        result['queue_log'] = runner.run(archive,'queue_log',lambda:QueueLog(queue_log).ingest(archive, max_events=250, seconds=.05))
    for source, path in (('cdr', cdr_json), ('cel', cel_json)):
        if path:
            result[source] = runner.run(archive,source,lambda:import_json_lines(archive, path, source, max_events=250))
    if activity_cache:
        result['activity']=runner.run(archive,'activity',lambda:ActivitySource(activity_cache).ingest(archive))
    if sql_source:
        result['sql']=runner.run(archive,'sql',lambda:sql_source.ingest(archive),interval=15)
    result['projection'] = project_batch(archive, limit=500)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--pbx', default='primary')
    parser.add_argument('--queue-log')
    parser.add_argument('--cdr-json')
    parser.add_argument('--cel-json')
    parser.add_argument('--activity-cache')
    parser.add_argument('--mysql-config')
    parser.add_argument('--disabled-file')
    parser.add_argument('--interval', type=float, default=3)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    if not 1 <= args.interval <= 300:
        parser.error('interval must be between 1 and 300 seconds')
    logging.basicConfig(level=logging.INFO)
    if hasattr(os, 'nice'):
        os.nice(10)
    stopped = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopped.set())
    archive = Archive(args.database, pbx=args.pbx)
    archive.initialize()
    sql_source=SQLSource.from_file(args.mysql_config) if args.mysql_config else None
    runner=SourceRunner()
    checkpoint_at = time.monotonic()
    while not stopped.is_set():
        if args.disabled_file and Path(args.disabled_file).exists():
            if args.once:
                print(json.dumps(dict(paused=True)))
                return
            stopped.wait(args.interval)
            continue
        try:
            result = cycle(archive, queue_log=args.queue_log, cdr_json=args.cdr_json, cel_json=args.cel_json,activity_cache=args.activity_cache,sql_source=sql_source,runner=runner)
            if args.once:
                print(json.dumps(result))
                return
            if time.monotonic() - checkpoint_at >= 60:
                archive.passive_checkpoint()
                checkpoint_at = time.monotonic()
        except (OSError, ValueError) as error:
            if args.once:
                raise
            # Never log payloads, paths, source numbers or credentials.
            LOG.warning('Reporting cycle deferred: %s', type(error).__name__)
        except Exception:
            if args.once:
                raise
            LOG.warning('Reporting cycle deferred; archive/source health requires inspection')
        stopped.wait(args.interval)


if __name__ == '__main__':
    main()
