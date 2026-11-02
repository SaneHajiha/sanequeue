#!/usr/bin/env python3
"""Create a new isolated synthetic reporting archive; never call a PBX.

No arguments is a dry run. Use --write --destination NEW_DIRECTORY to create
history.sqlite3 and manifest.json. Determinism concerns events and expected
metrics; SQLite timestamps/file bytes are not promised to be identical.
"""
import argparse
import csv
from datetime import datetime, timedelta
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sanequeue.reporting.store import Archive, Event
from sanequeue.reporting.facts import project_batch
from sanequeue.reporting.queries import Scope, overview, agents
from sanequeue.reporting.report_builder import preview, export_csv
from sanequeue.reporting.agent_metrics import report as agent_metrics

QUEUES=('8001','8002')
ZONE=ZoneInfo('Asia/Tehran')
DAY=datetime(2026,10,27,tzinfo=ZONE)
BASE=DAY.replace(hour=9).timestamp()
FORBIDDEN_ROOTS=('/etc','/opt','/var/lib','/var/spool','/usr','/bin','/sbin','/root','/boot','/proc','/sys','/dev','/run')


def _repeat(value):
    if type(value) is not int or not 1<=value<=15:
        raise ValueError('fixture_repeat_must_be_1_to_15')
    return value


def events(repeat=1):
    """Nine synthetic call identities per cycle, ten queue visits, no CDR/audio."""
    repeat=_repeat(repeat);result=[]
    for cycle in range(repeat):
        offset=cycle*600
        def queue(case,queue_name,kind,seconds,values=(),agent='100'):
            key=f'cycle-{cycle}-{queue_name}-{case}-{kind}'
            result.append(Event('queue_log',key,BASE+offset+seconds,kind,
                dict(callid=f'fixture-{cycle}-{case}',queue=queue_name,
                     agent=f'Local/{agent}@from-queue/n' if agent else 'NONE',values=list(values))))
        def answered(case,queue_name,entered,wait,talk,*,ended_by='caller',agent='100',number='0000000000'):
            queue(case,queue_name,'ENTERQUEUE',entered,['',number],agent='')
            queue(case,queue_name,'CONNECT',entered+wait,[str(wait),f'fixture-peer-{cycle}-{case}','0'],agent=agent)
            queue(case,queue_name,'COMPLETECALLER' if ended_by=='caller' else 'COMPLETEAGENT',entered+wait+talk,[str(wait),str(talk),'1'],agent=agent)
        answered('a','8001',0,10,60,number='0000000001')
        answered('b','8001',100,30,30,ended_by='agent',number='0000000002')
        queue('c','8001','ENTERQUEUE',200,['','0000000003'],agent='')
        queue('c','8001','ABANDON',245,['1','1','45'],agent='')
        queue('d','8001','ENTERQUEUE',300,['','0000000004'],agent='')
        queue('d','8001','CONNECT',305,['5',f'fixture-peer-{cycle}-d-first','0'],agent='200')
        queue('d','8001','TRANSFER',325,['8002','fixture-context'],agent='200')
        queue('e','8001','ENTERQUEUE',400,['','0000000005'],agent='')
        # Intentionally incomplete evidence: completion with no entry/connect,
        # unknown durations. It must not become a zero-duration complete call.
        queue('f','8001','COMPLETEAGENT',500,['',''],agent='100')
        answered('g','8002',80,4,10,number='0000000006')
        answered('h','8002',180,20,90,ended_by='agent',agent='200',number='0000000007')
        queue('i','8002','ENTERQUEUE',320,['','0000000008'],agent='')
        queue('i','8002','ABANDON',335,['1','1','15'],agent='')
        # Same synthetic call identity enters a second queue after transfer.
        answered('d','8002',326,10,50,number='0000000004')
        for queue_name in QUEUES:
            for agent in ('100','200'):
                if agent=='100':
                    schedule=[(0,10,'available'),(10,70,'on_call'),(70,84,'available'),
                              (84,94,'on_call'),(94,130,'available'),(130,160,'on_call'),
                              (160,170,'wrap_up' if queue_name=='8001' else 'available'),
                              (170,190,'paused'),(190,336,'available'),(336,386,'on_call'),
                              (386,396,'wrap_up' if queue_name=='8002' else 'available'),(396,600,'available')]
                else:
                    schedule=[(0,200,'available'),(200,290,'on_call'),(290,305,'available'),
                              (305,325,'on_call'),(325,600,'available')]
                for part,(begin,end,state) in enumerate(schedule):
                    result.append(Event('activity',f'cycle-{cycle}-{queue_name}-{agent}-{part}',BASE+offset+begin,'ACTIVITY_INTERVAL',
                        dict(queue=queue_name,agent=f'Local/{agent}@from-queue/n',canonical_agent=f'PJSIP/{agent}',
                             state=state,reason='fixture_survey' if state=='paused' else '',
                             starts=BASE+offset+begin,ends=BASE+offset+end,on_duty=state!='paused',coverage='observed')))
    if len(result)>1000:
        raise ValueError('fixture_event_limit')
    return result


def expected_metrics(repeat=1):
    n=_repeat(repeat)
    return dict(
        overview=[dict(queue='8001',visits=6*n,answered=4*n,abandoned=n,transferred=n,incomplete=2*n,
                       average_wait_seconds=22.5,average_talk_seconds=45,sla_known=3*n,sla_met=2*n,sla_percent=200/3),
                  dict(queue='8002',visits=4*n,answered=3*n,abandoned=n,transferred=0,incomplete=0,
                       average_wait_seconds=12.25,average_talk_seconds=50,sla_known=3*n,sla_met=3*n,sla_percent=100)],
        agents=[dict(queue='8001',agent='Local/100@from-queue/n',answered=3*n,transferred=0,average_talk_seconds=45,
                     average_wait_seconds=20,talk_seconds=90*n,caller_segment_hangup=n,agent_segment_hangup=2*n,unknown_segment_hangup=0),
                dict(queue='8001',agent='Local/200@from-queue/n',answered=n,transferred=n,average_talk_seconds=None,
                     average_wait_seconds=5,talk_seconds=None,caller_segment_hangup=None,agent_segment_hangup=None,unknown_segment_hangup=n),
                dict(queue='8002',agent='Local/100@from-queue/n',answered=2*n,transferred=0,average_talk_seconds=30,
                     average_wait_seconds=7,talk_seconds=60*n,caller_segment_hangup=2*n,agent_segment_hangup=0,unknown_segment_hangup=0),
                dict(queue='8002',agent='Local/200@from-queue/n',answered=n,transferred=0,average_talk_seconds=90,
                     average_wait_seconds=20,talk_seconds=90*n,caller_segment_hangup=0,agent_segment_hangup=n,unknown_segment_hangup=0)],
        builder=[dict(queue='8001',visits=6*n,answered_known=3*n,abandoned=n,wait_known=4*n,average_wait_seconds=22.5,
                      talk_known=2*n,average_queue_talk_seconds=45,queue_talk_seconds=90*n),
                 dict(queue='8002',visits=4*n,answered_known=3*n,abandoned=n,wait_known=4*n,average_wait_seconds=12.25,
                      talk_known=3*n,average_queue_talk_seconds=50,queue_talk_seconds=150*n)],
        agent_unique_activity=[dict(agent='PJSIP/100',observed_seconds=600*n,on_duty_seconds=580*n,on_call_seconds=150*n),
                               dict(agent='PJSIP/200',observed_seconds=600*n,on_duty_seconds=600*n,on_call_seconds=110*n)])


def plan(repeat=1):
    data=events(repeat)
    semantic=[dict(source=e.source,key=e.key,ts=e.timestamp,kind=e.kind,payload=e.payload) for e in data]
    return dict(schema_version=1,fixture='sanequeue-reporting-synthetic-v1',synthetic=True,repeat=repeat,
                event_count=len(data),queue_visit_count=10*repeat,unique_synthetic_call_ids=9*repeat,
                report_date='2026-10-27',timezone='Asia/Tehran',start=DAY.timestamp(),end=(DAY+timedelta(days=1)).timestamp(),
                activity_start=BASE,activity_end=BASE+600*repeat,queues=list(QUEUES),
                events_sha256=hashlib.sha256(json.dumps(semantic,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest(),
                expected=expected_metrics(repeat),
                limits=dict(maximum_events=1000,no_pbx_calls=True,no_ami=True,no_live_data=True,no_recordings=True),
                notes=['answered in overview includes completion-only evidence; answered_known in builder requires an answer timestamp',
                       'queue visits are not unique customer conversations; one identity visits both queues after transfer',
                       'presence is a union across simultaneous queue memberships, not the sum',
                       'unknown durations stay null; synthetic state and metrics do not validate live media or production load'])


def _compare(actual,expected,path):
    if isinstance(expected,list):
        if not isinstance(actual,list) or len(actual)!=len(expected):raise AssertionError('fixture_metric_mismatch:'+path)
        for index,(value,wanted) in enumerate(zip(actual,expected)):_compare(value,wanted,path+'/'+str(index))
    elif isinstance(expected,dict):
        if not isinstance(actual,dict):raise AssertionError('fixture_metric_mismatch:'+path)
        for key,value in expected.items():
            if key not in actual:raise AssertionError('fixture_metric_missing:'+path+'/'+key)
            _compare(actual[key],value,path+'/'+key)
    elif type(expected) in (int,float):
        if type(actual) not in (int,float) or not math.isclose(actual,expected,rel_tol=1e-10,abs_tol=1e-8):
            raise AssertionError('fixture_metric_mismatch:'+path)
    elif actual!=expected:raise AssertionError('fixture_metric_mismatch:'+path)


def verify(archive,metadata):
    """Compare literal expectations using shipped read APIs, never raw SQL facts."""
    scope=Scope(QUEUES);start,end=metadata['start'],metadata['end']
    actual=dict(overview=overview(archive,scope,start,end)['queues'],agents=agents(archive,scope,start,end)['rows'])
    spec=dict(dataset='queue_visits',queues=list(QUEUES),columns=['queue','agent','outcome','wait_seconds','talk_seconds'],group_by=['queue'],filters={})
    modes={queue:'masked' for queue in QUEUES}
    built=preview(archive,scope,start,end,spec,number_modes=modes)
    actual['builder']=built['rows']
    actual['agent_unique_activity']=agent_metrics(archive,scope,metadata['activity_start'],metadata['activity_end'],now=metadata['activity_end'])['agents']
    _compare(actual,metadata['expected'],'metrics')
    csv_data,csv_meta=export_csv(archive,scope,start,end,spec,number_modes=modes,language='en')
    if not csv_data.startswith(b'\xef\xbb\xbf') or csv_meta['rows']!=2:raise AssertionError('fixture_csv_verification_failed')
    rows=list(csv.DictReader(io.StringIO(csv_data.decode('utf-8-sig'))))
    if len(rows)!=2 or list(rows[0])!=built['columns']:raise AssertionError('fixture_csv_verification_failed')
    csv_values=[]
    for row in rows:
        parsed={}
        for key,value in row.items():
            if key=='queue':
                if not value.startswith("'"):raise AssertionError('fixture_csv_text_identity_missing')
                parsed[key]=value[1:]
            else:parsed[key]=None if value=='' else float(value)
        csv_values.append(parsed)
    _compare(csv_values,metadata['expected']['builder'],'csv')
    return dict(overview=True,agents=True,builder=True,agent_unique_activity=True,custom_csv=True,
                compared_queue_visits=sum(row['visits'] for row in actual['overview']),compared_agent_queue_groups=len(actual['agents']))


def _new_destination(destination):
    original=Path(destination).expanduser().absolute()
    for item in (original,*original.parents):
        if item.is_symlink():raise ValueError('fixture_symlink_refused')
    path=original.resolve()
    if path.exists() or os.path.lexists(path):raise FileExistsError('fixture_destination_exists')
    normalized=path.as_posix().lower()
    if any(normalized==root or normalized.startswith(root+'/') for root in FORBIDDEN_ROOTS):
        raise ValueError('fixture_production_path_refused')
    if re.match(r'^[a-z]:/(?:windows|program files(?: \(x86\))?|programdata)(?:/|$)',normalized):
        raise ValueError('fixture_production_path_refused')
    if not path.parent.is_dir():raise ValueError('fixture_parent_must_exist')
    return path


def generate(destination=None,*,write=False,repeat=1):
    metadata=plan(repeat)
    if not write:
        return {**metadata,'written':False,'verification':'not_run_dry_run'}
    if destination is None:raise ValueError('fixture_destination_required')
    path=_new_destination(destination);path.mkdir(mode=0o700)
    try:
        archive=Archive(path/'history.sqlite3',min_free_bytes=16*1024*1024);archive.initialize()
        archive.append(events(repeat))
        archive.append([],checkpoint_source='activity_cache',checkpoint=dict(observed=metadata['activity_end'],generation='synthetic-fixture-v1'))
        for _ in range(1001):
            if not project_batch(archive,limit=250,inventory={})['processed']:break
        else:raise RuntimeError('fixture_projection_limit')
        verification=verify(archive,metadata)
        archive.passive_checkpoint()
        output={**metadata,'written':True,'verification':verification}
        with (path/'manifest.json').open('x',encoding='utf-8') as stream:json.dump(output,stream,ensure_ascii=False,indent=2);stream.write('\n')
        return output
    except BaseException:
        # Retain a failed *new isolated* dataset for inspection; never delete,
        # overwrite or relabel it as successfully verified test data.
        with (path/'FAILED.txt').open('x',encoding='utf-8') as stream:stream.write('Synthetic fixture generation or metric verification failed.\n')
        raise


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination',type=Path,help='New isolated directory; parent must exist, production roots refused')
    parser.add_argument('--write',action='store_true',help='Actually create the NEW fixture directory; default is a dry run')
    parser.add_argument('--repeat',type=int,default=1,help='Deterministic cycles, 1..15; default1 is under100 events')
    args=parser.parse_args(argv)
    try:result=generate(args.destination,write=args.write,repeat=args.repeat)
    except (ValueError,FileExistsError) as error:parser.error(str(error))
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
