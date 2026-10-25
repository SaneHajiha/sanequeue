"""Low-priority bounded imports/projections, independent of the HTTP process.

JSONL inputs are immutable source snapshots. This worker does not pretend to
be a direct SQL replication adapter. Live queue_log is followed incrementally.
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

LOG = logging.getLogger('sanequeue.reporting.worker')


def cycle(archive, *, queue_log=None, cdr_json=None, cel_json=None):
    """One bounded cycle; source positions and facts survive cancellation."""
    result = {}
    if queue_log:
        result['queue_log'] = QueueLog(queue_log).ingest(archive, max_events=250, seconds=.05)
    for source, path in (('cdr', cdr_json), ('cel', cel_json)):
        if path:
            result[source] = import_json_lines(archive, path, source, max_events=250)
    result['projection'] = project_batch(archive, limit=500)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--pbx', default='primary')
    parser.add_argument('--queue-log')
    parser.add_argument('--cdr-json')
    parser.add_argument('--cel-json')
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
    checkpoint_at = time.monotonic()
    while not stopped.is_set():
        if args.disabled_file and Path(args.disabled_file).exists():
            if args.once:
                print(json.dumps(dict(paused=True)))
                return
            stopped.wait(args.interval)
            continue
        try:
            result = cycle(archive, queue_log=args.queue_log, cdr_json=args.cdr_json, cel_json=args.cel_json)
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
