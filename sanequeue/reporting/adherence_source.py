"""Bounded read-only shift source; never initializes the planning database."""
from pathlib import Path
import sqlite3
import time

from .store import QueryDeadline


def read(path, queues, start, end):
    if path is None or not Path(path).is_file():
        return dict(configured=False, shifts=[])
    path=Path(path)
    if path.is_symlink():
        raise ValueError('shift_source_symlink')
    queues=tuple(dict.fromkeys(queues))
    if not queues:
        return dict(configured=True, shifts=[])
    if len(queues)>256:
        raise ValueError('shift_scope_limit')
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.25)
    db.row_factory=sqlite3.Row
    deadline=time.monotonic()+.5
    db.set_progress_handler(lambda:int(time.monotonic()>=deadline),500)
    try:
        db.execute('PRAGMA query_only=ON');db.execute('PRAGMA trusted_schema=OFF')
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='shifts'").fetchone():
            return dict(configured=False, shifts=[])
        rows=[dict(row) for row in db.execute('''SELECT id,queue,agent,starts,ends FROM shifts
            WHERE queue IN ('''+','.join('?' for _ in queues)+''') AND starts<? AND ends>?
            ORDER BY starts,id LIMIT 2001''',(*queues,float(end),float(start)))]
        if len(rows)>2000:
            raise QueryDeadline('shift_limit_narrow_range')
        return dict(configured=True,shifts=rows)
    except sqlite3.OperationalError as error:
        if 'interrupt' in str(error).lower():raise QueryDeadline('shift_source_deadline') from None
        raise
    finally:
        db.close()
