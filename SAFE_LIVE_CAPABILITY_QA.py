#!/usr/bin/env python3
"""Read-only Asterisk 20 AMI capability audit. No call changing Action."""
import argparse
import getpass
import json
from datetime import datetime,timezone
from pathlib import Path
from qpanel.ami_targets import validate_target
from qpanel.ami_health import read_capabilities, read_health
from AMI_READONLY_TEST import ReadOnlyAMI


def main():
    ap=argparse.ArgumentParser(description='SaneQueue AMI read-only health QA')
    ap.add_argument('--host',default='127.0.0.1')
    ap.add_argument('--port',type=int,default=15038)
    ap.add_argument('--user',default='sq')
    ap.add_argument('--queue',default='*')
    args=ap.parse_args()
    validate_target(args.host,args.port,args.queue)
    secret=getpass.getpass('AMI password (local only, never saved): ')
    output={'time_utc':datetime.now(timezone.utc).isoformat(),
            'host_scope':'loopback' if args.host in ('127.0.0.1','localhost') else 'private-lan',
            'queue_scope':args.queue,
            'probe':{}, 'permissions':{}, 'health':{}}
    client=None
    try:
        client=ReadOnlyAMI(args.host,args.port,timeout=6)
        client.login(args.user,secret)
        output['probe']=client.queue_snapshot(args.queue,timeout=12)
        # queue_snapshot is already sanitized; no raw event bodies exported.
        output['permissions']=read_capabilities(args.host,args.port,args.user,secret,args.queue)
        for kind in ('channels','extensions','contacts','registrations','parking'):
            output['health'][kind]=read_health(args.host,args.port,args.user,secret,args.queue,kind)
    except Exception as e:
        # Errors can embed credentials in custom implementations; classify only.
        output['probe_error']=type(e).__name__
    finally:
        if client:client.close()
        secret=None
    target=Path(__file__).resolve().parent/'safe_live_capabilities.json'
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Read-only check saved to:',target)
    print('Queues found:',output['probe'].get('queue_count','—'))
    print('Health statuses:', {k:v.get('reason',v.get('supported')) for k,v in output['health'].items()})
    print('No AMI password, caller ID or SIP contact URI saved.')
    return 0 if output['probe'].get('snapshot_complete') else 1

if __name__=='__main__':raise SystemExit(main())
