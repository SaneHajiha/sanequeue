"""Dispatch private scheduled exports using current local account/queue grants."""
import argparse
import json
import os
from pathlib import Path
import time
import uuid

from qpanel.local_accounts import read_accounts
from qpanel.queue_policies import QueuePolicyStore
from sanequeue.security.permissions import sections_for
from .export_jobs import JobStore,ExportFailure,projection_watermark,_worker_lock
from .report_plans import SavedReports
from .queries import Scope
from .store import Archive
from .visit_snapshots import capture,SnapshotUnavailable


def current_modes(owner,queues,accounts_path,policy_path):
    account=read_accounts(accounts_path).get(owner)
    if not account or account.get('role') not in ('admin','supervisor') or 'reports' not in sections_for(account['role'],account):
        return None
    # Instantiate for this dispatch only: never retain grants across changes.
    policy=QueuePolicyStore(policy_path);role=account['role']
    if not queues or not all(policy.access(owner,role,queue,cap) for queue in queues for cap in ('view','report_export')):
        return None
    return {queue:'full' if policy.access(owner,role,queue,'caller_details') else 'masked' for queue in queues}


class PlanWorker:
    def __init__(self,plans,jobs,archive,authorize,*,disabled_file='/var/lib/sanequeue/module.disabled'):
        self.plans=plans;self.jobs=jobs;self.archive=archive;self.authorize=authorize;self.disabled_file=Path(disabled_file)

    def _modes(self,spec):
        try:modes=self.authorize(spec['owner'],spec['queues'])
        except Exception:return None
        if not isinstance(modes,dict) or set(modes)!=set(spec['queues']) or any(
                mode not in ('full','masked','hidden','pseudonymous') for mode in modes.values()):return None
        return modes

    def _cancel_if_inactive(self,occurrence,export_id):
        """Losing a lease alone never cancels the recovering worker's export."""
        plan=self.plans.get(occurrence['plan_id'],occurrence['owner'])
        current=self.plans.occurrence(occurrence['id'],occurrence['owner'])
        inactive=not plan or not plan['enabled'] or plan['archived'] or current is None or current['state']=='cancelled'
        if inactive and export_id:self.jobs.cancel(export_id,occurrence['owner'])
        return inactive

    def _preflight(self,occurrence,worker,*,export_id=None,number_modes=None):
        spec=occurrence['spec'];ident=occurrence['id']
        if export_id and self._cancel_if_inactive(occurrence,export_id):
            return None,dict(state='cancelled')
        if self.disabled_file.exists():
            self.plans.defer(ident,worker,'module_disabled')
            return None,dict(state='queued',reason='module_disabled')
        modes=self._modes(spec)
        if modes is None or number_modes is not None and any(
                number_modes.get(queue)=='full' and modes[queue]!='full' for queue in spec['queues']):
            if export_id:self.jobs.cancel(export_id,spec['owner'])
            self.plans.fail(ident,worker,'access_revoked')
            return None,dict(state='failed',reason='access_revoked')
        if not self.plans.renew(ident,worker):
            inactive=self._cancel_if_inactive(occurrence,export_id)
            return None,dict(state='cancelled' if inactive else 'lease_lost')
        return modes,None

    def _validate_prior(self,prior,spec):
        original=prior['spec'];scope=original.get('scope',{})
        # A request key cannot acknowledge a different period/format/scope.
        if (original.get('owner')!=spec['owner'] or original.get('pbx')!=self.archive.pbx
                or scope.get('queues')!=spec['queues'] or scope.get('agents')!=[]
                or scope.get('self_only') is not False or scope.get('not_before')!=0
                or any(original.get(key)!=spec[key] for key in ('start','end','outcome','format','language'))
                or set(original.get('number_modes',{}))!=set(spec['queues'])):
            raise ExportFailure('export_request_conflict')

    def run_once(self):
        if self.disabled_file.exists():return dict(state='paused')
        with _worker_lock(str(self.plans.path)+'.worker.lock') as acquired:
            if not acquired:return dict(state='busy')
            worker=uuid.uuid4().hex;occurrence=self.plans.reserve_due(worker)
            if occurrence is None:return dict(state='idle')
            ident=occurrence['id'];spec=occurrence['spec'];export_id=None
            try:
                modes,stopped=self._preflight(occurrence,worker)
                if stopped:return stopped
                # Cross-database recovery: the same occurrence always reuses
                # the original export and its original immutable snapshot.
                key='schedule:'+ident;prior=self.jobs.by_request(spec['owner'],key)
                if prior is not None:
                    self._validate_prior(prior,spec)
                    export_id=prior['id']
                else:
                    watermark=projection_watermark(self.archive);snapshot=capture(self.archive)
                    # Snapshot reads can race a plan/account change. Refresh
                    # grants and the active lease immediately before dispatch.
                    modes,stopped=self._preflight(occurrence,worker)
                    if stopped:return stopped
                    export_id=self.jobs.create(spec['owner'],Scope(tuple(spec['queues'])),spec['start'],spec['end'],
                        watermark=watermark,pbx=self.archive.pbx,number_modes=modes,
                        format=spec['format'],language=spec['language'],outcome=spec['outcome'],
                        snapshot=snapshot,request_key=key)
                    prior=self.jobs.get(export_id,spec['owner'])
                    self._validate_prior(prior,spec)
                _,stopped=self._preflight(occurrence,worker,export_id=export_id,number_modes=prior['spec']['number_modes'])
                if stopped:return stopped
                if not self.plans.finish(ident,worker,export_id):
                    inactive=self._cancel_if_inactive(occurrence,export_id)
                    return dict(state='cancelled' if inactive else 'lease_lost')
                # This is dispatch acknowledgement, not a promise that a file
                # succeeded. Cancelled/failed prior exports are never revived.
                return dict(state='dispatched',export_job_id=export_id,export_state=prior['state'])
            except SnapshotUnavailable:
                self.plans.defer(ident,worker,'export_unavailable');return dict(state='queued',reason='export_unavailable')
            except ExportFailure as error:
                if str(error)=='export_queue_quota':
                    self.plans.defer(ident,worker,'system_busy');return dict(state='queued',reason='system_busy')
                self.plans.fail(ident,worker,'export_failed');return dict(state='failed',reason='export_failed')
            except Exception:
                if export_id:
                    # Missing policy/plan evidence must not leave a newly
                    # dispatched queued/running export active. Completed
                    # artifacts are immutable and cancel() leaves them alone.
                    self.jobs.cancel(export_id,spec['owner'])
                self.plans.fail(ident,worker,'export_failed');return dict(state='failed',reason='export_failed')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for field in ('plans','jobs','outputs','archive','accounts','policies'):parser.add_argument('--'+field,required=True)
    parser.add_argument('--disabled-file',default='/var/lib/sanequeue/module.disabled');parser.add_argument('--once',action='store_true')
    args=parser.parse_args();plans=SavedReports(args.plans);plans.initialize();jobs=JobStore(args.jobs,args.outputs);jobs.initialize()
    worker=PlanWorker(plans,jobs,Archive(args.archive),lambda owner,queues:current_modes(owner,queues,args.accounts,args.policies),disabled_file=args.disabled_file)
    while True:
        result=worker.run_once()
        if args.once:print(json.dumps(result));break
        time.sleep(15)


if __name__=='__main__':main()
