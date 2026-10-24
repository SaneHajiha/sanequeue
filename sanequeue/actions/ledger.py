"""Local SQLite WAL ledger. No network calls while a DB transaction is held."""
from contextlib import contextmanager
import json
import math
from pathlib import Path
import secrets
import sqlite3
import time


class QueueBusy(RuntimeError):
    pass


class ActionLedger:
    def __init__(self, path, *, clock=time.time, reservation_seconds=300):
        self.path, self.clock = str(path), clock
        self.reservation_seconds=max(300,reservation_seconds)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS commands (
                id TEXT PRIMARY KEY, user TEXT NOT NULL, queue TEXT NOT NULL,
                action TEXT NOT NULL, fields TEXT NOT NULL, state TEXT NOT NULL,
                created REAL NOT NULL, updated REAL NOT NULL, evidence TEXT NOT NULL DEFAULT '');
              CREATE INDEX IF NOT EXISTS commands_pending ON commands(state,created);
              CREATE TABLE IF NOT EXISTS queue_locks(queue TEXT PRIMARY KEY,token TEXT,expires REAL);
              CREATE TABLE IF NOT EXISTS departures(queue TEXT,agent TEXT,expires REAL,PRIMARY KEY(queue,agent));''')

    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=2)
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA busy_timeout=2000')
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def queue_lock(self, queue):
        token, now = secrets.token_hex(16), self.clock()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM queue_locks WHERE expires < ?', (now,))
            try:db.execute('INSERT INTO queue_locks VALUES (?,?,?)',(queue,token,now+20))
            except sqlite3.IntegrityError:raise QueueBusy('queue_action_in_progress') from None
        try:
            yield
        finally:
            with self.db() as db:db.execute('DELETE FROM queue_locks WHERE queue=? AND token=?',(queue,token))

    def reserve(self, queue, agent, members, staffing, *, dry=False):
        def on_duty(m):
            return str(m.get('Paused','0')).lower() in ('0','false') and str(m.get('Status','0')) not in ('-1','0','4','5')
        now=self.clock()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM departures WHERE expires<?',(now,))
            index={str(k):m for k,m in members.items()}
            for m in members.values():
                if m.get('Location'):index[str(m['Location'])]=m
            if agent not in index:return False,'agent_not_in_queue'
            roster=staffing['roster_size']
            if not roster:return False,'configure_roster_size_before_leaving'
            pending=0
            for row in db.execute('SELECT agent FROM departures WHERE queue=?',(queue,)).fetchall():
                who=row['agent']
                if who not in index or not on_duty(index[who]):
                    db.execute('DELETE FROM departures WHERE queue=? AND agent=?',(queue,who))
                elif who==agent:return False,'departure_already_in_progress'
                else:pending+=1
            minimum=max(staffing['min_on_duty'],roster-min(staffing['max_absent_count'],math.floor(roster*staffing['max_absent_percent']/100)))
            after=sum(on_duty(m) for m in members.values())-pending-int(on_duty(index[agent]))
            if after<minimum:return False,'queue_exit_limit_reached'
            if not dry:db.execute('INSERT OR REPLACE INTO departures VALUES (?,?,?)',(queue,agent,now+self.reservation_seconds))
            return True,'ok'

    def release(self, queue, agent):
        with self.db() as db:db.execute('DELETE FROM departures WHERE queue=? AND agent=?',(queue,agent))

    def create(self, user, queue, action, fields):
        ident='sq-'+secrets.token_hex(16);now=self.clock()
        with self.db() as db:
            db.execute('INSERT INTO commands(id,user,queue,action,fields,state,created,updated) VALUES (?,?,?,?,?,?,?,?)',
                       (ident,user,queue,action,json.dumps(fields),'pending',now,now))
            db.execute('DELETE FROM commands WHERE id IN (SELECT id FROM commands ORDER BY created DESC LIMIT -1 OFFSET 5000)')
        return ident

    def update(self, ident, state, evidence):
        if state not in ('pending','confirmed','rejected','unknown'):raise ValueError('invalid_command_state')
        with self.db() as db:
            db.execute("UPDATE commands SET state=?,evidence=?,updated=? WHERE id=? AND state='pending'",(state,evidence,self.clock(),ident))

    def pending(self):
        with self.db() as db:return [dict(r) for r in db.execute("SELECT * FROM commands WHERE state='pending' ORDER BY created LIMIT 100")]

    def public(self, ident, user, allowed):
        with self.db() as db:row=db.execute('SELECT id,user,queue,action,state,created,updated,evidence FROM commands WHERE id=?',(ident,)).fetchone()
        if row is None or row['user']!=user or row['queue'] not in allowed:return None
        result=dict(row);result.pop('user')
        result['audio_verified']=False
        return result

    def reconcile(self, state):
        """Confirm observed state, not causation or audio correctness."""
        for row in self.pending():
            fields=json.loads(row['fields']);action=row['action'];q=state.get('queues',{}).get(row['queue'],{})
            member=q.get('members',{}).get(fields.get('Interface'))
            confirmed=False
            if action=='QueuePause' and member is not None:
                confirmed=str(member.get('paused','0')).lower() in ('1','true') if str(fields['Paused']).lower()=='true' else str(member.get('paused','0')).lower() in ('0','false')
            elif action=='QueuePenalty' and member is not None:confirmed=str(member.get('penalty'))==str(fields['Penalty'])
            elif action=='QueueAdd':confirmed=member is not None
            elif action=='QueueRemove':confirmed=member is None and bool(q)
            elif action=='QueueChangePriorityCaller':confirmed=any(e.get('channel')==fields.get('Caller') and str(e.get('priority'))==str(fields['Priority']) for e in q.get('entries',{}).values())
            elif action=='Hangup':confirmed=bool(state.get('channels_complete')) and not any(c.get('channel')==fields.get('Channel') for c in state.get('channels',{}).values())
            elif action=='Park':confirmed=any(p.get('parkeechannel')==fields.get('Channel') and p.get('observed_at',0)>=row['created'] for p in state.get('parked',{}).values())
            event=state.get('action_events',{}).get(row['id'])
            if event and event.get('response','').lower()=='failure':
                self.update(row['id'],'rejected','originate_failed');continue
            newer=max(state.get('last_event_at') or 0,state.get('last_sync_at') or 0)>row['created']
            if confirmed and newer:self.update(row['id'],'confirmed','effect_observed_no_causation_or_audio_guarantee')
            elif self.clock()-row['created']>90:self.update(row['id'],'unknown','confirmation_deadline_elapsed')
