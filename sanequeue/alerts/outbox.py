"""At-least-once notification attempts; no tokens or caller data in SQLite."""
import json
import secrets
import time
from sanequeue.actions.ledger import ActionLedger


class AlertOutbox(ActionLedger):
    def __init__(self,path,**kwargs):
        super().__init__(path,**kwargs)
        with self.db() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS alert_state(queue TEXT,type TEXT,payload TEXT,active INTEGER,last_enqueued REAL,PRIMARY KEY(queue,type));
              CREATE TABLE IF NOT EXISTS deliveries(id TEXT PRIMARY KEY,queue TEXT,type TEXT,payload TEXT,state TEXT,attempts INTEGER,next_at REAL,lease TEXT,lease_until REAL,updated REAL);
              CREATE INDEX IF NOT EXISTS deliveries_due ON deliveries(state,next_at);
            ''')

    def observe(self,alerts,policies,*,delivery_enabled=False):
        now=self.clock()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('UPDATE alert_state SET active=0')
            for alert in alerts:
                queue,kind=alert['queue'],alert['type']
                safe={k:alert[k] for k in ('queue','type','value','threshold','label') if k in alert}
                payload=json.dumps(safe,ensure_ascii=False)
                rules=policies.queue(queue)['alerts']
                row=db.execute('SELECT last_enqueued FROM alert_state WHERE queue=? AND type=?',(queue,kind)).fetchone()
                last=row[0] if row else -1e20
                if delivery_enabled and rules.get('bale_enabled') and now-last>=rules['cooldown_seconds']:
                    ident=secrets.token_hex(16)
                    db.execute('INSERT INTO deliveries VALUES (?,?,?,?,?,?,?,?,?,?)',(ident,queue,kind,payload,'pending',0,now,'',0,now))
                    last=now
                db.execute('INSERT OR REPLACE INTO alert_state VALUES (?,?,?,?,?)',(queue,kind,payload,1,last))
            db.execute("UPDATE deliveries SET state='cancelled',updated=? WHERE state='pending' AND NOT EXISTS (SELECT 1 FROM alert_state a WHERE a.queue=deliveries.queue AND a.type=deliveries.type AND a.active=1)",(now,))
            # Keep a bounded operational ledger; never delete pending deliveries.
            db.execute("DELETE FROM deliveries WHERE state IN ('sent','failed','cancelled') AND updated<?",(now-7*86400,))
            db.execute("DELETE FROM deliveries WHERE id IN (SELECT id FROM deliveries WHERE state IN ('sent','failed','cancelled') ORDER BY updated DESC LIMIT -1 OFFSET 5000)")
            count=db.execute("SELECT COUNT(*) FROM deliveries WHERE state IN ('pending','sending')").fetchone()[0]
            if count>1000:
                db.execute("UPDATE deliveries SET state='failed',updated=? WHERE id IN (SELECT id FROM deliveries WHERE state='pending' ORDER BY next_at LIMIT ?)",(now,count-1000))

    def claim(self):
        now=self.clock();token=secrets.token_hex(16)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute("SELECT * FROM deliveries WHERE (state='pending' AND next_at<=?) OR (state='sending' AND lease_until<?) ORDER BY next_at LIMIT 1",(now,now)).fetchone()
            if row is None:return None
            db.execute("UPDATE deliveries SET state='sending',lease=?,lease_until=?,updated=? WHERE id=?",(token,now+30,now,row['id']))
            return dict(id=row['id'],token=token,payload=json.loads(row['payload']),attempts=row['attempts'])

    def finish(self,job,success):
        now=self.clock();attempts=job['attempts']+1
        state='sent' if success else 'failed' if attempts>=6 else 'pending'
        with self.db() as db:
            db.execute('UPDATE deliveries SET state=?,attempts=?,next_at=?,lease=?,lease_until=0,updated=? WHERE id=? AND lease=?',
                       (state,attempts,now+min(120,2**attempts),'',now,job['id'],job['token']))

    def report(self,allowed):
        names=list(allowed)
        if not names:return dict(alerts=[],notification_status={'sent':0,'failed':0,'pending':0})
        slots=','.join('?' for _ in names)
        with self.db() as db:
            alerts=[json.loads(r[0]) for r in db.execute('SELECT payload FROM alert_state WHERE active=1 AND queue IN ('+slots+')',names)]
            counts={r[0]:r[1] for r in db.execute('SELECT state,COUNT(*) FROM deliveries WHERE queue IN ('+slots+') GROUP BY state',names)}
        return dict(alerts=alerts,notification_status=dict(sent=counts.get('sent',0),failed=counts.get('failed',0),
                    pending=counts.get('pending',0)+counts.get('sending',0)))
