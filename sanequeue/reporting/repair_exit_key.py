"""Bounded resumable repair of pre-fix EXITWITHKEY queue visit projections.

One invocation advances a checkpoint over at most a small page. Run via a
low-priority maintenance scheduler; this never touches Asterisk or source logs.
"""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import time

from .facts import _rebuild_visits
from .store import Archive

CHECKPOINT='repair:exitwithkey_wait:v1'


def step(archive, *, scan_limit=100, max_calls=5, seconds=2.0):
    if not 1 <= scan_limit <= 500 or not 1 <= max_calls <= 10 or not 0.05 <= seconds <= 3:
        raise ValueError('invalid_repair_limits')
    if not archive.path.is_file() or archive.path.is_symlink():
        raise ValueError('archive_unavailable')
    deadline=time.monotonic()+seconds
    with archive.writer() as db:
        db.set_progress_handler(lambda: int(time.monotonic()>=deadline),1000)
        try:
            db.execute('BEGIN IMMEDIATE')
            projection=db.execute('SELECT after_id FROM report_projection WHERE pbx=?',(archive.pbx,)).fetchone()
            if not projection:raise ValueError('projection_unavailable')
            row=db.execute('SELECT value FROM checkpoints WHERE pbx=? AND source=?',(archive.pbx,CHECKPOINT)).fetchone()
            checkpoint=json.loads(row[0]) if row else {'after_id':0,'target_id':projection[0],'completed':False}
            if (set(checkpoint)!={'after_id','target_id','completed'} or type(checkpoint['after_id']) is not int
                or type(checkpoint['target_id']) is not int or type(checkpoint['completed']) is not bool
                or not 0<=checkpoint['after_id']<=checkpoint['target_id']<=projection[0]):
                raise ValueError('invalid_repair_checkpoint')
            if checkpoint['completed']:return dict(**checkpoint,scanned=0,rebuilt_calls=0)
            rows=db.execute('SELECT event_id,kind,queue,callid FROM report_queue_events WHERE pbx=? AND event_id>? AND event_id<=? ORDER BY event_id LIMIT ?',
                            (archive.pbx,checkpoint['after_id'],checkpoint['target_id'],scan_limit)).fetchall()
            identities=set();last=checkpoint['after_id'];scanned=0
            for event_id,kind,queue,callid in rows:
                if kind=='EXITWITHKEY' and (queue,callid) not in identities and len(identities)>=max_calls:break
                if kind=='EXITWITHKEY':identities.add((queue,callid))
                last=event_id;scanned+=1
            for queue,callid in sorted(identities):
                _rebuild_visits(db,archive.pbx,queue,callid,projection[0])
            done=scanned==len(rows) and len(rows)<scan_limit
            state={'after_id':checkpoint['target_id'] if done else last,'target_id':checkpoint['target_id'],'completed':done}
            db.execute('INSERT OR REPLACE INTO checkpoints VALUES(?,?,?,?)',
                       (archive.pbx,CHECKPOINT,json.dumps(state,separators=(',',':')),time.time()))
            return dict(**state,scanned=scanned,rebuilt_calls=len(identities))
        finally:
            db.set_progress_handler(None,0)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True)
    parser.add_argument('--pbx',default='primary')
    parser.add_argument('--apply',action='store_true',required=True)
    parser.add_argument('--scan-limit',type=int,default=100)
    parser.add_argument('--max-calls',type=int,default=5)
    parser.add_argument('--seconds',type=float,default=2)
    args=parser.parse_args()
    if hasattr(os,'nice'):os.nice(10)
    archive=Archive(Path(args.database),pbx=args.pbx)
    try:
        print(json.dumps(step(archive,scan_limit=args.scan_limit,max_calls=args.max_calls,seconds=args.seconds)))
    except (ValueError,sqlite3.Error,OSError) as error:
        # Do not expose identifiers, source values or paths in logs.
        print(json.dumps({'error':type(error).__name__}))
        raise SystemExit(1)


if __name__=='__main__':main()
