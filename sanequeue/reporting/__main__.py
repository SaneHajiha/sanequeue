"""Offline/laboratory archive CLI. No AMI commands or PBX configuration writes."""
import argparse
import json

from .store import Archive
from .sources import QueueLog, import_json_lines
from .correlate import relations


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', required=True)
    parser.add_argument('--pbx', default='primary')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('initialize')
    commands.add_parser('status')
    queue = commands.add_parser('import-queue')
    queue.add_argument('path')
    queue.add_argument('--batch', type=int, default=500)
    sql = commands.add_parser('import-json')
    sql.add_argument('source', choices=('cdr', 'cel'))
    sql.add_argument('path')
    sql.add_argument('--timezone', default='Asia/Tehran')
    edge = commands.add_parser('relations')
    edge.add_argument('uniqueid')
    args = parser.parse_args()
    archive = Archive(args.database, pbx=args.pbx)
    if args.command == 'initialize':
        archive.initialize()
        result = archive.status()
    elif args.command == 'status':
        result = archive.status()
    elif args.command == 'import-queue':
        result = QueueLog(args.path).ingest(archive, max_events=args.batch)
    elif args.command == 'import-json':
        result = import_json_lines(archive, args.path, args.source, timezone=args.timezone)
    else:
        result = relations(archive, args.uniqueid)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
