"""Incremental, bounded queue_log ingestion. No caller numbers are persisted."""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime


def number(value):
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError, OverflowError):
        return 0


class QueueReports:
    def __init__(self, database):
        self.database = database

    @contextmanager
    def connect(self):
        os.makedirs(os.path.dirname(os.path.abspath(self.database)), exist_ok=True)
        conn = sqlite3.connect(self.database, timeout=10)
        conn.execute('CREATE TABLE IF NOT EXISTS cursor (path TEXT PRIMARY KEY, inode TEXT, position INTEGER)')
        conn.execute('CREATE TABLE IF NOT EXISTS events (ts INTEGER, queue TEXT, agent TEXT, event TEXT, wait INTEGER, talk INTEGER)')
        conn.execute('CREATE INDEX IF NOT EXISTS event_range ON events(ts, queue)')
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def ingest(self, path, budget=8 * 1024 * 1024):
        with self.connect() as conn, open(path, 'rb') as source:
            conn.execute('BEGIN IMMEDIATE')
            stat = os.fstat(source.fileno())
            inode = str(stat.st_dev) + ':' + str(stat.st_ino)
            cursor = conn.execute('SELECT inode, position FROM cursor WHERE path=?', (path,)).fetchone()
            position = cursor[1] if cursor and cursor[0] == inode and cursor[1] <= stat.st_size else 0
            source.seek(position)
            start = position
            while source.tell() - start < budget:
                position = source.tell()
                line = source.readline(65536)
                if not line or not line.endswith(b'\n'):
                    source.seek(position)
                    break
                parts = line.decode('utf-8', 'replace').rstrip('\r\n').split('|')
                if len(parts) < 5 or not parts[0].isdigit():
                    continue
                ts, _, queue, agent, event = parts[:5]
                values = parts[5:]
                if event not in ('ENTERQUEUE', 'CONNECT', 'ABANDON', 'COMPLETEAGENT', 'COMPLETECALLER', 'EXITWITHTIMEOUT', 'RINGNOANSWER'):
                    continue
                wait = number(values[0]) if event in ('CONNECT', 'COMPLETEAGENT', 'COMPLETECALLER') and values else 0
                if event in ('ABANDON', 'EXITWITHTIMEOUT') and len(values) > 2:
                    wait = number(values[2])
                talk = number(values[1]) if event.startswith('COMPLETE') and len(values) > 1 else 0
                conn.execute('INSERT INTO events VALUES (?,?,?,?,?,?)', (int(ts), queue, agent, event, wait, talk))
            position = source.tell()
            conn.execute('INSERT OR REPLACE INTO cursor VALUES (?,?,?)', (path, inode, position))
            return {'caught_up': position >= stat.st_size, 'bytes_remaining': max(0, stat.st_size - position)}

    def report(self, start, end, queues, sla=20):
        groups, hours = {}, [0] * 24
        with self.connect() as conn:
            rows = conn.execute('SELECT ts, queue, agent, event, wait, talk FROM events WHERE ts>=? AND ts<? ORDER BY ts', (start, end))
            for ts, queue, agent, event, wait, talk in rows:
                if queue not in queues:
                    continue
                key = (queue, agent if event != 'ENTERQUEUE' else '—')
                row = groups.setdefault(key, dict(queue=queue, agent=key[1], entered=0, answered=0, abandoned=0, completed=0, missed=0, within_sla=0, wait_seconds=0, talk_seconds=0))
                if event == 'ENTERQUEUE':
                    row['entered'] += 1
                    hours[datetime.fromtimestamp(ts).hour] += 1
                elif event == 'CONNECT':
                    row['answered'] += 1
                    row['wait_seconds'] += wait
                    row['within_sla'] += int(wait <= sla)
                elif event in ('ABANDON', 'EXITWITHTIMEOUT'):
                    row['abandoned'] += 1
                elif event.startswith('COMPLETE'):
                    row['completed'] += 1
                    row['talk_seconds'] += talk
                elif event == 'RINGNOANSWER':
                    row['missed'] += 1
        total = {key: sum(row[key] for row in groups.values()) for key in ('entered', 'answered', 'abandoned', 'completed', 'missed', 'within_sla', 'wait_seconds', 'talk_seconds')}
        total['average_wait'] = round(total['wait_seconds'] / total['answered'], 1) if total['answered'] else None
        total['average_talk'] = round(total['talk_seconds'] / total['completed'], 1) if total['completed'] else None
        total['service_level'] = round(100 * total['within_sla'] / total['entered'], 1) if total['entered'] else None
        return dict(totals=total, rows=list(groups.values()), hourly=hours, sla_seconds=sla)
