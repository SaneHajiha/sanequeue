"""Permission-checked, bounded background agent summaries.

The web process only queues jobs and reads finished artifacts. All source
scans and aggregation run inside the existing resource-limited export worker.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
import uuid

from . import activity_snapshots, agent_background
from .export_jobs import JobStore, ExportFailure, _Cancelled, _Deferred, _json, _worker_lock
from .queries import Scope, _where


class AgentJobStore(JobStore):
    def create_summary(self, owner, scope, start, end, snapshot, *, min_samples, top, request_key):
        if not isinstance(owner, str) or not 1 <= len(owner) <= 128:
            raise ValueError('invalid_export_owner')
        _where(snapshot['pbx'], scope, start, end)
        activity_snapshots.validate_pair_token(snapshot)
        queues = tuple(dict.fromkeys(scope.queues))
        if not queues or len(queues) > 256 or scope.self_only or end-start > 31*86400:
            raise ValueError('invalid_agent_summary_scope')
        if type(min_samples) is not int or not 1 <= min_samples <= 100 or type(top) is not int or not 1 <= top <= 20:
            raise ValueError('invalid_aggregation_ranking')
        if not isinstance(request_key, str) or not re.fullmatch('[A-Za-z0-9_.:-]{1,128}', request_key):
            raise ValueError('invalid_export_request_key')
        spec = dict(owner=owner, pbx=snapshot['pbx'], start=float(start), end=float(end),
                    watermark=snapshot['watermark'], snapshot=snapshot,
                    scope=dict(queues=list(queues), agents=list(scope.agents), self_only=False,
                               not_before=float(scope.not_before)),
                    number_modes={q:'masked' for q in queues}, format='json',
                    unit='agent_summary', min_samples=min_samples, top=top)
        payload = _json(spec)
        core = {key:value for key,value in spec.items() if key not in ('watermark','snapshot')}
        request_hash = hashlib.sha256(_json(core).encode()).hexdigest()
        now=time.time(); ident=uuid.uuid4().hex
        with self._db(write=True) as db:
            prior=db.execute('SELECT * FROM export_jobs WHERE owner=? AND request_key=?',(owner,request_key)).fetchone()
            if prior:
                self._public(prior)
                if prior['request_hash']!=request_hash:raise ExportFailure('export_request_conflict')
                return prior['id']
            counts=db.execute("SELECT COUNT(*),COALESCE(SUM(owner=?),0) FROM export_jobs WHERE state IN ('queued','running')",(owner,)).fetchone()
            if counts[0]>=10 or counts[1]>=3:raise ExportFailure('export_queue_quota')
            db.execute('INSERT INTO export_jobs(id,owner,state,spec,spec_hash,created,updated,available_at,request_key,request_hash) VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (ident,owner,'queued',payload,hashlib.sha256(payload.encode()).hexdigest(),now,now,now,request_key,request_hash))
        return ident


class AgentSummaryWorker:
    def __init__(self, store, archive, gate, authorize):
        self.store=store; self.archive=archive; self.gate=gate; self.authorize=authorize

    def run_once(self):
        with _worker_lock(str(self.store.path)+'.worker.lock') as acquired:
            if not acquired:return dict(state='busy')
            try:self.gate()
            except _Deferred as error:return dict(state='deferred',error=str(error))
            worker=uuid.uuid4().hex
            job=self.store.claim(worker,lease_seconds=300)
            if job is None:return dict(state='idle')
            ident=job['id']; spec=job['spec']; work=self.store.output_dir/(ident+'.'+worker+'.work')
            final=self.store.output_dir/(ident+'.json'); published=False; scratch_expected=False
            def check(rows):
                self.gate()
                if not self.authorize(spec) or spec['pbx']!=self.archive.pbx:
                    raise ExportFailure('agent_access_denied')
                if not self.store._update(ident,worker,rows=rows,lease_seconds=300):
                    raise _Cancelled('cancelled')
            try:
                check(0)
                if final.exists() or final.is_symlink():raise ExportFailure('agent_summary_output_exists')
                if work.exists() or work.is_symlink():raise ExportFailure('agent_summary_scratch_exists')
                scratch_expected=True
                scope=Scope(tuple(spec['scope']['queues']),tuple(spec['scope']['agents']),
                            spec['scope']['self_only'],spec['scope']['not_before'])
                result=agent_background.run_pinned(self.archive,spec['snapshot'],work,scope,spec['start'],spec['end'],
                    min_samples=spec['min_samples'],top=spec['top'],checkpoint=check)
                artifact=work/'result.json'
                data=artifact.read_bytes()
                if not 0<len(data)<=2*1024**2:raise ExportFailure('agent_summary_limit')
                digest=hashlib.sha256(data).hexdigest(); rows=result['limits']['scanned_rows']
                check(rows)
                os.link(artifact,final);published=True
                check(rows)
                if not self.store._update(ident,worker,state='completed',rows=rows,size=len(data),checksum=digest):
                    raise _Cancelled('cancelled')
                return dict(id=ident,state='completed',rows=rows,bytes=len(data))
            except _Deferred as error:
                self.store._defer(ident,worker,str(error));return dict(id=ident,state='queued',error=str(error))
            except _Cancelled:
                return dict(id=ident,state='cancelled')
            except Exception as error:
                safe_aggregation_errors={'aggregation_row_limit','aggregation_deadline','aggregation_disk_pressure',
                    'aggregation_identity_unavailable','aggregation_agent_limit','aggregation_result_limit',
                    'agent_identity_unresolved'}
                reason=(str(error) if isinstance(error,ExportFailure) or
                        isinstance(error,agent_background.AggregationError) and str(error) in safe_aggregation_errors
                        else 'agent_snapshot_unavailable' if isinstance(error,activity_snapshots.SnapshotUnavailable)
                        else 'agent_summary_failed')
                self.store._update(ident,worker,state='failed',error=reason)
                return dict(id=ident,state='failed',error=reason)
            finally:
                if published:
                    current=self.store.get(ident,job['owner'])
                    if current is None or current['state']!='completed':final.unlink(missing_ok=True)
                # Only this attempt's freshly created, private scratch directory.
                if scratch_expected and work.is_dir() and not work.is_symlink():
                    shutil.rmtree(work)


def read_result(store, ident, owner):
    job=store.get(ident,owner)
    if not job or job['state']!='completed':raise FileNotFoundError('agent_summary_not_completed')
    fd,size=store.open_output(ident,owner)
    with os.fdopen(fd,'rb') as stream:
        if size>2*1024**2:raise ExportFailure('agent_summary_limit')
        data=stream.read(size+1)
    if len(data)!=size or hashlib.sha256(data).hexdigest()!=job['checksum']:
        raise ExportFailure('agent_summary_integrity')
    return json.loads(data)
