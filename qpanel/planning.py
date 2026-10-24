"""Small, scoped scheduling/directory store. Never modifies PBX state."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone


class PlanningStore:
    def __init__(self, path):
        self.path = str(path)

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=5)
        db.row_factory=sqlite3.Row
        try:
            with db:
                db.execute('CREATE TABLE IF NOT EXISTS shifts (id INTEGER PRIMARY KEY, queue TEXT, agent TEXT, starts INTEGER, ends INTEGER, note TEXT)')
                db.execute('CREATE INDEX IF NOT EXISTS shift_period ON shifts(starts, ends)')
                db.execute('CREATE TABLE IF NOT EXISTS directory (id INTEGER PRIMARY KEY, queue TEXT, name TEXT, phone TEXT, note TEXT)')
                yield db
        finally:db.close()

    def list(self, kind, queues):
        if kind not in ('shifts','directory'):raise ValueError('unknown_kind')
        with self.connect() as db:
            allowed=tuple(str(q) for q in queues)
            if not allowed:return []
            placeholders=','.join('?' for _ in allowed)
            rows=db.execute('SELECT * FROM '+kind+' WHERE queue IN ('+placeholders+') ORDER BY id DESC LIMIT 1000',allowed).fetchall()
            return [dict(row) for row in rows]

    def save(self, kind, data, queues):
        if kind not in ('shifts','directory'):raise ValueError('unknown_kind')
        if not isinstance(data,dict):raise ValueError('invalid_payload')
        queue=str(data.get('queue',''))
        if queue not in queues:raise PermissionError('queue_not_allowed')
        ident=data.get('id')
        note=str(data.get('note','')).strip()[:300]
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if ident:
                row=db.execute('SELECT queue FROM '+kind+' WHERE id=?',(ident,)).fetchone()
                if not row or row['queue'] not in queues:raise PermissionError('record_not_allowed')
            if data.get('delete'):
                if not ident:raise ValueError('record_required')
                db.execute('DELETE FROM '+kind+' WHERE id=?',(ident,));return
            if kind=='shifts':
                agent=str(data.get('agent','')).strip()
                if not agent or len(agent)>100:raise ValueError('invalid_agent')
                try:
                    start=datetime.fromisoformat(str(data['starts']).replace('Z','+00:00'))
                    end=datetime.fromisoformat(str(data['ends']).replace('Z','+00:00'))
                    if start.tzinfo is None or end.tzinfo is None:raise ValueError()
                    begin,finish=int(start.timestamp()),int(end.timestamp())
                    if not 0 < finish-begin <= 86400:raise ValueError()
                except (KeyError,ValueError,TypeError):raise ValueError('invalid_shift_period')
                if db.execute('SELECT 1 FROM shifts WHERE agent=? AND starts<? AND ends>? AND id!=?',(agent,finish,begin,int(ident or 0))).fetchone():raise ValueError('overlapping_shift')
                fields=(queue,agent,begin,finish,note)
                if ident:db.execute('UPDATE shifts SET queue=?,agent=?,starts=?,ends=?,note=? WHERE id=?',fields+(ident,))
                else:db.execute('INSERT INTO shifts(queue,agent,starts,ends,note) VALUES (?,?,?,?,?)',fields)
            else:
                name,phone=str(data.get('name','')).strip(),str(data.get('phone','')).strip()
                if not name or len(name)>100 or not phone or len(phone)>40 or any(c not in '+0123456789*# -()' for c in phone):raise ValueError('invalid_contact')
                fields=(queue,name,phone,note)
                if ident:db.execute('UPDATE directory SET queue=?,name=?,phone=?,note=? WHERE id=?',fields+(ident,))
                else:db.execute('INSERT INTO directory(queue,name,phone,note) VALUES (?,?,?,?)',fields)
