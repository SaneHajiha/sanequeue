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
              CREATE TABLE IF NOT EXISTS delivery_cooldowns(queue TEXT,type TEXT,provider TEXT,last REAL,PRIMARY KEY(queue,type,provider));
            ''')
            columns={r[1] for r in db.execute('PRAGMA table_info(deliveries)')}
            if 'provider' not in columns:
                db.execute("ALTER TABLE deliveries ADD COLUMN provider TEXT NOT NULL DEFAULT 'bale'")

    def observe(self,alerts,policies,*,delivery_enabled=False,system_rules=None):
        now=self.clock()
        enabled={'bale'} if delivery_enabled is True else set(delivery_enabled or ())
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('UPDATE alert_state SET active=0')
            for alert in alerts:
                queue,kind=alert['queue'],alert['type']
                safe={k:alert[k] for k in ('queue','type','value','threshold','label','scope') if k in alert}
                payload=json.dumps(safe,ensure_ascii=False)
                rules=system_rules if alert.get('scope')=='system' else policies.queue(queue)['alerts']
                if not rules:continue
                # Each trunk gets its own debounce/cooldown identity.
                if alert.get('scope')=='system':
                    import hashlib
                    kind=kind+':'+hashlib.sha256(str(alert.get('label','')).encode()).hexdigest()[:12]
                row=db.execute('SELECT last_enqueued FROM alert_state WHERE queue=? AND type=?',(queue,kind)).fetchone()
                last=row[0] if row else -1e20
                for provider in sorted(enabled & {'telegram','bale'}):
                    if not rules.get(provider+'_enabled'):continue
                    previous=db.execute('SELECT last FROM delivery_cooldowns WHERE queue=? AND type=? AND provider=?',(queue,kind,provider)).fetchone()
                    # Preserve the old Bale cooldown when upgrading an existing ledger.
                    provider_last=previous[0] if previous else last if provider=='bale' else -1e20
                    if now-provider_last<rules['cooldown_seconds']:continue
                    ident=secrets.token_hex(16)
                    db.execute('INSERT INTO deliveries(id,queue,type,payload,state,attempts,next_at,lease,lease_until,updated,provider) VALUES (?,?,?,?,?,?,?,?,?,?,?)',(ident,queue,kind,payload,'pending',0,now,'',0,now,provider))
                    db.execute('INSERT OR REPLACE INTO delivery_cooldowns VALUES (?,?,?,?)',(queue,kind,provider,now))
                    if provider=='bale':last=now
                db.execute('INSERT OR REPLACE INTO alert_state VALUES (?,?,?,?,?)',(queue,kind,payload,1,last))
            db.execute("UPDATE deliveries SET state='cancelled',updated=? WHERE state='pending' AND NOT EXISTS (SELECT 1 FROM alert_state a WHERE a.queue=deliveries.queue AND a.type=deliveries.type AND a.active=1)",(now,))
            # Keep a bounded operational ledger; never delete pending deliveries.
            db.execute("DELETE FROM deliveries WHERE state IN ('sent','failed','cancelled') AND updated<?",(now-7*86400,))
            db.execute("DELETE FROM deliveries WHERE id IN (SELECT id FROM deliveries WHERE state IN ('sent','failed','cancelled') ORDER BY updated DESC LIMIT -1 OFFSET 5000)")
            count=db.execute("SELECT COUNT(*) FROM deliveries WHERE state IN ('pending','sending')").fetchone()[0]
            if count>1000:
                db.execute("UPDATE deliveries SET state='failed',updated=? WHERE id IN (SELECT id FROM deliveries WHERE state='pending' ORDER BY next_at LIMIT ?)",(now,count-1000))

    def claim(self,enabled=None):
        now=self.clock();token=secrets.token_hex(16)
        providers=sorted({'bale','telegram'} if enabled is None else set(enabled)&{'bale','telegram'})
        if not providers:return None
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            slots=','.join('?' for _ in providers)
            row=db.execute("SELECT * FROM deliveries WHERE ((state='pending' AND next_at<=?) OR (state='sending' AND lease_until<?)) AND provider IN ("+slots+") ORDER BY next_at LIMIT 1",(now,now,*providers)).fetchone()
            if row is None:return None
            db.execute("UPDATE deliveries SET state='sending',lease=?,lease_until=?,updated=? WHERE id=?",(token,now+30,now,row['id']))
            return dict(id=row['id'],token=token,payload=json.loads(row['payload']),attempts=row['attempts'],provider=row['provider'])

    def finish(self,job,success):
        now=self.clock();attempts=job['attempts']+1
        state='sent' if success else 'failed' if attempts>=6 else 'pending'
        with self.db() as db:
            db.execute('UPDATE deliveries SET state=?,attempts=?,next_at=?,lease=?,lease_until=0,updated=? WHERE id=? AND lease=?',
                       (state,attempts,now+min(120,2**attempts),'',now,job['id'],job['token']))

    def report(self,allowed,include_system=False):
        names=list(allowed)+(['__system__'] if include_system else [])
        if not names:return dict(alerts=[],notification_status={'sent':0,'failed':0,'pending':0})
        slots=','.join('?' for _ in names)
        with self.db() as db:
            alerts=[json.loads(r[0]) for r in db.execute('SELECT payload FROM alert_state WHERE active=1 AND queue IN ('+slots+')',names)]
            counts={r[0]:r[1] for r in db.execute('SELECT state,COUNT(*) FROM deliveries WHERE queue IN ('+slots+') GROUP BY state',names)}
        return dict(alerts=alerts,notification_status=dict(sent=counts.get('sent',0),failed=counts.get('failed',0),
                    pending=counts.get('pending',0)+counts.get('sending',0)))
