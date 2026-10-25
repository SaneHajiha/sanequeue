"""Indexed, read-only SQL ingestion. Never imported or invoked by HTTP routes.

CEL advances by its indexed integer ID. CDR history advances by complete
timestamp groups; ended CEL identities also trigger indexed CDR lookups so a
long call is not missed merely because its start time precedes the watermark.
"""
import configparser
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import time
from zoneinfo import ZoneInfo
from .sources import sql_event

FIELDS={
 'cdr':('calldate','clid','src','dst','dcontext','channel','dstchannel','lastapp','lastdata',
        'duration','billsec','disposition','uniqueid','linkedid','sequence','did','recordingfile'),
 'cel':('id','eventtype','eventtime','channame','uniqueid','linkedid','peer','eventextra','context','appname','appdata')}


def identifier(value):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}',value):
        raise ValueError('invalid_reporting_sql_identifier')
    return '`'+value+'`'


def cdr_page(rows,limit):
    """Do not skip rows sharing the last timestamp when no integer PK exists."""
    if len(rows)<=limit:return rows
    boundary=rows[-1]['calldate']
    complete=[row for row in rows if row['calldate']<boundary]
    if not complete:
        raise ValueError('cdr_timestamp_density_exceeds_batch')
    return complete


class SQLSource:
    def __init__(self,config,*,connect=None):
        self.config=dict(config)
        self.database=identifier(self.config.get('database','asteriskcdrdb'))
        self.tables={name:identifier(self.config.get(name+'_table',name)) for name in FIELDS}
        self.generation=self.config.get('generation','')
        if not re.fullmatch(r'[A-Za-z0-9_-]{0,32}',self.generation):raise ValueError('invalid_sql_generation')
        self.timezone=self.config.get('timezone','Asia/Tehran')
        self.connect_factory=connect or self._connect
        self.schema={}

    @classmethod
    def from_file(cls,path):
        path=Path(path)
        if path.is_symlink() or not path.is_file():raise ValueError('invalid_sql_config_file')
        if os.name!='nt' and path.stat().st_mode & 0o027:raise ValueError('sql_config_permissions')
        cfg=configparser.ConfigParser(interpolation=None);cfg.read(path)
        return cls(dict(cfg['reporting']))

    def _connect(self):
        import pymysql
        host=self.config.get('host','127.0.0.1')
        if host not in ('localhost','127.0.0.1','::1'):
            raise ValueError('reporting_sql_requires_local_host')
        return pymysql.connect(host=host,port=int(self.config.get('port',3306)),
                               user=self.config['user'],password=self.config['password'],
                               unix_socket=self.config.get('unix_socket') or None,
                               charset='utf8mb4',autocommit=True,connect_timeout=3,
                               read_timeout=2,write_timeout=2,local_infile=False,
                               cursorclass=pymysql.cursors.DictCursor)

    def _table(self,source):return self.database+'.'+self.tables[source]

    def _columns(self,cursor,source):
        if source not in self.schema:
            cursor.execute('SHOW COLUMNS FROM '+self._table(source))
            definitions=cursor.fetchall()
            fields={row['Field'] for row in definitions}
            if source=='cel' and not any(row['Field']=='id' and re.match(r'(?:big|medium|small|tiny)?int\b',row.get('Type',''),re.I) for row in definitions):
                raise ValueError('reporting_cel_integer_id_required')
            required={'id','eventtime','eventtype','uniqueid'} if source=='cel' else {'calldate','uniqueid'}
            if not required.issubset(fields):raise ValueError('reporting_source_schema_missing_fields')
            cursor.execute('SHOW INDEX FROM '+self._table(source))
            indexed={row['Column_name'] for row in cursor.fetchall() if int(row['Seq_in_index'])==1}
            if ('id' if source=='cel' else 'calldate') not in indexed:
                raise ValueError('reporting_source_index_required')
            if source=='cdr' and ('uniqueid' not in indexed or 'linkedid' in fields and 'linkedid' not in indexed):
                raise ValueError('reporting_cdr_identity_index_required')
            self.schema[source]=fields
        return ','.join(identifier(name) if name in self.schema[source] else 'NULL AS '+identifier(name) for name in FIELDS[source])

    def _event(self,source,row):
        event=sql_event(source,row,timezone=self.timezone)
        if self.generation:
            from .store import Event
            event=Event(event.source,self.generation+':'+event.key,event.timestamp,event.kind,event.payload)
        return event

    @staticmethod
    def _anchor(event):
        return hashlib.sha256(json.dumps(event.payload,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()

    def ingest(self,archive,*,limit=250,now=None):
        limit=max(1,min(500,int(limit)));now=time.time() if now is None else float(now)
        name='sql:cel:'+self.generation
        checkpoint=archive.checkpoint(name)
        connection=self.connect_factory()
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT VERSION() AS version');version=str(cursor.fetchone()['version'])
                cursor.execute('SET SESSION TRANSACTION READ ONLY')
                cursor.execute('SET SESSION max_statement_time=1' if 'mariadb' in version.lower() else 'SET SESSION max_execution_time=1000')
                self._columns(cursor,'cdr')
                columns=self._columns(cursor,'cel');after=int(checkpoint.get('after_id',0))
                if after:
                    cursor.execute('SELECT '+columns+' FROM '+self._table('cel')+' WHERE `id`=%s',(after,))
                    anchor=cursor.fetchone()
                    if anchor is None or self._anchor(self._event('cel',anchor))!=checkpoint.get('anchor'):
                        raise ValueError('cel_source_reset_requires_new_generation')
                cursor.execute('SELECT '+columns+' FROM '+self._table('cel')+' WHERE `id`>%s ORDER BY `id` LIMIT %s',(after,limit))
                rows=cursor.fetchall();events=[self._event('cel',row) for row in rows]
                identities={str((row.get('linkedid') if 'linkedid' in self.schema['cdr'] else '') or row.get('uniqueid') or '') for row in rows if str(row['eventtype']).upper() in ('CHAN_END','LINKEDID_END','HANGUP')}-{''}
                if any(len(uid)>256 for uid in identities):raise ValueError('sql_identity_limit')
                def enqueue(db):
                    count=db.execute('SELECT COUNT(*) FROM sql_cdr_pending WHERE pbx=?',(archive.pbx,)).fetchone()[0]
                    for uid in identities:
                        exists=db.execute('SELECT 1 FROM sql_cdr_pending WHERE pbx=? AND uid=?',(archive.pbx,uid)).fetchone()
                        if not exists:
                            if count>=20000:raise ValueError('cdr_pending_capacity')
                            count+=1
                        db.execute('''INSERT INTO sql_cdr_pending VALUES(?,?,?,?,?) ON CONFLICT(pbx,uid)
                          DO UPDATE SET due=MIN(due,excluded.due)''',(archive.pbx,uid,now+2,0,now))
                value=dict(after_id=int(rows[-1]['id']) if rows else after,
                           anchor=self._anchor(events[-1]) if events else checkpoint.get('anchor'),observed=now)
                inserted=archive.append(events,checkpoint_source=name,checkpoint=value,update_state=enqueue)
                result=dict(cel_inserted=inserted,cel_rows=len(rows),cel_caught_up=len(rows)<limit)
                result.update(self._cdr_backfill(cursor,archive,limit,now))
                result.update(self._cdr_pending(cursor,archive,now))
                if result['cdr_caught_up']:
                    result.update(self._cdr_overlap(cursor,archive,limit,now))
                return result
        finally:
            connection.close()

    def _cdr_backfill(self,cursor,archive,limit,now):
        name='sql:cdr:'+self.generation
        previous=archive.checkpoint(name)
        after=previous.get('after_time','1900-01-01 00:00:00')
        columns=self._columns(cursor,'cdr')
        cursor.execute('SELECT '+columns+' FROM '+self._table('cdr')+' WHERE `calldate`>%s ORDER BY `calldate` LIMIT %s',(after,limit+1))
        rows=cursor.fetchall();complete=cdr_page(rows,limit)
        value=dict(after_time=complete[-1]['calldate'].isoformat(sep=' ') if complete else after,
                   observed=now,caught_up=len(rows)<=limit,late_rows_strategy='cel_end_identity_lookup')
        inserted=archive.append([self._event('cdr',row) for row in complete],checkpoint_source=name,checkpoint=value)
        return dict(cdr_inserted=inserted,cdr_rows=len(complete),cdr_caught_up=len(rows)<=limit)

    def _cdr_pending(self,cursor,archive,now):
        with archive.reader() as db:
            pending=[dict(row) for row in db.execute('SELECT uid,attempts,created FROM sql_cdr_pending WHERE pbx=? AND due<=? ORDER BY created DESC LIMIT 20',(archive.pbx,now))]
        if not pending:return dict(cdr_lookups=0)
        identities=[row['uid'] for row in pending];events={}
        for column in ('uniqueid','linkedid'):
            if column not in self.schema['cdr']:continue
            cursor.execute('SELECT '+self._columns(cursor,'cdr')+' FROM '+self._table('cdr')+' WHERE '+identifier(column)+' IN ('+','.join('%s' for _ in identities)+') LIMIT 501',identities)
            rows=cursor.fetchall()
            if len(rows)>500:raise ValueError('cdr_identity_fanout_limit')
            for row in rows:
                event=self._event('cdr',row);events[event.key]=event
        def finish(db):
            for row in pending:
                # Recheck after initial success: another CDR leg/recording
                # reference can be committed shortly after the first one.
                if row['attempts']>=3 and any(row['uid'] in (e.payload.get('uniqueid'),e.payload.get('linkedid')) for e in events.values()):
                    db.execute('DELETE FROM sql_cdr_pending WHERE pbx=? AND uid=?',(archive.pbx,row['uid']))
                elif now-row['created']>=86400:
                    # Retain an explicit unresolved record instead of an
                    # unbounded hot retry queue. Raw CEL is never removed.
                    db.execute('INSERT OR REPLACE INTO sql_cdr_unresolved VALUES(?,?,?,?,?)',
                               (archive.pbx,row['uid'],row['attempts'],now,'no_cdr_after_24h'))
                    db.execute('DELETE FROM sql_cdr_pending WHERE pbx=? AND uid=?',(archive.pbx,row['uid']))
                else:
                    delay=min(3600,5*2**min(10,row['attempts']))
                    db.execute('UPDATE sql_cdr_pending SET attempts=attempts+1,due=? WHERE pbx=? AND uid=?',(now+delay,archive.pbx,row['uid']))
        inserted=archive.append(events.values(),update_state=finish)
        return dict(cdr_lookups=len(pending),cdr_lookup_inserted=inserted)

    def _cdr_overlap(self,cursor,archive,limit,now):
        """Reconcile late CDR commits in a bounded 24-hour indexed window."""
        name='sql:cdr_overlap:'+self.generation
        previous=archive.checkpoint(name)
        if now<float(previous.get('next_scan',0)):return dict(cdr_overlap_deferred=True)
        zone=ZoneInfo(self.timezone)
        local=lambda stamp:datetime.fromtimestamp(stamp,zone).replace(tzinfo=None).isoformat(sep=' ')
        after=previous.get('after_time') or local(now-86400)
        through=previous.get('through_time') or local(now)
        cursor.execute('SELECT '+self._columns(cursor,'cdr')+' FROM '+self._table('cdr')+
                       ' WHERE `calldate`>%s AND `calldate`<=%s ORDER BY `calldate` LIMIT %s',(after,through,limit+1))
        rows=cursor.fetchall();complete=cdr_page(rows,limit);caught_up=len(rows)<=limit
        checkpoint=dict(after_time=None if caught_up else complete[-1]['calldate'].isoformat(sep=' '),
                        through_time=None if caught_up else through,next_scan=now+300 if caught_up else now,
                        observed=now,window_seconds=86400,caught_up=caught_up)
        inserted=archive.append([self._event('cdr',row) for row in complete],checkpoint_source=name,checkpoint=checkpoint)
        return dict(cdr_overlap_inserted=inserted,cdr_overlap_caught_up=caught_up)
