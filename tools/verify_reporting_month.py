#!/usr/bin/env python3
"""Validate a NEW synthetic monthly archive without touching a live PBX.

Read-only checks run by default. Private background CSV/XLSX tests require
--write-exports --export-output NEW_DIRECTORY. This verifies report scale, not
concurrent phone calls, AMI throughput, RTP quality or production capacity.
"""
import argparse
import csv
from dataclasses import asdict
import io
import json
import math
import os
from pathlib import Path
import platform
import re
import sys
import time
from xml.etree import ElementTree as ET
from zipfile import ZipFile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from sanequeue.reporting.store import Archive,QueryDeadline
from sanequeue.reporting.queries import Scope,overview,agents
from sanequeue.reporting.analytics import dashboard
from sanequeue.reporting.report_builder import preview,COLUMNS
from sanequeue.reporting.agent_rankings import rank_agents,MAX_VISITS as RANK_VISITS
from sanequeue.reporting.agent_metrics import report as agent_metrics
from sanequeue.reporting.ring_attempts import report as ring_attempts,MAX_EVENTS as RING_EVENTS
from sanequeue.reporting.export_jobs import JobStore,ExportWorker,Limits
from sanequeue.reporting import builder_exports
from tools.generate_reporting_fixture import _compare,_new_destination


def resources():
    values=os.times();peak=None
    try:
        import resource
        peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform=='darwin':peak/=1024
    except ImportError:pass
    return dict(cpu_user_seconds=values.user,cpu_system_seconds=values.system,
                cumulative_process_peak_rss_kib=peak)


def _read_manifest(path):
    directory=Path(path).absolute()
    if directory.is_symlink() or not directory.is_dir() or (directory/'FAILED.txt').exists():raise ValueError('monthly_fixture_directory_invalid')
    manifest=directory/'manifest.json'
    if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_size>2*1024*1024:raise ValueError('monthly_manifest_invalid')
    value=json.loads(manifest.read_text(encoding='utf-8'))
    if not isinstance(value,dict) or value.get('synthetic') is not True:raise ValueError('monthly_synthetic_manifest_required')
    if type(value.get('days')) is not int or not 1<=value['days']<=31 or value.get('calls_per_day')!=1000:raise ValueError('monthly_fixture_size_invalid')
    if value.get('queue_visit_count')!=1111*value['days'] or value.get('unique_synthetic_call_ids')!=1000*value['days']:raise ValueError('monthly_manifest_count_invalid')
    if not isinstance(value.get('daily'),list) or len(value['daily'])!=value['days']:raise ValueError('monthly_manifest_days_invalid')
    if set(value.get('queues',[]))!={'8001','8002'}:raise ValueError('monthly_fixture_scope_invalid')
    database=directory/'history.sqlite3'
    if database.is_symlink() or not database.is_file():raise ValueError('monthly_fixture_database_invalid')
    return directory,value


def _read_checks(archive,metadata):
    scope=Scope(tuple(metadata['queues']));checks=[]
    def run(name,function):
        started=time.monotonic();before=resources()
        try:result=function();state='passed'
        except (AssertionError,ValueError,QueryDeadline,RuntimeError):result={'reason':'monthly_check_failed_or_limited'};state='failed'
        after=resources()
        checks.append(dict(name=name,state=state,elapsed_seconds=round(time.monotonic()-started,4),
            cpu_seconds=round(after['cpu_user_seconds']+after['cpu_system_seconds']-before['cpu_user_seconds']-before['cpu_system_seconds'],4),
            cumulative_process_peak_rss_kib=after['cumulative_process_peak_rss_kib'],result=result))
    def period(item):
        actual=dict(overview=overview(archive,scope,item['start'],item['end'])['queues'],
                    agents=agents(archive,scope,item['start'],item['end'])['rows'])
        spec=dict(dataset='queue_visits',queues=list(scope.queues),columns=['queue'],group_by=['queue'],filters={})
        actual['builder']=preview(archive,scope,item['start'],item['end'],spec,number_modes={q:'masked' for q in scope.queues})['rows']
        _compare(actual,item['expected'],'monthly_validation')
        with archive.reader() as db:
            count=db.execute('SELECT COUNT(*),COUNT(DISTINCT callid) FROM report_visits WHERE pbx=? AND entered>=? AND entered<?',(archive.pbx,item['start'],item['end'])).fetchone()
        if tuple(count)!=(item['queue_visit_count'],item['unique_synthetic_call_ids']):raise AssertionError('monthly_identity_count_mismatch')
        return dict(visits=count[0],logical_call_ids=count[1],queue_groups=len(actual['overview']),agent_queue_groups=len(actual['agents']))
    ring_days=[]
    for day in metadata['daily']:
        run('day:'+day['date'],lambda item=day:period(item))
        if 'expected_ring_attempts' in day:
            def ring_day(item=day):
                result=ring_attempts(archive,scope,item['start'],item['end'],now=metadata['end'])
                _compare(result['totals'],item['expected_ring_attempts'],'daily_ring_attempts')
                other=ring_attempts(archive,Scope(('8002',)),item['start'],item['end'],now=metadata['end'])
                if other['totals']['attempts']!=0 or other['rows']:raise AssertionError('monthly_ring_scope_mismatch')
                ring_days.append(result['totals'])
                return dict(totals=result['totals'],other_queue_attempts=0,coverage_complete=False)
            run('day:'+day['date']+':ring_attempts',ring_day)
    run('month:overview_agents_builder',lambda:period(metadata))
    def charts():
        result=dashboard(archive,scope,metadata['start'],metadata['end'],interval='day')
        wanted={key:sum(q[key] for q in metadata['expected']['overview']) for key in ('visits','answered','abandoned','transferred','incomplete')}
        _compare(result['totals'],wanted,'monthly_analytics')
        if sum(row['visits'] for row in result['trends'])!=metadata['queue_visit_count']:raise AssertionError('monthly_trend_count_mismatch')
        if len(result['trends'])!=metadata['days']:raise AssertionError('monthly_trend_days_mismatch')
        if sum(row['visits'] for row in result['heatmap'])!=metadata['queue_visit_count']:raise AssertionError('monthly_heatmap_count_mismatch')
        return dict(totals=wanted,trend_days=len(result['trends']),heatmap_visits=sum(row['visits'] for row in result['heatmap']))
    run('month:charts',charts)
    if 'expected_ring_attempts' in metadata:
        def ring_month():
            if len(ring_days)!=metadata['days']:raise AssertionError('monthly_ring_days_incomplete')
            totals={key:sum(item[key] for item in ring_days) for key in ('attempts','known_duration_attempts','unknown_duration_attempts','known_ring_seconds','matched_visit_attempts','unmatched_visit_attempts')}
            totals['average_known_ring_seconds']=totals['known_ring_seconds']/totals['known_duration_attempts'] if totals['known_duration_attempts'] else None
            _compare(totals,metadata['expected_ring_attempts'],'monthly_daily_ring_sum')
            try:result=ring_attempts(archive,scope,metadata['start'],metadata['end'],now=metadata['end'])
            except QueryDeadline as error:
                if metadata['event_count']>RING_EVENTS and str(error)=='ring_attempt_source_event_limit':
                    return dict(state='expected_limited',reason=str(error),configured_event_cap=RING_EVENTS,
                                verified_daily_aggregate=totals,monthly_endpoint_complete=False)
                raise
            _compare(result['totals'],metadata['expected_ring_attempts'],'monthly_ring_attempts')
            return dict(state='calculated',totals=result['totals'],coverage_complete=False)
        run('month:ring_attempt_bound',ring_month)
    def ranking():
        result=rank_agents(archive,scope,metadata['start'],metadata['end'])
        if metadata['queue_visit_count']>RANK_VISITS:
            if result['state']!='limited' or result['reason']!='ranking_visit_limit' or result['rows']:raise AssertionError('monthly_ranking_must_refuse_partial')
            return dict(state='expected_limited',reason=result['reason'],configured_visit_cap=RANK_VISITS,complete=False)
        if result['state']=='limited' and result['reason']=='ranking_identity_interval_limit':
            return dict(state='expected_limited',reason=result['reason'],complete=False)
        if result['state']!='available':raise AssertionError('monthly_ranking_unexpected_state')
        return dict(state=result['state'],rows=len(result['rows']),complete=False)
    run('month:ranking_bound',ranking)
    def activity():
        try:result=agent_metrics(archive,scope,metadata['start'],metadata['end'],now=metadata['end'])
        except QueryDeadline as error:
            if metadata['queue_visit_count']>10000 and str(error) in ('agent_metric_interval_limit','agent_metric_visit_limit'):
                return dict(state='expected_limited',reason=str(error),complete=False)
            raise
        return dict(state='calculated',agents=len(result['agents']),coverage_complete=result['coverage']['complete'])
    run('month:agent_activity_bound',activity)
    return checks


def _validate_rows(rows,metadata):
    ids=set();queues={q:0 for q in metadata['queues']};count=0
    for row in rows:
        if len(row)!=len(COLUMNS):raise AssertionError('monthly_export_columns_mismatch')
        queue=row[0].removeprefix("'");ident=row[-1].removeprefix("'")
        if queue not in queues or not re.fullmatch('[a-f0-9]{64}',ident) or ident in ids:raise AssertionError('monthly_export_scope_or_identity_mismatch')
        ids.add(ident);queues[queue]+=1;count+=1
    if count!=metadata['queue_visit_count']:raise AssertionError('monthly_export_count_mismatch')
    if queues!={item['queue']:item['visits'] for item in metadata['expected']['overview']}:raise AssertionError('monthly_export_queue_count_mismatch')
    return dict(rows=count,distinct_visit_ids=len(ids),queues=queues)


def _xlsx_rows(stream):
    ns='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    with ZipFile(stream) as archive:
        with archive.open('xl/worksheets/sheet1.xml') as sheet:
            parser=ET.iterparse(sheet,events=('start','end'));_,root=next(parser);sheet_data=None
            for event,node in parser:
                if event=='start' and node.tag==ns+'sheetData':sheet_data=node
                if event!='end' or node.tag!=ns+'row':continue
                row_number=int(node.attrib['r']);values=[]
                for cell in node:
                    value=cell.find(ns+'is/'+ns+'t') if cell.get('t')=='inlineStr' else cell.find(ns+'v')
                    column=re.match('[A-Z]+',cell.attrib['r']).group();index=0
                    for char in column:index=index*26+ord(char)-64
                    while len(values)<index:values.append('')
                    values[index-1]=value.text or '' if value is not None else ''
                if row_number==4:
                    if values!=list(COLUMNS):raise AssertionError('monthly_xlsx_header_mismatch')
                elif row_number>4:
                    while len(values)<len(COLUMNS):values.append('')
                    yield values
                node.clear()
                if sheet_data is not None:sheet_data.clear()


def _exports(archive,metadata,destination):
    output=_new_destination(destination);output.mkdir(mode=0o700)
    store=JobStore(output/'jobs.sqlite3',output/'private-exports');store.initialize()
    scope=Scope(tuple(metadata['queues']));pinned=builder_exports.capture(archive)
    spec=dict(dataset='queue_visits',queues=list(scope.queues),columns=list(COLUMNS),group_by=[],filters={})
    modes={q:'masked' for q in scope.queues};limits=Limits();results=[]
    for format in ('csv','xlsx'):
        started=time.monotonic();before=resources()
        ident=store.create('synthetic-validator',scope,metadata['start'],metadata['end'],builder_definition=spec,number_modes=modes,format=format,language='en',**pinned)
        def authorize(job):
            return job['owner']=='synthetic-validator' and set(job['scope']['queues'])==set(scope.queues) and job['builder_definition']==spec and job['number_modes']==modes
        worker=ExportWorker(store,archive,limits=limits,authorize=authorize,disabled_file=output/'disabled')
        try:result=worker.run_once()
        finally:
            if hasattr(worker,'reconciler'):worker.reconciler.close()
        verification=None;state='failed'
        if result['state']=='completed':
            fd,size=store.open_output(ident,'synthetic-validator')
            with os.fdopen(fd,'rb') as stream:
                if format=='csv':
                    text=io.TextIOWrapper(stream,encoding='utf-8-sig',newline='');rows=csv.reader(text)
                    if next(rows)!=list(COLUMNS):raise AssertionError('monthly_csv_header_mismatch')
                    verification=_validate_rows(rows,metadata)
                else:verification=_validate_rows(_xlsx_rows(stream),metadata)
            if store.get(ident,'synthetic-validator')['rows']!=metadata['queue_visit_count']:raise AssertionError('monthly_job_row_mismatch')
            state='passed'
        after=resources()
        results.append(dict(format=format,state=state,job=result,verification=verification,
            checksum_sha256=store.get(ident,'synthetic-validator')['checksum'],
            elapsed_seconds=round(time.monotonic()-started,4),cpu_seconds=round(after['cpu_user_seconds']+after['cpu_system_seconds']-before['cpu_user_seconds']-before['cpu_system_seconds'],4),
            cumulative_process_peak_rss_kib=after['cumulative_process_peak_rss_kib']))
    return dict(checks=results,limits=asdict(limits),xlsx_xml_limit_bytes=64*1024*1024,
                snapshot=pinned,resource_scope='same verifier process; peak RSS is cumulative, not per job or cgroup')


def verify(fixture,*,export_output=None,write_exports=False):
    directory,metadata=_read_manifest(fixture)
    if write_exports and export_output is None:raise ValueError('monthly_export_output_required')
    if export_output is not None and not write_exports:raise ValueError('monthly_export_write_opt_in_required')
    archive=Archive(directory/'history.sqlite3')
    checks=_read_checks(archive,metadata)
    exports=_exports(archive,metadata,export_output) if write_exports else None
    passed=all(item['state']=='passed' for item in checks) and (exports is None or all(item['state']=='passed' for item in exports['checks']))
    return dict(synthetic=True,passed=passed,days=metadata['days'],calls_per_day=metadata['calls_per_day'],
                queue_visit_count=metadata['queue_visit_count'],unique_synthetic_call_ids=metadata['unique_synthetic_call_ids'],checks=checks,exports=exports,
                python=platform.python_version(),report_scale_only=True,live_calls=False,rtp_assessed=False,
                ring_attempts_included='expected_ring_attempts' in metadata,
                limits_unchanged=True,resources=resources())


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--fixture',type=Path,required=True)
    parser.add_argument('--export-output',type=Path);parser.add_argument('--write-exports',action='store_true');args=parser.parse_args(argv)
    result=verify(args.fixture,export_output=args.export_output,write_exports=args.write_exports)
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
