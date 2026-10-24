#!/usr/bin/env python3
"""Safe Asterisk AMI diagnostic independent of Flask.

Uses only Login, QueueStatus and Logoff. No telephone or queue mutations.
Does not export caller names/numbers or the AMI password.
"""
import argparse
import getpass
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from AMI_READONLY_TEST import ReadOnlyAMI
from qpanel.ami_targets import validate_target
from qpanel.ami_live import read_queue_data
from qpanel.queue_visibility import filter_queue_data
from qpanel.ami_connection_qa import classify_error, safe_stage


def run(host,port,user,password,queue='*',visible='8001',client_cls=ReadOnlyAMI,queue_reader=read_queue_data):
    completed=[]
    client=None
    stage='target'
    try:
        host,port,queue=validate_target(host,port,queue)
        completed.append(safe_stage('target',True))
        stage='tcp'
        client=client_cls(host,port,timeout=10)
        completed.append(safe_stage('tcp',True))
        stage='login'
        client.login(user,password)
        completed.append(safe_stage('login',True))
        stage='queue_status'
        result=client.queue_snapshot(queue,timeout=20)
        if not result.get('snapshot_complete') or not result.get('queue_count'):
            raise TimeoutError('AMI queue response incomplete')
        completed.append(safe_stage('queue_status',True))
    except Exception as exc:
        code=classify_error(exc,stage)
        completed.append(safe_stage(stage,False,code))
        return dict(ok=False,stages=completed,error_code=code)
    finally:
        if client is not None:
            client.close()
    stage='live_parser'
    try:
        result=queue_reader(host,port,user,password,queue)
        completed.append(safe_stage('live_parser',True))
        stage='visibility'
        shown=filter_queue_data(result,visible)
        if not shown:raise ValueError('No Issabel queues matched')
        completed.append(safe_stage('visibility',True))
        return dict(ok=True,stages=completed,queue_count=len(result),visible_queue_count=len(shown))
    except Exception as exc:
        code=classify_error(exc,stage)
        completed.append(safe_stage(stage,False,code))
        return dict(ok=False,stages=completed,error_code=code)


def main():
    ap=argparse.ArgumentParser(description='Read-only Asterisk 20 AMI six-stage verification')
    ap.add_argument('--host',default='192.168.2.2')
    ap.add_argument('--port',type=int,default=5038)
    ap.add_argument('--user',default='sq')
    ap.add_argument('--queue',default='*')
    ap.add_argument('--visible',default='8001')
    args=ap.parse_args()
    print('No PBX changes, no call operations, no credentials written to disk.')
    password=getpass.getpass('AMI password (hidden): ')
    result=run(args.host,args.port,args.user,password,args.queue,args.visible)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['ok'] else 1
if __name__=='__main__':raise SystemExit(main())
