"""Bounded internal callback dispatch, using cached channel state and no retry after uncertain send."""
import hashlib,json,os
from pathlib import Path
import re,sqlite3,stat,time
from contextlib import contextmanager

from sanequeue.actions.transport import send_action
from sanequeue.realtime.local_inventory import read_snapshot
from .features import FeatureStore


class CallbackWorker:
    def __init__(self,state,spool='/var/spool/asterisk/sanequeue',*,expected_uid=None,send=send_action):
        self.state=Path(state);self.spool=Path(spool);self.path=self.state/'callbacks.sqlite3';self.send=send;self.last_dispatch=0
        if expected_uid is None and os.name!='nt':
            import pwd
            try:expected_uid=pwd.getpwnam('asterisk').pw_uid
            except KeyError:expected_uid=-1
        self.expected_uid=expected_uid
    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=2);db.row_factory=sqlite3.Row
        if os.name!='nt':os.chmod(self.path,0o600)
        db.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,source TEXT,target TEXT,created REAL,expires REAL,state TEXT,action_id TEXT,updated REAL)')
        existing={r[1] for r in db.execute('PRAGMA table_info(jobs)')}
        for name in ('answered_at','connected_at','ended_at','talk_seconds'):
            if name not in existing:db.execute('ALTER TABLE jobs ADD COLUMN '+name+' REAL')
        try:
            with db:yield db
        finally:db.close()
    def ingest(self,phones,now):
        with self.db() as db:
            for path in list(self.spool.glob('job-*.json'))[:20]:
                if not re.fullmatch(r'job-[a-f0-9]{32}\.json',path.name):continue
                try:
                    fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0))
                    with os.fdopen(fd,'rb') as stream:
                        metadata=os.fstat(stream.fileno())
                        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink!=1 or metadata.st_size>1024 or (self.expected_uid is not None and metadata.st_uid!=self.expected_uid):continue
                        row=json.loads(stream.read(1025))
                    if row['id']!=path.stem[4:] or row['source'] not in phones or row['target'] not in phones.values():continue
                    if not isinstance(row['created'],(int,float)) or not isinstance(row['expires'],(int,float)) or not 0<row['expires']-row['created']<=1800 or row['created']>now+5:continue
                    count=db.execute("SELECT COUNT(*) FROM jobs WHERE state='pending'").fetchone()[0]
                    if count>=200:continue
                    duplicate=db.execute("SELECT 1 FROM jobs WHERE source=? AND target=? AND state IN ('pending','dispatching','accepted') AND expires>?",(row['source'],row['target'],now)).fetchone()
                    db.execute('INSERT OR IGNORE INTO jobs(id,source,target,created,expires,state,action_id,updated) VALUES (?,?,?,?,?,?,?,?)',(row['id'],row['source'],row['target'],row['created'],row['expires'],'duplicate' if duplicate else 'pending','',now))
                except (OSError,ValueError,KeyError,TypeError):continue
                finally:
                    # Only remove the owned, fixed-format request filename.
                    try:path.unlink(missing_ok=True)
                    except OSError:pass
            db.execute("UPDATE jobs SET state='expired',updated=? WHERE state='pending' AND expires<=?",(now,now))
            db.execute("UPDATE jobs SET state='unknown',updated=? WHERE state='dispatching' AND updated<?",(now,now-30))
            db.execute("DELETE FROM jobs WHERE state NOT IN ('pending','dispatching') AND updated<?",(now-30*86400,))
    def tick(self,state,now=None):
        now=time.time() if now is None else now
        if not self.spool.exists() or (self.spool/'disabled').exists():return
        settings=FeatureStore(self.state).read()
        if not settings['callback']['enabled']:return
        inventory=read_snapshot('/run/sanequeue/inventory.json')
        if inventory is None:return
        phones={r['technology']+'/'+r['endpoint']:r['endpoint'] for r in inventory['endpoints'] if r['category']=='extension'}
        reachable={r['technology']+'/'+r['endpoint'] for r in inventory['endpoints'] if r['category']=='extension' and r.get('reachable')}
        self.ingest(phones,now)
        with self.db() as db:
            for row in db.execute("SELECT id,action_id,updated,state,connected_at FROM jobs WHERE state IN ('accepted','caller_answered','connected')").fetchall():
                event=state.get('action_events',{}).get(row['action_id'],{})
                if event.get('response','').lower()=='failure':
                    db.execute("UPDATE jobs SET state='failed',updated=? WHERE id=?",(now,row['id']));continue
                if event.get('response','').lower()=='success':
                    answered=event.get('observed_at') or now;connected=event.get('connected_at');ended=event.get('ended_at')
                    disappeared=bool(event.get('uniqueid') and event['uniqueid'] not in state.get('channels',{}) and now-answered>5)
                    status='completed' if ended and connected else 'ended_unverified' if ended else 'connected' if connected else 'ended_unverified' if disappeared else 'caller_answered'
                    db.execute('UPDATE jobs SET state=?,answered_at=COALESCE(answered_at,?),connected_at=COALESCE(connected_at,?),ended_at=?,talk_seconds=?,updated=? WHERE id=?',(status,answered,connected,ended,max(0,ended-connected) if ended and connected else None,now,row['id']))
                elif row['state']=='accepted' and now-row['updated']>35:db.execute("UPDATE jobs SET state='unknown',updated=? WHERE id=?",(now,row['id']))
                elif row['state'] in ('caller_answered','connected') and now-row['updated']>1800:db.execute("UPDATE jobs SET state='unknown',updated=? WHERE id=?",(now,row['id']))
        try:applied=json.loads(Path('/run/sanequeue/pbx-status.json').read_text())
        except (OSError,ValueError):return
        fingerprint=hashlib.sha256(json.dumps(settings,sort_keys=True).encode()).hexdigest()
        if not applied.get('applied') or applied.get('requested_hash')!=fingerprint:return
        if not state.get('channels_complete') or now-self.last_dispatch<settings['callback']['retry_seconds']:return
        channels=[str(c.get('channel','')) for c in state.get('channels',{}).values()]
        busy=lambda phone:any(c==phone or c.startswith(phone+'-') for c in channels)
        selected=None
        with self.db() as db:
            for row in db.execute("SELECT * FROM jobs WHERE state='pending' AND expires>? ORDER BY created LIMIT 200",(now,)):
                targets=[phone for phone,number in phones.items() if number==row['target']]
                if row['source'] not in reachable or len(targets)!=1 or targets[0] not in reachable or busy(row['source']) or busy(targets[0]):continue
                selected=dict(row);break
            if not selected:return
            action_id='sq-cb-'+selected['id']
            updated=db.execute("UPDATE jobs SET state='dispatching',action_id=?,updated=? WHERE id=? AND state='pending'",(action_id,now,selected['id']))
            if updated.rowcount!=1:return
        self.last_dispatch=now
        fields=dict(Variable='__SANEQUEUE_CALLBACK=1',Channel=selected['source'],Context='from-internal',Exten=selected['target'],Priority='1',Timeout='25000',Async='true',CallerID='Callback '+selected['target']+' <'+phones[selected['source']]+'>')
        try:status='accepted' if self.send('/etc/sanequeue/control.ini','Originate',fields,action_id) else 'rejected'
        except Exception:status='unknown'
        with self.db() as db:db.execute('UPDATE jobs SET state=?,updated=? WHERE id=?',(status,now,selected['id']))


def report(path):
    path=Path(path)
    if not path.exists():return []
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2);db.row_factory=sqlite3.Row
    try:
        names={r[1] for r in db.execute('PRAGMA table_info(jobs)')}
        extra=','.join(name if name in names else 'NULL AS '+name for name in ('answered_at','connected_at','ended_at','talk_seconds'))
        return [dict(row) for row in db.execute('SELECT source,target,created,expires,state,updated,'+extra+' FROM jobs ORDER BY created DESC LIMIT 100')]
    finally:db.close()
