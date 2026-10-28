#!/usr/bin/env python3
"""Isolated synthetic month: exactly 1,000 call identities per local day.

Default is dry-run. --write --destination NEW_DIRECTORY creates a fresh archive
and verified manifest. No AMI, telephone calls, production database, audio or
credentials are used. Events are streamed in batches of at most 250.
"""
import argparse
from copy import deepcopy
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import shutil
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools.generate_reporting_fixture import events as baseline_events, BASE, ZONE, QUEUES, _compare, _new_destination
from sanequeue.reporting.store import Archive, Event
from sanequeue.reporting.facts import project_batch
from sanequeue.reporting.queries import Scope, overview, agents
from sanequeue.reporting.report_builder import preview
from sanequeue.reporting.ring_attempts import report as ring_attempts

TEMPLATE=tuple(baseline_events())
PUBLIC_CYCLES=111
CALLS_PER_DAY=1000
BATCH=250
MIN_FREE_BYTES=128*1024*1024


def _day_bounds(day):
    return (datetime.combine(day,datetime.min.time(),ZONE).timestamp(),
            datetime.combine(day+timedelta(days=1),datetime.min.time(),ZONE).timestamp())


def _day_events(day,cycles):
    start,end=_day_bounds(day)
    for cycle in range(cycles):
        shift=start+cycle*600-BASE;prefix='month-'+day.strftime('%Y%m%d')+'-'+str(cycle)
        for event in TEMPLATE:
            payload=deepcopy(event.payload)
            if event.source=='queue_log':
                payload['callid']=prefix+'-'+payload['callid']
                if event.kind=='CONNECT':payload['values'][1]=prefix+'-'+payload['values'][1]
            else:
                payload['starts']+=shift;payload['ends']+=shift
            yield Event(event.source,prefix+'-'+event.key,event.timestamp+shift,event.kind,payload)
    # Add one distinct answered identity after the cycles: 111*9+1 = 1,000.
    entered=start+70000;answered=entered+10;ended=answered+60
    prefix='month-'+day.strftime('%Y%m%d')+'-extra'
    for kind,stamp,values in [('ENTERQUEUE',entered,['','0000000009']),
                              ('CONNECT',answered,['10',prefix+'-peer','0']),
                              ('COMPLETECALLER',ended,['10','60','1'])]:
        yield Event('queue_log',prefix+'-'+kind,stamp,kind,
                    dict(callid=prefix,queue='8001',agent='NONE' if kind=='ENTERQUEUE' else 'Local/100@from-queue/n',values=values))
    for queue in QUEUES:
        for agent in ('100','200'):
            schedule=[(start+cycles*600,answered,'available'),(answered,ended,'on_call'),(ended,end,'available')] if agent=='100' else [(start+cycles*600,end,'available')]
            for index,(first,last,state) in enumerate(schedule):
                yield Event('activity',prefix+'-'+queue+'-'+agent+'-'+str(index),first,'ACTIVITY_INTERVAL',
                            dict(queue=queue,agent='Local/'+agent+'@from-queue/n',canonical_agent='PJSIP/'+agent,
                                 state=state,reason='',starts=first,ends=last,on_duty=True,coverage='observed'))
    # One explicit no-answer offer on an already-counted abandoned caller.
    # This adds evidence, not a new call identity or queue visit.
    prefix='month-'+day.strftime('%Y%m%d')
    yield Event('queue_log',prefix+'-ring-no-answer',start+220,'RINGNOANSWER',
                dict(callid=prefix+'-0-fixture-0-c',queue='8001',agent='Local/100@from-queue/n',values=['2000']))


def _expected(cycles,days=1):
    n=cycles;d=days
    q1_wait=(90*n+10)/(4*n+1);q1_talk=(90*n+60)/(2*n+1)
    return dict(
        overview=[dict(queue='8001',visits=(6*n+1)*d,answered=(4*n+1)*d,abandoned=n*d,transferred=n*d,
                       incomplete=2*n*d,average_wait_seconds=q1_wait,average_talk_seconds=q1_talk,
                       sla_known=(3*n+1)*d,sla_met=(2*n+1)*d,sla_percent=100*(2*n+1)/(3*n+1)),
                  dict(queue='8002',visits=4*n*d,answered=3*n*d,abandoned=n*d,transferred=0,incomplete=0,
                       average_wait_seconds=12.25,average_talk_seconds=50,sla_known=3*n*d,sla_met=3*n*d,sla_percent=100)],
        agents=[dict(queue='8001',agent='Local/100@from-queue/n',answered=(3*n+1)*d,transferred=0,
                     average_talk_seconds=q1_talk,average_wait_seconds=(40*n+10)/(2*n+1),talk_seconds=(90*n+60)*d,
                     caller_segment_hangup=(n+1)*d,agent_segment_hangup=2*n*d,unknown_segment_hangup=0),
                dict(queue='8001',agent='Local/200@from-queue/n',answered=n*d,transferred=n*d,
                     average_talk_seconds=None,average_wait_seconds=5,talk_seconds=None,
                     caller_segment_hangup=None,agent_segment_hangup=None,unknown_segment_hangup=n*d),
                dict(queue='8002',agent='Local/100@from-queue/n',answered=2*n*d,transferred=0,
                     average_talk_seconds=30,average_wait_seconds=7,talk_seconds=60*n*d,
                     caller_segment_hangup=2*n*d,agent_segment_hangup=0,unknown_segment_hangup=0),
                dict(queue='8002',agent='Local/200@from-queue/n',answered=n*d,transferred=0,
                     average_talk_seconds=90,average_wait_seconds=20,talk_seconds=90*n*d,
                     caller_segment_hangup=0,agent_segment_hangup=n*d,unknown_segment_hangup=0)],
        builder=[dict(queue='8001',visits=(6*n+1)*d,answered_known=(3*n+1)*d,abandoned=n*d,
                      wait_known=(4*n+1)*d,average_wait_seconds=q1_wait,talk_known=(2*n+1)*d,
                      average_queue_talk_seconds=q1_talk,queue_talk_seconds=(90*n+60)*d),
                 dict(queue='8002',visits=4*n*d,answered_known=3*n*d,abandoned=n*d,wait_known=4*n*d,
                      average_wait_seconds=12.25,talk_known=3*n*d,average_queue_talk_seconds=50,queue_talk_seconds=150*n*d)])


def _plan(start_date='2026-09-01',days=30,*,cycles=PUBLIC_CYCLES):
    if not isinstance(start_date,str):raise ValueError('invalid_fixture_start_date')
    first=date.fromisoformat(start_date)
    if type(days) is not int or not 1<=days<=31:raise ValueError('fixture_days_must_be_1_to_31')
    if type(cycles) is not int or not 1<=cycles<=PUBLIC_CYCLES:raise ValueError('invalid_fixture_cycles')
    if len(TEMPLATE)!=58:raise ValueError('baseline_template_changed_review_month_fixture')
    records=[]
    for offset in range(days):
        day=first+timedelta(days=offset);start,end=_day_bounds(day)
        if end-start<70100:raise ValueError('fixture_day_too_short')
        records.append(dict(date=day.isoformat(),start=start,end=end,unique_synthetic_call_ids=9*cycles+1,
                            queue_visit_count=10*cycles+1,event_count=58*cycles+12,expected=_expected(cycles),
                            expected_ring_attempts=dict(attempts=1,known_duration_attempts=1,unknown_duration_attempts=0,known_ring_seconds=2)))
    if records[-1]['end']-records[0]['start']>31*86400:raise ValueError('fixture_range_exceeds_builder_limit')
    return dict(schema_version=1,fixture='sanequeue-reporting-synthetic-month-v1',synthetic=True,
                start_date=first.isoformat(),end_date=records[-1]['date'],timezone='Asia/Tehran',days=days,
                calls_per_day=9*cycles+1,cycles_per_day=cycles,
                unique_synthetic_call_ids=(9*cycles+1)*days,queue_visit_count=(10*cycles+1)*days,
                event_count=(58*cycles+12)*days,start=records[0]['start'],end=records[-1]['end'],
                queues=list(QUEUES),daily=records,expected=_expected(cycles,days),
                expected_ring_attempts=dict(attempts=days,known_duration_attempts=days,unknown_duration_attempts=0,known_ring_seconds=2*days),
                limits=dict(append_batch_events=BATCH,projection_batch_events=BATCH,no_pbx_calls=True,no_live_data=True,no_media=True),
                notes=['Call identities differ from queue visits: a transferred identity visits both queues.',
                       'Completion-only evidence contributes to overview answered but not builder answered_known.',
                       'Unknown durations remain NULL. This fixture does not prove audio quality, load capacity or root cause.',
                       'Monthly agent metrics can exceed MAX_INTERVALS/MAX_VISITS; a limited result must not be labeled complete.',
                       'Daily no-answer attempts are verified; a full-month ring-attempt query exceeds its MAX_EVENTS cap and is not certified.',
                       'Events are deterministic; SQLite imported/projection timestamps and file bytes are not.'])


def plan(start_date='2026-09-01',days=30,*,calls_per_day=CALLS_PER_DAY):
    if type(calls_per_day) is not int or calls_per_day!=CALLS_PER_DAY:
        raise ValueError('fixture_calls_per_day_must_be_1000')
    return _plan(start_date,days)


def _actual(archive,start,end):
    scope=Scope(QUEUES)
    spec=dict(dataset='queue_visits',queues=list(QUEUES),columns=['queue','agent','outcome','wait_seconds','talk_seconds'],group_by=['queue'],filters={})
    return dict(overview=overview(archive,scope,start,end)['queues'],agents=agents(archive,scope,start,end)['rows'],
                builder=preview(archive,scope,start,end,spec,number_modes={q:'masked' for q in QUEUES})['rows'])


def _unique_calls(archive,start,end):
    with archive.reader() as db:
        return db.execute('''SELECT COUNT(DISTINCT json_extract(payload,'$.callid')) FROM events
            WHERE pbx=? AND ts>=? AND ts<? AND source='queue_log' ''',(archive.pbx,start,end)).fetchone()[0]


def verify(archive,metadata):
    """Verify source identities plus actual public query aggregates for all days."""
    checked=0
    for day in metadata['daily']:
        _compare(_actual(archive,day['start'],day['end']),day['expected'],'daily/'+day['date'])
        if _unique_calls(archive,day['start'],day['end'])!=day['unique_synthetic_call_ids']:
            raise AssertionError('fixture_daily_call_identity_mismatch')
        if 'expected_ring_attempts' in day:
            _compare(ring_attempts(archive,Scope(QUEUES),day['start'],day['end'])['totals'],day['expected_ring_attempts'],'daily_ring/'+day['date'])
        checked+=1
    _compare(_actual(archive,metadata['start'],metadata['end']),metadata['expected'],'monthly')
    if _unique_calls(archive,metadata['start'],metadata['end'])!=metadata['unique_synthetic_call_ids']:
        raise AssertionError('fixture_monthly_call_identity_mismatch')
    with archive.reader() as db:
        counts=db.execute('SELECT COUNT(*) FROM events WHERE pbx=?',(archive.pbx,)).fetchone()[0]
    if counts!=metadata['event_count']:raise AssertionError('fixture_event_count_mismatch')
    return dict(days_verified=checked,unique_calls_verified=metadata['unique_synthetic_call_ids'],
                queue_visits_verified=metadata['queue_visit_count'],events_verified=counts,
                daily_and_monthly_overview=True,agents=True,builder=True,raw_unique_ids=True,
                ring_attempts_daily=all('expected_ring_attempts' in day for day in metadata['daily']),ring_attempts_monthly_complete=False,
                monthly_agent_metrics_complete=False,monthly_agent_metrics_note='not certified beyond bounded API limits')


def _write(destination,metadata):
    path=_new_destination(destination)
    if shutil.disk_usage(path.parent).free<256*1024*1024:raise OSError('fixture_insufficient_free_disk')
    path.mkdir(mode=0o700);started=time.monotonic();batches=0;maximum=0
    try:
        archive=Archive(path/'history.sqlite3',min_free_bytes=MIN_FREE_BYTES);archive.initialize()
        buffer=[]
        def flush():
            nonlocal batches,maximum
            if not buffer:return
            maximum=max(maximum,len(buffer));archive.append(buffer);buffer.clear();batches+=1
            # At most 250 new events were appended; don't build an unbounded
            # projection backlog or hold a transaction across the whole month.
            for _ in range(4):
                if not project_batch(archive,limit=BATCH,inventory={})['processed']:break
            else:raise RuntimeError('fixture_projection_backlog_limit')
        for day in metadata['daily']:
            for event in _day_events(date.fromisoformat(day['date']),metadata['cycles_per_day']):
                buffer.append(event)
                if len(buffer)==BATCH:flush()
            flush()
            # Check the day before proceeding; failure preserves this isolated
            # archive for investigation and never publishes a success manifest.
            _compare(_actual(archive,day['start'],day['end']),day['expected'],'day/'+day['date'])
            if _unique_calls(archive,day['start'],day['end'])!=day['unique_synthetic_call_ids']:
                raise AssertionError('fixture_daily_call_identity_mismatch')
        archive.append([],checkpoint_source='activity_cache',checkpoint=dict(observed=metadata['end'],generation='synthetic-month-v1'))
        verified=verify(archive,metadata);archive.passive_checkpoint()
        result={**metadata,'written':True,'verification':verified,
                'generation':dict(append_batches=batches,maximum_batch_events=maximum,elapsed_seconds=round(time.monotonic()-started,3))}
        with (path/'manifest.json').open('x',encoding='utf-8') as stream:json.dump(result,stream,ensure_ascii=False,indent=2);stream.write('\n')
        return result
    except BaseException:
        with (path/'FAILED.txt').open('x',encoding='utf-8') as stream:stream.write('Synthetic month generation or verification failed; not a ready fixture.\n')
        raise


def generate(destination=None,*,write=False,start_date='2026-09-01',days=30,calls_per_day=CALLS_PER_DAY):
    metadata=plan(start_date,days,calls_per_day=calls_per_day)
    if not write:return {**metadata,'written':False,'verification':'not_run_dry_run'}
    if destination is None:raise ValueError('fixture_destination_required')
    return _write(destination,metadata)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination',type=Path,help='NEW isolated directory; parent must exist')
    parser.add_argument('--write',action='store_true')
    parser.add_argument('--start-date',default='2026-09-01')
    parser.add_argument('--days',type=int,default=30)
    parser.add_argument('--calls-per-day',type=int,choices=(CALLS_PER_DAY,),default=CALLS_PER_DAY)
    args=parser.parse_args(argv)
    try:result=generate(args.destination,write=args.write,start_date=args.start_date,days=args.days,calls_per_day=args.calls_per_day)
    except (ValueError,FileExistsError) as error:parser.error(str(error))
    summary={key:result[key] for key in ('fixture','synthetic','written','days','calls_per_day','unique_synthetic_call_ids','queue_visit_count','event_count','start_date','end_date','verification')}
    if result['written']:summary['manifest']=str(args.destination/'manifest.json');summary['generation']=result['generation']
    print(json.dumps(summary,ensure_ascii=False,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
