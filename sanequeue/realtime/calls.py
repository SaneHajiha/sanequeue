"""Bounded observed call ledger. No CDR scans, per-request AMI or audio capture."""
import asyncio
from collections import OrderedDict,deque
from datetime import datetime,time as day_time,timedelta
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import time
from zoneinfo import ZoneInfo

from .local_inventory import read_snapshot


def numeric(value):
    try:return max(0,min(86400,float(value)))
    except (TypeError,ValueError,OverflowError):return 0


class CallStore:
    def __init__(self,path):self.path=Path(path)

    def write(self,rows,observed):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        db=sqlite3.connect(self.path,timeout=2)
        try:
            os.chmod(self.path,0o600);db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''CREATE TABLE IF NOT EXISTS calls (
              call_key TEXT,queue TEXT,agent TEXT,direction TEXT,number TEXT,started REAL,answered REAL,ended REAL,
              talk_seconds REAL,wait_seconds REAL,hold_seconds REAL,end_party TEXT,reason TEXT,incomplete INTEGER,
              within_sla INTEGER,PRIMARY KEY(call_key,queue));
              CREATE INDEX IF NOT EXISTS call_period ON calls(queue,agent,started);
              CREATE INDEX IF NOT EXISTS call_end ON calls(ended);
              CREATE TABLE IF NOT EXISTS coverage(id INTEGER PRIMARY KEY,since REAL,observed REAL);''')
            with db:
                db.execute('BEGIN IMMEDIATE')
                meta=db.execute('SELECT observed FROM coverage WHERE id=1').fetchone()
                if meta and meta[0]>observed:return
                for row in rows:
                    fields=('call_key','queue','agent','direction','number','started','answered','ended','talk_seconds','wait_seconds','hold_seconds','end_party','reason','incomplete','within_sla')
                    db.execute('INSERT OR IGNORE INTO calls VALUES ('+','.join('?' for _ in fields)+')',tuple(row[k] for k in fields))
                db.execute('INSERT OR IGNORE INTO coverage VALUES (1,?,?)',(observed,observed))
                db.execute('UPDATE coverage SET observed=? WHERE id=1',(observed,))
                db.execute('DELETE FROM calls WHERE ended<?',(observed-90*86400,))
                db.execute('DELETE FROM calls WHERE rowid<(SELECT COALESCE(MAX(rowid),0)-500000 FROM calls)')
        finally:db.close()

    def daily(self,queues,day,*,agents=None,not_before=0,details=True):
        result={'rows':[],'since':None,'observed_until':None,'complete_history':False,'limited':False}
        if not self.path.exists() or not queues:return result
        zone=ZoneInfo('Asia/Tehran');date=datetime.strptime(day,'%Y-%m-%d').date()
        start=max(datetime.combine(date,day_time(),zone).timestamp(),float(not_before))
        end=datetime.combine(date+timedelta(days=1),day_time(),zone).timestamp()
        db=sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True,timeout=2);db.row_factory=sqlite3.Row
        try:
            meta=db.execute('SELECT since,observed FROM coverage WHERE id=1').fetchone()
            if meta:result.update(since=meta['since'],observed_until=meta['observed'])
            args=[*sorted(set(queues)),start,end]
            sql='SELECT * FROM calls WHERE queue IN ('+','.join('?' for _ in set(queues))+') AND started>=? AND started<?'
            if agents is not None:
                if not agents:return result
                sql+=' AND agent IN ('+','.join('?' for _ in agents)+')';args.extend(agents)
            # Totals are bounded by retained observations, not just the detail page.
            # SQL aggregates avoid materializing hundreds of thousands of rows per dashboard read.
            source=sql.replace('SELECT * FROM calls','FROM calls',1)
            aggregate="SELECT queue,agent,SUM(direction='inbound' AND answered IS NOT NULL) AS answered,SUM(direction='inbound' AND answered IS NULL) AS abandoned,SUM(CASE WHEN direction='inbound' THEN talk_seconds ELSE 0 END) AS talk_seconds,SUM(CASE WHEN direction='inbound' AND answered IS NOT NULL THEN wait_seconds ELSE 0 END) AS wait_seconds,SUM(direction='inbound' AND end_party='caller') AS caller_hangup,SUM(direction='inbound' AND end_party='agent') AS agent_hangup,SUM(direction='inbound' AND end_party NOT IN ('caller','agent')) AS unknown_hangup,SUM(direction='inbound' AND answered IS NOT NULL AND within_sla IS NOT NULL) AS sla_known,SUM(CASE WHEN direction='inbound' AND answered IS NOT NULL THEN COALESCE(within_sla,0) ELSE 0 END) AS sla_met "
            result['summaries']=[dict(r) for r in db.execute(aggregate+source+' GROUP BY queue,agent',args)]
            if details:
                rows=[dict(r) for r in db.execute(sql+' ORDER BY started DESC LIMIT 1001',args)]
                result['limited']=len(rows)>1000;result['rows']=rows[:1000]
            return result
        finally:db.close()


class CallRecorder:
    def __init__(self,store,inventory_path='/run/sanequeue/inventory.json'):
        self.store=store;self.inventory_path=inventory_path;self.phones={};self.active={};self.links={};self.queue_roots=OrderedDict();self.waiting={};self.pending=deque();self.observed=0;self.dropped=0
        self.refresh_inventory()

    def refresh_inventory(self):
        inventory=read_snapshot(self.inventory_path)
        if inventory:
            self.phones={r['technology']+'/'+r['endpoint']:r['endpoint'] for r in inventory['endpoints'] if r['category']=='extension'}

    def phone(self,channel):
        if channel in self.phones:return channel
        base=re.sub(r'-[0-9a-fA-F]{4,}$','',channel or '')
        if base in self.phones:return base
        match=re.fullmatch(r'Local/([A-Za-z0-9_.-]+)@[^/]+(?:/n)?',channel or '')
        if match:
            found=[p for p,v in self.phones.items() if v==match[1]]
            if len(found)==1:return found[0]
        return channel if channel.startswith('Local/') else ''

    def emit(self,record):
        if len(self.pending)>=10000:self.dropped+=1;return
        self.pending.append(record)

    def ingest(self,event,queues,now=None):
        e={str(k).lower():str(v) for k,v in event.items()};kind=e.get('event','').lower();now=time.time() if now is None else now;self.observed=now
        uid=e.get('uniqueid','');root=e.get('linkedid',uid);queue=e.get('queue','');agent=self.phone(e.get('interface','')) or e.get('interface','')
        if kind=='queuecallerjoin':
            self.queue_roots[root]=now;self.queue_roots.move_to_end(root)
            self.waiting[(queue,uid)]=(now,e.get('calleridnum',''))
            while len(self.queue_roots)>5000:self.queue_roots.popitem(last=False)
            while len(self.waiting)>5000:self.waiting.pop(next(iter(self.waiting)))
        if kind=='agentconnect' and queue and uid:
            key=('in',queue,uid);start,number=self.waiting.pop((queue,uid),(now-numeric(e.get('holdtime')),e.get('calleridnum','')))
            if len(self.active)<5000:self.active[key]=dict(call_key=hashlib.sha256(('in:'+queue+':'+uid+':'+e.get('destuniqueid','')).encode()).hexdigest(),queue=queue,agent=agent,direction='inbound',number=number or e.get('calleridnum',''),started=start,answered=now,ended=now,talk_seconds=0,wait_seconds=numeric(e.get('holdtime')),hold_seconds=0,end_party='unknown',reason='',incomplete=0)
        if kind in ('agentcomplete','queuecallerabandon') and queue and uid:
            record=self.active.pop(('in',queue,uid),None)
            if record is None:
                start,number=self.waiting.pop((queue,uid),(now-numeric(e.get('talktime'))-numeric(e.get('holdtime')),e.get('calleridnum','')))
                record=dict(call_key=hashlib.sha256(('in:'+queue+':'+uid+':'+e.get('destuniqueid','')).encode()).hexdigest(),queue=queue,agent=agent,direction='inbound',number=number,started=start,answered=now-numeric(e.get('talktime')) if kind=='agentcomplete' else None,hold_seconds=0,reason='',incomplete=1)
            record.update(ended=now,talk_seconds=numeric(e.get('talktime')),wait_seconds=numeric(e.get('holdtime')),end_party=e.get('reason') if e.get('reason') in ('caller','agent') else 'caller' if kind=='queuecallerabandon' else 'unknown')
            limit=queues.get(queue,{}).get('params',{}).get('servicelevel')
            record['within_sla']=int(record['wait_seconds']<=numeric(limit)) if limit is not None and kind=='agentcomplete' else None
            self.emit(record)
        if kind=='dialbegin' and root not in self.queue_roots:
            phone=self.phone(e.get('channel',''))
            if phone not in self.phones or not uid:return
            memberships={}
            for q,data in queues.items():
                for interface,m in data.get('members',{}).items():
                    if self.phone(interface)==phone and str(m.get('paused','0')).lower() in ('1','true') and m.get('pausedreason'):
                        memberships[q]=str(m['pausedreason'])[:100]
            if not memberships:return
            dial=e.get('dialstring','').split(',',1)[0];number=dial.rsplit('/',1)[-1].split('@',1)[0]
            if not re.fullmatch(r'\+?[0-9]{2,20}',number):number=e.get('destcalleridnum','')
            if not re.fullmatch(r'\+?[0-9]{2,20}',number):number=''
            key=('out',uid)
            if key not in self.active and len(self.active)<5000:
                self.active[key]=dict(call_key=hashlib.sha256(('out:'+uid).encode()).hexdigest(),agent=phone,direction='outbound',number=number,started=now,answered=None,ended=now,talk_seconds=0,wait_seconds=0,hold_seconds=0,end_party='unknown',incomplete=0,memberships=memberships)
            dest=e.get('destuniqueid')
            if dest and len(self.links)<10000:self.links[dest]=uid
        out_uid=uid if ('out',uid) in self.active else self.links.get(uid)
        record=self.active.get(('out',out_uid))
        if record:
            if (kind=='dialend' and e.get('dialstatus')=='ANSWER') or kind=='bridgeenter':record['answered']=record['answered'] or now
            if kind=='hold':record.setdefault('held_since',now)
            if kind=='unhold' and record.get('held_since') is not None:record['hold_seconds']+=max(0,now-record.pop('held_since'))
            if kind=='hangup' and uid==out_uid:
                self.active.pop(('out',out_uid),None);record['ended']=now
                record['talk_seconds']=max(0,now-record['answered']) if record['answered'] else 0
                if record.get('held_since') is not None:record['hold_seconds']+=max(0,now-record.pop('held_since'))
                for q,reason in record.pop('memberships').items():self.emit(dict(record,queue=q,reason=reason,within_sla=None))
                self.links={k:v for k,v in self.links.items() if v!=out_uid}

    def disconnected(self):
        # Calls crossing a disconnect cannot establish complete duration or party.
        self.active.clear();self.links.clear();self.waiting.clear();self.queue_roots.clear()

    async def flush(self):
        rows=list(self.pending);self.pending.clear()
        try:
            await asyncio.to_thread(self.refresh_inventory)
            await asyncio.to_thread(self.store.write,rows,self.observed or time.time())
        except (OSError,sqlite3.Error):
            if len(rows)+len(self.pending)<=10000:self.pending.extendleft(reversed(rows))
            else:self.dropped+=len(rows)
