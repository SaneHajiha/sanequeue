"""Read-only incremental archival of the collector's bounded activity cache."""
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time
from .store import Event
from .identity import canonical
from sanequeue.realtime.local_inventory import read_snapshot


class ActivitySource:
    source = 'activity_cache'

    def __init__(self, path,*,inventory_path='/run/sanequeue/inventory.json'):
        self.path = Path(path).absolute()
        self.inventory_path=inventory_path

    def ingest(self, archive, *, limit=250):
        limit = max(1, min(500, int(limit)))
        if self.path.is_symlink():
            raise ValueError('activity_source_symlink')
        meta_file = self.path.stat()
        identity = f'{meta_file.st_dev}:{meta_file.st_ino}'
        previous = archive.checkpoint(self.source)
        if previous.get('path') and previous['path'] != str(self.path):
            raise ValueError('activity_source_path_changed')
        with archive.reader() as db:
            tracked = db.execute('SELECT row_id,source_key,payload FROM activity_import_open WHERE pbx=? AND source=? ORDER BY row_id LIMIT 10001',
                                 (archive.pbx,self.source)).fetchall()
        if len(tracked)>10000:
            raise ValueError('activity_open_row_limit')
        source = sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,timeout=.25)
        source.row_factory=sqlite3.Row
        deadline=time.monotonic()+.5
        source.set_progress_handler(lambda:int(time.monotonic()>deadline),1000)
        try:
            source.execute('PRAGMA query_only=ON')
            source.execute('BEGIN')
            meta=source.execute('SELECT generation,observed FROM activity_meta WHERE id=1').fetchone()
            if not meta:
                return dict(inserted=0,caught_up=True,available=False)
            observed=float(meta['observed'])
            if not math.isfinite(observed) or not 0<=observed<=32503680000:
                raise ValueError('invalid_activity_heartbeat')
            maximum=source.execute('SELECT MAX(id) FROM activity').fetchone()[0] or 0
            after=int(previous.get('after',0))
            reset=bool(previous) and (previous.get('identity')!=identity or observed<float(previous.get('observed',0)) or maximum<after or previous.get('generation')!=meta['generation'])
            if reset:after=0
            minimum=source.execute('SELECT MIN(id) FROM activity').fetchone()[0]
            gap=bool(minimum and after and minimum>after+1)
            new=[dict(row) for row in source.execute('SELECT * FROM activity WHERE id>? ORDER BY id LIMIT ?', (after,limit))]
            updates=[]
            selected=[]
            if not reset:
                selected=[row for row in tracked if row['row_id']>int(previous.get('open_after',0))][:500]
                if not selected:selected=tracked[:500]
                ids=[int(row['row_id']) for row in selected]
                for index in range(0,len(ids),100):
                    part=ids[index:index+100]
                    updates.extend(dict(row) for row in source.execute('SELECT * FROM activity WHERE id IN ('+','.join('?' for _ in part)+')',part))
            source.commit()
        finally:
            source.close()
        events=[];opened={};closed=set();seen=set()
        inventory=read_snapshot(self.inventory_path)
        closing=tracked[:500] if reset else [row for row in selected if row['row_id'] not in {item['id'] for item in updates}]
        if closing and not reset:gap=True
        # A replacement cache cannot extend old open intervals across a
        # monitoring gap. End them at their last observed heartbeat.
        for row in closing:
            payload=json.loads(row['payload'])
            payload['ends']=max(payload['starts'],float(previous.get('observed',payload['starts'])))
            payload['coverage']='source_replaced' if reset else 'source_row_missing'
            events.append(Event('activity',row['source_key'],payload['starts'],'ACTIVITY_INTERVAL',payload))
            closed.add(row['row_id'])
        resetting=reset and len(tracked)>500
        if resetting:new=[]
        for row in new+updates:
            if row['id'] in seen:continue
            seen.add(row['id'])
            start=float(row['starts']);end=None if row['ends'] is None else float(row['ends'])
            if not math.isfinite(start) or start<0 or start>observed or end is not None and (not math.isfinite(end) or end<start or end>observed):
                raise ValueError('invalid_activity_interval')
            if len(str(row['queue']))>128 or len(str(row['agent']))>256 or len(str(row['reason']))>1000:
                raise ValueError('activity_field_limit')
            key=hashlib.sha256(json.dumps([row['id'],str(row['queue']),str(row['agent']),start]).encode()).hexdigest()
            payload=dict(row_id=int(row['id']),queue=str(row['queue']),agent=str(row['agent']),
                         canonical_agent=canonical(str(row['agent']),inventory),
                         state=str(row['state']),reason=str(row['reason']),starts=start,ends=end,
                         on_duty=bool(row['on_duty']),coverage='observed')
            events.append(Event('activity',key,start,'ACTIVITY_INTERVAL',payload))
            if end is None:opened[row['id']]=(key,payload)
            else:closed.add(row['id'])
        # Bound the shared archive transaction even when many intervals close.
        if len(events)>1000:
            raise ValueError('activity_update_batch_limit')
        after=max([after]+[int(row['id']) for row in new])
        checkpoint=dict(path=str(self.path),identity=identity,after=after,observed=observed,
                        generation=str(meta['generation']),gaps=int(previous.get('gaps',0))+int((gap or reset) and not previous.get('resetting')),
                        resetting=resetting)
        checkpoint['open_after']=selected[-1]['row_id'] if selected else 0
        if resetting:
            checkpoint.update(identity=previous.get('identity'),generation=previous.get('generation'),
                              observed=previous.get('observed'),after=previous.get('after',0))
        def state(db):
            for row_id in closed:
                db.execute('DELETE FROM activity_import_open WHERE pbx=? AND source=? AND row_id=?',
                           (archive.pbx,self.source,row_id))
            for row_id,(key,payload) in opened.items():
                db.execute('INSERT OR REPLACE INTO activity_import_open VALUES(?,?,?,?,?)',
                           (archive.pbx,self.source,row_id,key,json.dumps(payload,ensure_ascii=False)))
        inserted=archive.append(events,checkpoint_source=self.source,checkpoint=checkpoint,update_state=state)
        return dict(inserted=inserted,caught_up=after>=maximum,available=True,gap_detected=gap or reset,observed_until=observed)
