"""Run the independent collector; secrets are read from a local INI file."""
import argparse
import asyncio
import json
import logging
import signal
import os
from pathlib import Path

from redis.asyncio import Redis
from .collector import Collector
from .config import Settings
from .store import RedisStateStore


async def main(args):
    settings = Settings.load(args.config)
    redis = Redis.from_url(settings.redis_url, socket_timeout=3, socket_connect_timeout=3,
                           decode_responses=True)
    store = RedisStateStore(redis, settings.pbx_id)
    try:
        if args.status:
            report = await store.read()
            state = report['state'] or {}
            print(json.dumps({'stale': report['stale'], 'health': report['health'],
                              'queue_count': len(state.get('queues', {})),
                              'channel_legs': len(state.get('channels', {}))}))
            return
        from .activity import ActivityRecorder,ActivityStore
        activity=ActivityRecorder(ActivityStore(Path(os.getenv('SANEQUEUE_STATE_DIR','/var/lib/sanequeue'))/'activity.sqlite3'))
        task = asyncio.create_task(Collector(settings, store,activity).run())
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(signum, task.cancel)
            except (NotImplementedError, RuntimeError):
                pass
        try:
            await task
        except asyncio.CancelledError:
            pass
    finally:
        await redis.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='SaneQueue persistent read-only AMI collector')
    parser.add_argument('--config', required=True)
    parser.add_argument('--status', action='store_true', help='Print sanitized Redis health; never contacts AMI')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        # Do not print URLs, INI contents or raw AMI errors.
        logging.error('collector_failed error_type=%s', type(exc).__name__)
        raise SystemExit(1)
