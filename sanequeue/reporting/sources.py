"""Bounded source adapters. These never perform PBX writes or AMI requests."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import time
from zoneinfo import ZoneInfo

from .store import Event


def sql_event(source, row, *, timezone='Asia/Tehran'):
    if source not in ('cdr', 'cel'):
        raise ValueError('invalid_sql_source')
    row = {str(k).lower(): v for k, v in row.items()}
    stamp = row.get('eventtime' if source == 'cel' else 'calldate')
    if isinstance(stamp, str):
        stamp = datetime.fromisoformat(stamp)
    if not isinstance(stamp, datetime):
        raise ValueError('missing_source_datetime')
    assumed_zone = stamp.tzinfo is None
    ambiguous = False
    if assumed_zone:
        ambiguous = stamp.replace(tzinfo=ZoneInfo(timezone), fold=0).utcoffset() != stamp.replace(tzinfo=ZoneInfo(timezone), fold=1).utcoffset()
        stamp = stamp.replace(tzinfo=ZoneInfo(timezone))
    timestamp = stamp.timestamp()
    payload = {k: v.isoformat() if isinstance(v, datetime) else v for k, v in row.items()}
    payload['_source_time'] = dict(timezone=timezone if assumed_zone else str(stamp.tzinfo),
                                   assumed=assumed_zone, ambiguous_or_nonexistent=ambiguous)
    if source == 'cel':
        ident = row.get('id')
        if ident is None or not str(ident).isdigit():
            raise ValueError('cel_id_required')
        key = str(ident)
        kind = str(row.get('eventtype') or 'UNKNOWN')
    else:
        # Legacy Issabel CDR schemas have no integer primary key.
        identity = [timestamp] + [str(row.get(k, '')) for k in ('uniqueid', 'linkedid', 'sequence')]
        key = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
        kind = 'CDR'
    return Event(source, key, timestamp, kind, payload)


class QueueLog:
    def __init__(self, path, *, source='queue_log'):
        self.path = Path(path)
        self.source = source

    def ingest(self, archive, *, max_events=500, max_bytes=262144, seconds=.1):
        """Commit complete lines and cursor together; preserve rejected bytes as evidence.

        The anchor detects copy-truncate-and-regrow even if the new file is
        already larger than the old cursor. Generation is part of the key.
        """
        max_events = max(1, min(1000, max_events))
        max_bytes = max(65537, min(1024 * 1024, max_bytes))
        previous = archive.checkpoint(self.source)
        if previous.get('path') and previous['path'] != str(self.path.absolute()):
            raise ValueError('source_path_changed_use_new_source_id')
        with self.path.open('rb') as stream:
            meta = os.fstat(stream.fileno())
            identity = str(meta.st_dev) + ':' + str(meta.st_ino)
            offset = int(previous.get('offset', 0))
            generation = int(previous.get('generation', 0))
            reset = previous and (identity != previous.get('identity') or offset > meta.st_size)
            if previous and offset and not reset:
                stream.seek(max(0, offset - 256))
                reset = hashlib.sha256(stream.read(min(256, offset))).hexdigest() != previous.get('anchor')
            if reset:
                offset = 0
                generation += 1
            stream.seek(offset)
            started = offset
            deadline = time.monotonic() + max(.001, min(2, seconds))
            events = []
            rejected = 0
            discarding = bool(previous.get('discarding')) and not reset
            while len(events) < max_events and stream.tell() - started < max_bytes and time.monotonic() < deadline:
                line_start = stream.tell()
                raw = stream.readline(min(65537, max_bytes - (line_start - started)))
                if not raw:
                    break
                if discarding:
                    if raw.endswith(b'\n'):
                        discarding = False
                    continue
                if not raw.endswith(b'\n') or len(raw) > 65536:
                    if len(raw) >= 65536:
                        # A poison line must not pin ingestion forever.
                        discarding = not raw.endswith(b'\n')
                        rejected += 1
                        events.append(Event(self.source, f'{identity}:{generation}:{line_start}', 0,
                                            'INGEST_REJECTED', {'reason': 'oversized_line', 'prefix_sha256': hashlib.sha256(raw).hexdigest()}))
                    else:
                        stream.seek(line_start)
                    break
                parts = raw.decode('utf-8', errors='replace').rstrip('\r\n').split('|')
                key = f'{identity}:{generation}:{line_start}'
                if len(parts) < 5 or not parts[0].isdigit():
                    rejected += 1
                    event = Event(self.source, key, 0, 'INGEST_REJECTED',
                                  {'reason': 'invalid_queue_log', 'raw': raw.decode('utf-8', errors='replace')[:8192]})
                else:
                    event = Event(self.source, key, float(parts[0]), parts[4],
                                  dict(callid=parts[1], queue=parts[2], agent=parts[3], values=parts[5:]))
                events.append(event)
            offset = stream.tell()
            stream.seek(max(0, offset - 256))
            anchor = hashlib.sha256(stream.read(min(256, offset))).hexdigest()
            checkpoint = dict(path=str(self.path.absolute()), identity=identity, offset=offset,
                              generation=generation, anchor=anchor, discarding=discarding,observed=time.time(),
                              caught_up=offset>=meta.st_size,
                              source_time=max((event.timestamp for event in events),default=previous.get('source_time',0)))
            gaps=list(previous.get('coverage_gaps',[]))
            # Rotation must not silently present partial history as complete.
            if reset:
                checkpoint['last_rotation_detected'] = time.time()
                boundary=previous.get('observed',0) if previous.get('caught_up') is True else previous.get('source_time',0)
                gaps.append([max(0,float(boundary)-120),checkpoint['last_rotation_detected']])
            elif previous.get('last_rotation_detected'):
                checkpoint['last_rotation_detected'] = previous['last_rotation_detected']
            if reset or previous.get('coverage_gap'):
                # The prior inode's unread tail cannot be proven complete.
                # Preserve this uncertainty across subsequent healthy cycles.
                checkpoint['coverage_gap']=True
            if not gaps and previous.get('last_rotation_detected'):
                # Legacy checkpoints have no trustworthy lower boundary.
                gaps=[[0,previous['last_rotation_detected']]]
            if len(gaps)>32:
                # Bound metadata without silently forgetting an older gap.
                gaps=[[min(g[0] for g in gaps[:-31]),max(g[1] for g in gaps[:-31])],*gaps[-31:]]
            if gaps:checkpoint['coverage_gaps']=gaps
            inserted = archive.append(events, checkpoint_source=self.source, checkpoint=checkpoint, rejected=rejected)
            return dict(inserted=inserted, offset=offset, caught_up=offset >= meta.st_size,
                        rotation_detected=bool(reset), coverage_gap=bool(checkpoint.get('coverage_gap')), rejected=rejected)


def import_json_lines(archive, path, source, *, timezone='Asia/Tehran', max_events=500):
    """Import bounded exported CDR/CEL rows, preserving continuation position."""
    name = 'json:' + source + ':' + hashlib.sha256(str(Path(path).absolute()).encode()).hexdigest()[:24]
    cursor = archive.checkpoint(name)
    events = []
    with Path(path).open('rb') as stream:
        metadata = os.fstat(stream.fileno())
        identity = str(metadata.st_dev) + ':' + str(metadata.st_ino)
        if cursor and (cursor.get('identity') != identity or cursor.get('offset', 0) > metadata.st_size):
            raise ValueError('json_source_replaced_use_new_path')
        if cursor and (cursor.get('mtime_ns') != metadata.st_mtime_ns or cursor.get('size') != metadata.st_size):
            raise ValueError('json_snapshot_modified_use_new_path')
        stream.seek(cursor.get('offset', 0))
        batch_start = stream.tell()
        for _ in range(max(1, min(1000, max_events))):
            if stream.tell() - batch_start >= 1024 * 1024:
                break
            start = stream.tell()
            raw = stream.readline(65537)
            if not raw:
                break
            if not raw.endswith(b'\n'):
                if len(raw) > 65536:
                    raise ValueError('json_row_too_large')
                stream.seek(start)
                break
            row = json.loads(raw)
            events.append(sql_event(source, row, timezone=timezone))
        # SQL exports are immutable snapshots. A changed export gets a new path;
        # source-level keys still deduplicate it against already archived rows.
        checkpoint = dict(identity=identity, offset=stream.tell(), size=metadata.st_size, mtime_ns=metadata.st_mtime_ns)
        count = archive.append(events, checkpoint_source=name, checkpoint=checkpoint)
        return dict(inserted=count, caught_up=checkpoint['offset'] >= metadata.st_size)
