"""Bounded, event-driven queue membership observations, without CDR/AMI queries.

The collector records transitions in memory. An independent asyncio task sends
small batches to SQLite off the event loop. Coverage stops at the last collector
heartbeat; a reconnect never turns a monitoring gap into credited work time.
"""
from collections import deque
from datetime import datetime, time as day_time, timedelta
from pathlib import Path
import os
import sqlite3
import time
import uuid
from zoneinfo import ZoneInfo

from .state import agent_state


class ActivityStore:
    def __init__(self, path):
        self.path = Path(path)
        self.last_prune = 0

    def write(self, transitions, observed_at, generation):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=2)
        try:
            os.chmod(self.path, 0o600)
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA synchronous=NORMAL')
            with db:
                db.execute('CREATE TABLE IF NOT EXISTS activity_meta (id INTEGER PRIMARY KEY CHECK(id=1), generation TEXT, observed REAL)')
                db.execute('CREATE TABLE IF NOT EXISTS activity (id INTEGER PRIMARY KEY, queue TEXT NOT NULL, agent TEXT NOT NULL, state TEXT NOT NULL, reason TEXT NOT NULL, starts REAL NOT NULL, ends REAL, on_duty INTEGER NOT NULL)')
                db.execute('CREATE INDEX IF NOT EXISTS activity_period ON activity(queue,agent,starts)')
                db.execute('CREATE INDEX IF NOT EXISTS activity_end ON activity(ends)')
                # Ordinary index also works with older host SQLite builds.
                db.execute('CREATE INDEX IF NOT EXISTS activity_lookup ON activity(queue,agent,ends)')
                db.execute('BEGIN IMMEDIATE')
                meta=db.execute('SELECT generation,observed FROM activity_meta WHERE id=1').fetchone()
                if meta and meta[1]>observed_at:return
                if meta and meta[0]!=generation:
                    db.execute('UPDATE activity SET ends=MAX(starts,?) WHERE ends IS NULL',(meta[1],))
                for queue,agent,state,reason,stamp,on_duty in transitions:
                    db.execute('UPDATE activity SET ends=MAX(starts,?) WHERE queue=? AND agent=? AND ends IS NULL',(stamp,queue,agent))
                    db.execute('INSERT INTO activity(queue,agent,state,reason,starts,on_duty) VALUES (?,?,?,?,?,?)',(queue,agent,state,reason,stamp,int(on_duty)))
                db.execute('INSERT OR REPLACE INTO activity_meta VALUES (1,?,?)',(generation,observed_at))
                db.execute('DELETE FROM activity WHERE ends IS NOT NULL AND id<(SELECT COALESCE(MAX(id),0)-490000 FROM activity)')
                if observed_at-self.last_prune>=3600:
                    db.execute('DELETE FROM activity WHERE ends<?',(observed_at-90*86400,))
                    self.last_prune=observed_at
        finally:
            db.close()

    def daily(self, queues, day, *, agent='', timezone='Asia/Tehran', now=None,not_before=0):
        zone=ZoneInfo(timezone)
        date=datetime.strptime(day,'%Y-%m-%d').date()
        start=max(datetime.combine(date,day_time(),zone).timestamp(),float(not_before))
        finish=datetime.combine(date+timedelta(days=1),day_time(),zone).timestamp()
        result=dict(day=day,timezone=timezone,rows=[],observed_until=None,complete_history=False)
        allowed=tuple(sorted(set(queues)))
        if not allowed or not self.path.exists():return result
        if len(allowed)>1024:raise ValueError('queue_limit')
        db=sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,timeout=2)
        db.row_factory=sqlite3.Row
        try:
            meta=db.execute('SELECT observed FROM activity_meta WHERE id=1').fetchone()
            if not meta:return result
            cutoff=min(float(meta[0]),time.time() if now is None else now,finish)
            result['observed_until']=meta[0]
            placeholders=','.join('?' for _ in allowed)
            sql='SELECT queue,agent,state,reason,on_duty,SUM(MIN(COALESCE(ends,?),?)-MAX(starts,?)) AS seconds,MIN(MAX(starts,?)) AS first,MAX(MIN(COALESCE(ends,?),?)) AS last FROM activity WHERE queue IN ('+placeholders+') AND starts<? AND COALESCE(ends,?)>?'
            args=[cutoff,cutoff,start,start,cutoff,cutoff,*allowed,cutoff,cutoff,start]
            if agent:
                sql+=' AND agent=?';args.append(agent)
            sql+=' GROUP BY queue,agent,state,reason,on_duty HAVING seconds>0 ORDER BY queue,agent,state,reason'
            result['rows']=[dict(row) for row in db.execute(sql,args)]
            return result
        finally:db.close()


class ActivityRecorder:
    def __init__(self, store, *, max_pending=20000):
        self.store=store
        self.current={}
        self.by_queue={}
        self.pending=deque()
        self.max_pending=max_pending
        self.generation=''
        self.observed=0
        self.dropped=0

    def reset(self, generation):
        self.current={}
        self.by_queue={}
        self.pending.clear()
        self.generation=generation
        self.observed=0

    def observe(self, queues, now, *, only_queue=None):
        self.observed=now
        selected={only_queue:queues.get(only_queue,{'members':{}})} if only_queue else queues
        for queue,data in selected.items():
            members=data.get('members',{})
            seen=set()
            for interface,member in members.items():
                derived=agent_state(member,now)
                state='paused' if derived['paused'] else derived['activity']
                reason=str(member.get('pausedreason',''))[:100] if derived['paused'] else ''
                self._transition(queue,interface,state,reason,now,derived['on_duty'])
                seen.add(interface)
            for interface in self.by_queue.get(queue,set())-seen:
                self._transition(queue,interface,'removed','',now,False)

    def _transition(self, queue, interface, state, reason, now, on_duty):
        key=(queue,interface)
        value=(state,reason,bool(on_duty))
        if self.current.get(key)==value:return
        if len(self.current)>=10000 and key not in self.current:
            self.dropped+=1;return
        if len(self.pending)>=self.max_pending:
            # Start a new coverage generation instead of inventing durations
            # across dropped observations. Existing rows end at last flush.
            self.dropped+=1
            self.current.clear();self.by_queue.clear();self.pending.clear()
            self.generation=uuid.uuid4().hex
        self.current[key]=value
        self.by_queue.setdefault(queue,set()).add(interface)
        self.pending.append((str(queue),str(interface),state,reason,now,bool(on_duty)))

    async def flush(self):
        import asyncio
        if not self.observed:return
        batch=list(self.pending);self.pending.clear()
        try:
            await asyncio.to_thread(self.store.write,batch,self.observed,self.generation)
        except (OSError,sqlite3.Error):
            # Keep monitoring independent of disk failures and bound the retry.
            if len(batch)+len(self.pending)<=self.max_pending:
                self.pending.extendleft(reversed(batch))
            else:
                self.dropped+=len(batch)
                self.current.clear();self.by_queue.clear();self.pending.clear();self.generation=uuid.uuid4().hex
