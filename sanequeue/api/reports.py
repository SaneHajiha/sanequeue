"""Authenticated historical reports backed only by the local reporting archive."""
import csv
from datetime import datetime, timedelta
import hashlib
import hmac
import io
import os
import re
from pathlib import Path
import sqlite3
import time
from zoneinfo import ZoneInfo

from flask import abort, jsonify, request, Response, g, session
from flask_login import login_required, current_user
from werkzeug.exceptions import HTTPException

from sanequeue.reporting import queries
from sanequeue.reporting import exports
from sanequeue.reporting import activity_queries
from sanequeue.reporting import outbound
from sanequeue.reporting import analytics
from sanequeue.reporting import followup
from sanequeue.reporting import agent_metrics
from sanequeue.reporting.export_jobs import JobStore, ExportFailure, projection_watermark
from sanequeue.reporting.access_audit import AuditStore, AuditUnavailable
from sanequeue.reporting import work_sessions
from sanequeue.reporting import visit_snapshots
from sanequeue.reporting import adherence, adherence_source
from sanequeue.reporting import cdr_queries
from sanequeue.reporting import journey
from sanequeue.reporting.quality import QualityStore, QualityConflict, QualityUnavailable
from sanequeue.reporting.ai_jobs import AIJobs, AIConflict, AIUnavailable
from sanequeue.reporting.report_plans import SavedReports,PlanConflict,PlanUnavailable,period_bounds
from sanequeue.reporting.recording_scope import ownership as recording_ownership
from sanequeue.reporting.audio import byte_range, open_recording, duration_seconds, AudioDurationUnavailable
from sanequeue.reporting.privacy import display_number
from sanequeue.reporting.store import Archive, QueryDeadline


def install(app, path, *, role, sections, can_queue, own_interfaces=lambda: (), own_since=lambda: 0,
            recording_root='/var/spool/asterisk/monitor', pbx='primary',reason_label=lambda queue,reason:reason,
            known_agents=lambda: (), planning_path=None, shift_identity=None):
    archive = Archive(path, pbx=pbx)
    export_store = JobStore(archive.path.parent/'export-jobs.sqlite3', archive.path.parent/'private-exports')
    audit_store = AuditStore(archive.path.parent/'recording-access.sqlite3')
    work_store = work_sessions.WorkSessions(archive.path.parent/'work-sessions.sqlite3', pbx=pbx)
    quality_store=QualityStore(archive.path.parent/'quality.sqlite3',pbx=pbx)
    ai_store=AIJobs(archive.path.parent/'ai-jobs.sqlite3',pbx=pbx)
    plans_store=SavedReports(archive.path.parent/'report-plans.sqlite3',pbx=pbx)
    try:
        plans_store.initialize();plans_ready=True
    except (OSError,sqlite3.Error,ValueError,PlanUnavailable):
        plans_ready=False;app.logger.warning('Saved report storage unavailable')
    try:
        ai_store.initialize();ai_ready=True
    except (OSError,sqlite3.Error,ValueError,AIUnavailable):
        ai_ready=False;app.logger.warning('AI job storage unavailable')
    try:
        quality_store.initialize();quality_ready=True
    except (OSError,sqlite3.Error,ValueError,QualityUnavailable):
        quality_ready=False;app.logger.warning('Quality review storage unavailable')
    try:
        work_store.initialize()
        work_ready = True
    except (OSError, sqlite3.Error, ValueError, work_sessions.SessionUnavailable):
        work_ready = False
        app.logger.warning('Work session storage unavailable')
    try:
        audit_store.initialize()
        audit_ready = True
    except (OSError, sqlite3.Error, ValueError, AuditUnavailable):
        audit_ready = False
        app.logger.warning('Recording access audit unavailable; audio will remain closed')
    app.config['SANEQUEUE_HISTORY_INSTALLED'] = True

    def recording_permitted(archive,ident,capability,can_queue,*,fallback_queues=()):
        # Cache ownership only within this HTTP request, then recheck each
        # capability. Never cache grants across requests or users. A page of
        # audio proofs has a shared one-second budget, not N times five seconds.
        cache=g.setdefault('report_recording_proofs',{})
        deadline=g.setdefault('report_recording_deadline',time.monotonic()+1)
        key=(ident,tuple(sorted(fallback_queues)))
        if key not in cache:
            remaining=deadline-time.monotonic()
            if remaining<=0:cache[key]=False
            else:
                bounded=Archive(archive.path,pbx=archive.pbx,read_seconds=min(.2,remaining))
                try:cache[key]=recording_ownership(bounded,ident,fallback_queues=fallback_queues)
                except QueryDeadline:cache[key]=False
        queues=cache[key]
        return bool(queues) and all(can_queue(queue,capability) for queue in queues)

    def context(*, restrict_queue=True):
        if 'reports' not in sections():
            abort(403)
        # The web process never initializes, imports or rebuilds the archive.
        if not archive.path.is_file():
            abort(503, description='report_archive_not_initialized')
        allowed = tuple(q for q in queries.queues(archive) if can_queue(q, 'view'))
        selected_queue = request.args.get('queue')
        if selected_queue:
            if selected_queue not in allowed:
                abort(403)
            if restrict_queue:
                allowed = (selected_queue,)
        if len(allowed) > 256:
            abort(422, description='report_scope_limit')
        today = datetime.now(ZoneInfo('Asia/Tehran')).date()
        start = datetime.fromisoformat(request.args.get('from', today.isoformat())).date()
        end = datetime.fromisoformat(request.args.get('to', today.isoformat())).date() + timedelta(days=1)
        if not 0 < (end - start).days <= 366:
            raise ValueError('invalid_report_range')
        zone = ZoneInfo('Asia/Tehran')
        start_ts = datetime.combine(start, datetime.min.time(), zone).timestamp()
        end_ts = datetime.combine(end, datetime.min.time(), zone).timestamp()
        own = role() == 'agent'
        return queries.Scope(allowed, tuple(own_interfaces()), own, own_since() if own else 0), start_ts, end_ts

    def protect_number(row):
        row = dict(row)
        secret = hashlib.sha256(('sanequeue.reporting.numbers:' + str(app.secret_key)).encode()).digest()
        row['caller'] = display_number(row['caller'], mode='full' if can_queue(row['queue'], 'caller_details') else 'masked',
                                       secret=secret, tenant='default', pbx=pbx, version='1')
        return row

    def safe(function):
        from functools import wraps
        @wraps(function)
        def wrapped(*args, **kwargs):
            try:
                response = app.make_response(function(*args, **kwargs))
            except (ValueError, TypeError, OverflowError):
                response = app.make_response((jsonify(error='invalid_report_request'), 400))
            except QueryDeadline:
                response = app.make_response((jsonify(error='report_query_deadline'), 422))
            except visit_snapshots.SnapshotUnavailable as error:
                response = app.make_response((jsonify(error=str(error)), 503))
            except ExportFailure as error:
                response = app.make_response((jsonify(error=str(error)), 422))
            except AuditUnavailable:
                response = app.make_response((jsonify(error='recording_audit_unavailable'), 503))
            except QualityUnavailable:
                response = app.make_response((jsonify(error='quality_storage_unavailable'), 503))
            except QualityConflict:
                response = app.make_response((jsonify(error='quality_request_conflict'), 409))
            except AIUnavailable:
                response = app.make_response((jsonify(error='ai_storage_unavailable'), 503))
            except AIConflict:
                response = app.make_response((jsonify(error='ai_request_conflict_or_quota'), 409))
            except PlanUnavailable:
                response = app.make_response((jsonify(error='report_plans_unavailable'), 503))
            except PlanConflict:
                response = app.make_response((jsonify(error='report_plan_conflict_or_quota'), 409))
            except work_sessions.SessionUnavailable:
                response = app.make_response((jsonify(error='work_sessions_unavailable'), 503))
            except work_sessions.SessionAccessDenied:
                response = app.make_response((jsonify(error='report_access_denied'), 403))
            except work_sessions.SessionConflict:
                response = app.make_response((jsonify(error='work_session_conflict'), 409))
            except (sqlite3.Error, OSError):
                response = app.make_response((jsonify(error='report_archive_unavailable'), 503))
            except HTTPException as error:
                message = {403: 'report_access_denied', 404: 'report_not_found',
                           415: 'recording_codec_requires_conversion',
                           503: 'report_archive_not_initialized'}.get(error.code, 'report_request_failed')
                if error.code == 503 and error.description == 'export_service_not_initialized':
                    message = 'export_service_not_initialized'
                if error.code==415 and error.description in ('recording_duration_parser_unavailable',
                        'recording_duration_budget_exceeded','recording_duration_invalid_metadata',
                        'recording_duration_unsupported','recording_duration_invalid_source','recording_duration_invalid_seek'):
                    message=error.description
                response = app.make_response((jsonify(error=message), error.code))
            response.headers['Cache-Control'] = 'private, no-store'
            response.headers['X-Content-Type-Options'] = 'nosniff'
            return response
        return wrapped

    def export_context():
        if 'reports' not in sections() or role() not in ('admin', 'supervisor'):
            abort(403)
        # Initialization belongs to the service, not an HTTP GET or POST.
        if not export_store.path.is_file() or not export_store.output_dir.is_dir():
            abort(503, description='export_service_not_initialized')
        return str(current_user.get_id())

    def export_csrf():
        token = request.headers.get('X-CSRF-Token', '')
        if not token or not session.get('csrf_token') or not hmac.compare_digest(token, session['csrf_token']):
            abort(403)

    def export_permitted(job):
        if not job:
            return False
        spec = job['spec']
        if spec['pbx'] != pbx:
            return False
        for queue in spec['scope']['queues']:
            if not can_queue(queue, 'view') or not can_queue(queue, 'report_export'):
                return False
            if spec['number_modes'][queue] == 'full' and not can_queue(queue, 'caller_details'):
                return False
        return True

    def export_public(job):
        return {key: job[key] for key in ('id', 'state', 'created', 'updated', 'rows', 'bytes', 'error_code')} | {
            'format': job['spec']['format'], 'start': job['spec']['start'], 'end': job['spec']['end']}

    @app.route('/api/history/export-jobs', methods=['GET', 'POST'])
    @login_required
    @safe
    def history_export_jobs():
        owner = export_context()
        if request.method == 'GET':
            from sanequeue.reporting.export_maintenance import owner_artifacts
            recovery=[]
            for item in owner_artifacts(export_store,owner):
                if export_permitted(export_store.get(item['job_id'],owner)):recovery.append(item)
            return jsonify(jobs=[export_public(job) for job in export_store.list(owner) if export_permitted(job)],
                           recovery=recovery,recovery_limit=20)
        export_csrf()
        scope, start, end = context()
        if not scope.queues or not all(can_queue(queue, 'report_export') for queue in scope.queues):
            abort(403)
        modes = {queue: 'full' if can_queue(queue, 'caller_details') else 'masked' for queue in scope.queues}
        ident = export_store.create(owner, scope, start, end, watermark=projection_watermark(archive), pbx=pbx,
                                    number_modes=modes, language=request.args.get('lang', 'en'),
                                    outcome=request.args.get('outcome'), format=request.args.get('format', 'csv'),
                                    snapshot=visit_snapshots.capture(archive))
        app.logger.info('report export queued user=%r job=%s', owner, ident)
        return jsonify(export_public(export_store.get(ident, owner))), 202

    @app.post('/api/history/export-jobs/<ident>/cancel')
    @login_required
    @safe
    def history_export_cancel(ident):
        owner = export_context()
        export_csrf()
        job = export_store.get(ident, owner)
        if not job:
            abort(404)
        if not export_permitted(job):
            abort(403)
        changed = export_store.cancel(ident, owner)
        return jsonify(cancelled=changed, job=export_public(export_store.get(ident, owner)))

    @app.get('/api/history/export-jobs/<ident>/download')
    @login_required
    @safe
    def history_export_download(ident):
        owner = export_context()
        job = export_store.get(ident, owner)
        if not job:
            abort(404)
        if not export_permitted(job):
            abort(403)
        try:
            fd, size = export_store.open_output(ident, owner)
        except FileNotFoundError:
            abort(404)
        stream = os.fdopen(fd, 'rb')
        def chunks():
            try:
                while True:
                    chunk = stream.read(65536)
                    if not chunk:
                        break
                    yield chunk
            finally:
                stream.close()
        extension=job['spec']['format']
        mime={'xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','pdf':'application/pdf',
              'csv':'text/csv; charset=utf-8'}[extension]
        result = Response(chunks(), mimetype=mime, headers={
            'Content-Length': str(size), 'Content-Disposition': f'attachment; filename="sanequeue-{ident}.{extension}"'})
        result.call_on_close(stream.close)
        app.logger.info('report export downloaded user=%r job=%s rows=%s', owner, ident, job['rows'])
        return result

    def plan_permitted(plan):
        return plan is not None and all(can_queue(queue,cap) for queue in plan['queues'] for cap in ('view','report_export'))

    def plan_context(ident=None):
        owner=export_context();scope,start,end=context()
        if not plans_ready:raise PlanUnavailable('report_plans_unavailable')
        plan=plans_store.get(ident,owner) if ident else None
        if ident and plan is None:abort(404)
        if plan and not plan_permitted(plan):abort(403)
        return owner,scope,plan

    @app.route('/api/history/plans',methods=['GET','POST'])
    @login_required
    @safe
    def history_plans():
        owner,scope,_=plan_context()
        if request.method=='GET':return jsonify(plans=[plan for plan in plans_store.list(owner) if plan_permitted(plan)])
        export_csrf();body=request.get_json(silent=True)
        if not isinstance(body,dict):raise ValueError('invalid_report_plan')
        queues=body.get('queues')
        if not isinstance(queues,list) or not queues or not set(queues).issubset(scope.queues):abort(403)
        if not all(can_queue(queue,'report_export') for queue in queues):abort(403)
        if body.get('id'):
            previous=plans_store.get(body['id'],owner)
            if previous is None:abort(404)
            if not plan_permitted(previous):abort(403)
        plan=plans_store.save(owner,body.get('name'),queues,outcome=body.get('outcome'),format=body.get('format','xlsx'),
            language=body.get('language','fa'),period=body.get('period','yesterday'),at=body.get('at','08:00'),
            weekdays=body.get('weekdays'),enabled=body.get('enabled',False),ident=body.get('id'))
        return jsonify(plan=plan),201

    @app.post('/api/history/plans/<ident>/archive')
    @login_required
    @safe
    def history_plan_archive(ident):
        owner,_,_=plan_context(ident);export_csrf()
        return jsonify(archived=plans_store.delete(ident,owner))

    @app.post('/api/history/plans/<ident>/run')
    @login_required
    @safe
    def history_plan_run(ident):
        owner,_,plan=plan_context(ident);export_csrf()
        if plan['archived']:abort(403)
        body=request.get_json(silent=True)
        if not isinstance(body,dict) or not isinstance(body.get('request_key'),str):raise ValueError('invalid_report_plan_run')
        if not re.fullmatch('[A-Za-z0-9_.:-]{1,128}',body['request_key']):raise ValueError('invalid_report_plan_run')
        request_key='manual:'+ident+':'+hashlib.sha256(body['request_key'].encode()).hexdigest()
        previous=export_store.by_request(owner,request_key)
        if previous is not None:
            # Retry the original request, including its original period, even
            # if Tehran midnight or a later plan edit has changed defaults.
            if not export_permitted(previous):abort(403)
            return jsonify(job=export_public(previous)),202
        period=period_bounds(time.time(),plan['period'])
        modes={queue:'full' if can_queue(queue,'caller_details') else 'masked' for queue in plan['queues']}
        try:
            job_id=export_store.create(owner,queries.Scope(tuple(plan['queues'])),period['start'],period['end'],
                watermark=projection_watermark(archive),pbx=pbx,number_modes=modes,format=plan['format'],language=plan['language'],
                outcome=plan['outcome'],snapshot=visit_snapshots.capture(archive),request_key=request_key)
        except ExportFailure as error:
            # Another request may have won the unique key after our lookup,
            # including on the other side of midnight. It remains the original.
            if str(error)!='export_request_conflict':raise
            previous=export_store.by_request(owner,request_key)
            if previous is None:raise
            if not export_permitted(previous):abort(403)
            job_id=previous['id']
        return jsonify(job=export_public(export_store.get(job_id,owner))),202

    @app.get('/api/history/plans/<ident>/runs')
    @login_required
    @safe
    def history_plan_runs(ident):
        owner,_,_=plan_context(ident)
        runs=[]
        for run in plans_store.occurrences(ident,owner):
            if not all(can_queue(queue,cap) for queue in run['spec']['queues'] for cap in ('view','report_export')):continue
            job=export_store.get(run['export_job_id'],owner) if run['export_job_id'] else None
            run['export_state']=job['state'] if job and export_permitted(job) else None
            runs.append(run)
        return jsonify(runs=runs)

    @app.get('/api/history/overview')
    @login_required
    @safe
    def history_overview():
        scope, start, end = context()
        result = queries.overview(archive, scope, start, end, sla_seconds=request.args.get('sla', 20))
        result['timezone'] = 'Asia/Tehran'
        result['allowed_queues']=list(scope.queues)
        result['sources']={name:archive.checkpoint('health:'+name) for name in ('queue_log','activity','sql')}
        result['archive'] = archive.status()
        # Checkpoints can identify private source paths; expose only safe fields.
        result['archive'].pop('checkpoints', None)
        return jsonify(result)

    @app.get('/api/history/visits')
    @login_required
    @safe
    def history_visits():
        scope, start, end = context()
        before = (request.args['before_time'], request.args['before_id']) if 'before_time' in request.args and 'before_id' in request.args else None
        result = queries.visits(archive, scope, start, end, before=before,
                                queue=request.args.get('queue'), outcome=request.args.get('outcome'))
        result['rows'] = [protect_number(r) for r in result['rows']]
        return jsonify(result)

    @app.get('/api/history/analytics')
    @login_required
    @safe
    def history_analytics():
        scope, start, end = context()
        if request.args.get('compare', '0') not in ('0', '1'):
            raise ValueError('invalid_report_comparison')
        return jsonify(analytics.dashboard(archive, scope, start, end,
            interval=request.args.get('interval', 'day'), sla_seconds=request.args.get('sla', 20),
            sla_basis=request.args.get('sla_basis', 'answered_known_wait'),
            short_abandon_seconds=request.args.get('short_abandon', 0),
            compare=request.args.get('compare') == '1'))

    @app.get('/api/history/adherence')
    @login_required
    @safe
    def history_adherence():
        scope, start, end = context()
        if 'shifts' not in sections():
            abort(403)
        source=adherence_source.read(planning_path,scope.queues,max(start,scope.not_before),end)
        result=adherence.report(archive,scope,start,end,source['shifts'],agent_aliases=shift_identity)
        result['schedule_configured']=source['configured']
        # Free-form planning notes and account records never reach the API.
        return jsonify(result)

    @app.get('/api/history/followup')
    @login_required
    @safe
    def history_followup():
        scope,start,end=context()
        if role() not in ('admin','supervisor'):abort(403)
        before=(request.args['before_time'],request.args.get('before_id')) if request.args.get('before_time') else None
        result=followup.report(archive,scope,start,end,window_days=int(request.args.get('window_days',7)),before=before)
        result['rows']=[protect_number(row) for row in result['rows']]
        return jsonify(result)

    def cdr_context():
        scope,start,end=context()
        # Global CDR is deliberately separate from queue-scoped reporting.
        # A supervisor's queue grant can never expose unrelated PBX traffic.
        if role()!='admin' or 'users' not in sections() or request.args.get('queue'):
            abort(403)
        all_queues=queries.queues(archive)
        if not all(can_queue(queue,'view') for queue in all_queues):abort(403)
        numbers=bool(all_queues) and all(can_queue(queue,'caller_details') for queue in all_queues)
        keys=('src','dst','party','origin','outbound_cid','did','match','src_length','dst_length',
              'direction','disposition','trunk','hour_from','hour_to','duration_min','duration_max',
              'billsec_min','billsec_max')
        filters={key:request.args[key] for key in keys if request.args.get(key) not in (None,'')}
        if request.args.get('weekdays'):
            filters['weekdays']=request.args['weekdays'].split(',')
        if not numbers and any(key in filters for key in ('src','dst','party','origin','outbound_cid','did','src_length','dst_length')):
            abort(403)
        return start,end,filters,numbers

    @app.get('/api/history/cdr')
    @login_required
    @safe
    def history_cdr():
        start,end,filters,numbers=cdr_context()
        before=None
        if request.args.get('before_time') is not None:
            before=(request.args['before_time'],request.args.get('before_id'))
        data=cdr_queries.page(archive,start,end,filters,before=before)
        secret=hashlib.sha256(('sanequeue.reporting.numbers:'+str(app.secret_key)).encode()).digest()
        for row in data['rows']:
            for key in ('src','dst','internal_caller_ext','outbound_cid','did'):
                if row.get(key) is not None:
                    row[key]=display_number(row[key],mode='full' if numbers else 'masked',secret=secret,tenant='default',pbx=pbx,version='1')
        data['can_search_numbers']=numbers
        data['filters']={} if not numbers else data['filters']
        return jsonify(data)

    @app.get('/api/history/cdr/summary')
    @login_required
    @safe
    def history_cdr_summary():
        start,end,filters,numbers=cdr_context()
        data=cdr_queries.summary(archive,start,end,filters)
        # Trunk labels identify configured routes, not telephone numbers.
        data['can_search_numbers']=numbers
        data['filters']={} if not numbers else data['filters']
        return jsonify(data)

    def work_context():
        scope, start, end = context(restrict_queue=False)
        if not work_ready:
            raise work_sessions.SessionUnavailable('work_sessions_unavailable')
        return scope, start, end

    def work_session(ident):
        scope, start, end = work_context()
        item = work_store.get(ident, scope)
        if not item:
            abort(404)
        return item, scope, start, end

    def work_agents(scope):
        known = set(known_agents())
        if role() == 'agent' and known:
            return sorted(known.intersection(scope.agents))
        if role() == 'admin' and 'users' in sections() and known:
            if len(known)>500:
                raise QueryDeadline('work_agent_limit_narrow_queue')
            return sorted(known)
        clause, args = queries._scope(pbx, scope)
        with archive.reader() as db:
            rows = [row[0] for row in db.execute('''SELECT DISTINCT canonical_agent FROM report_activity
              WHERE '''+clause+" AND canonical_agent<>'' ORDER BY canonical_agent LIMIT 501", args)]
        if len(rows)>500:
            raise QueryDeadline('work_agent_limit_narrow_queue')
        return [agent for agent in rows if not known or agent in known]

    @app.route('/api/history/work-sessions', methods=['GET', 'POST'])
    @login_required
    @safe
    def history_work_sessions():
        scope, start, end = work_context()
        if request.method == 'GET':
            result = work_store.list(scope, before=request.args.get('before'),
                                     state=request.args.get('state'), purpose=request.args.get('purpose'))
            result['agents'] = work_agents(context()[0])
            result['can_manage'] = role() == 'agent' or role() in ('admin','supervisor') and all(
                can_queue(queue, 'pause') for queue in context()[0].queues)
            for item in result['rows']:
                item['can_close'] = item['ended_at'] is None and (
                    role() == 'agent' and item['actor'] == str(current_user.get_id()) or
                    role() in ('admin','supervisor') and all(can_queue(queue,'pause') for queue in item['queues']))
            return jsonify(result)
        export_csrf()
        scope, start, end = context()
        if role() not in ('admin', 'supervisor', 'agent'):
            abort(403)
        if role() != 'agent' and not all(can_queue(queue, 'pause') for queue in scope.queues):
            abort(403)
        obj = request.get_json(silent=True)
        if not isinstance(obj, dict) or not scope.queues:
            raise ValueError('invalid_work_session')
        agent = obj.get('agent')
        if agent not in work_agents(scope) or scope.self_only and agent not in scope.agents:
            abort(403)
        item = work_store.open(str(current_user.get_id()), agent, obj.get('purpose'), obj.get('title'),
                               scope.queues, obj.get('request_key'))
        return jsonify(session=item), 201

    @app.post('/api/history/work-sessions/<ident>/close')
    @login_required
    @safe
    def history_work_close(ident):
        item, scope, start, end = work_session(ident)
        export_csrf()
        if role() not in ('admin', 'supervisor', 'agent'):
            abort(403)
        if role() == 'agent' and item['actor'] != str(current_user.get_id()):
            abort(403)
        if role() != 'agent' and not all(can_queue(queue, 'pause') for queue in item['queues']):
            abort(403)
        return jsonify(session=work_store.close(ident, str(current_user.get_id())))

    @app.get('/api/history/work-sessions/<ident>/summary')
    @login_required
    @safe
    def history_work_summary(ident):
        item, scope, start, end = work_session(ident)
        return jsonify(work_sessions.summary(archive, item, scope, start, end,
                       direction=request.args.get('pause_direction', 'outbound')))

    @app.get('/api/history/work-sessions/<ident>/calls')
    @login_required
    @safe
    def history_work_calls(ident):
        item, scope, start, end = work_session(ident)
        before = (request.args['before_time'], request.args['before_id']) if 'before_time' in request.args and 'before_id' in request.args else None
        result = work_sessions.calls(archive, item, scope, start, end,
                                     direction=request.args.get('pause_direction', 'outbound'), before=before)
        full = all(can_queue(queue, 'caller_details') for queue in item['queues'])
        secret = hashlib.sha256(('sanequeue.reporting.numbers:' + str(app.secret_key)).encode()).digest()
        for row in result['rows']:
            row['destination'] = display_number(row['destination'], mode='full' if full else 'masked',
                secret=secret, tenant='default', pbx=pbx, version='1')
            for key, capability in (('can_play','recording_play'), ('can_download','recording_download')):
                row[key] = bool(row['has_recording'] and role() in ('admin','supervisor') and
                    recording_permitted(archive, row['id'], capability, can_queue, fallback_queues=item['queues']))
        return jsonify(result)

    @app.get('/api/history/work-sessions/<ident>/calls/<recording_id>/recording')
    @login_required
    @safe
    def history_work_recording(ident, recording_id):
        item, scope, start, end = work_session(ident)
        result = work_sessions.calls(archive, item, scope, start, end, ident=recording_id,
                                     direction=request.args.get('pause_direction','outbound'))
        if recording_id not in {row['id'] for row in result['rows']}:
            abort(404)
        download = request.args.get('download') == '1'
        capability = 'recording_download' if download else 'recording_play'
        if role() not in ('admin','supervisor') or not recording_permitted(
                archive,recording_id,capability,can_queue,fallback_queues=item['queues']):
            abort(403)
        with archive.reader() as db:
            recording = db.execute('SELECT recording,ts FROM report_cdr WHERE pbx=? AND source_key=?', (pbx,recording_id)).fetchone()
        if not recording or not recording['recording']:
            abort(404)
        return serve_recording(recording,recording_id,download)

    @app.get('/api/history/outbound-pauses/summary')
    @login_required
    @safe
    def history_outbound_summary():
        scope, start, end = context()
        result = outbound.summary(archive, scope, start, end,
                                  direction=request.args.get('pause_direction', 'outbound'))
        for row in result.get('queue_reasons', []):
            row['reason_label'] = reason_label(row['queue'], row['reason'])
        return jsonify(result)

    @app.get('/api/history/agents')
    @login_required
    @safe
    def history_agents():
        scope, start, end = context()
        return jsonify(queries.agents(archive, scope, start, end))

    @app.get('/api/history/agent-metrics')
    @login_required
    @safe
    def history_agent_metrics():
        scope,start,end=context()
        return jsonify(agent_metrics.report(archive,scope,start,end))

    @app.get('/api/history/activity')
    @login_required
    @safe
    def history_activity():
        scope,start,end=context()
        result=activity_queries.summary(archive,scope,start,end)
        for row in result['rows']:row['reason_label']=reason_label(row['queue'],row['reason'])
        return jsonify(result)

    @app.get('/api/history/activity/intervals')
    @login_required
    @safe
    def history_activity_intervals():
        scope,start,end=context()
        before=(request.args['before_time'],request.args['before_id']) if 'before_time' in request.args and 'before_id' in request.args else None
        result=activity_queries.intervals(archive,scope,start,end,before=before)
        for row in result['rows']:row['reason_label']=reason_label(row['queue'],row['reason'])
        return jsonify(result)

    @app.get('/api/history/outbound-pauses')
    @login_required
    @safe
    def history_outbound_pauses():
        scope,start,end=context()
        before=(request.args['before_time'],request.args['before_id']) if 'before_time' in request.args and 'before_id' in request.args else None
        result=outbound.page(archive,scope,start,end,before=before,direction=request.args.get('pause_direction','outbound'))
        for row in result['rows']:
            memberships=row['memberships']
            queue=next((item['queue'] for item in memberships if can_queue(item['queue'],'caller_details')),memberships[0]['queue'])
            row['destination']=protect_number(dict(queue=queue,caller=row['destination']))['caller']
            for item in memberships:item['reason_label']=reason_label(item['queue'],item['reason'])
            for key,action in (('can_play','recording_play'),('can_download','recording_download')):
                row[key]=bool(row['has_recording'] and role() in ('admin','supervisor') and
                    recording_permitted(archive,row['id'],action,can_queue,
                                        fallback_queues=[item['queue'] for item in memberships]))
            row['can_audit'] = 'audit' in sections() and (row['can_play'] or row['can_download'])
        return jsonify(result)

    @app.get('/api/history/outbound-pauses/<recording_id>/recording')
    @login_required
    @safe
    def history_outbound_recording(recording_id):
        scope,start,end=context()
        result=outbound.page(archive,scope,start,end,ident=recording_id,direction=request.args.get('pause_direction','outbound'))
        if not result['rows']:abort(404)
        download=request.args.get('download')=='1'
        capability='recording_download' if download else 'recording_play'
        if role() not in ('admin','supervisor') or not any(can_queue(item['queue'],capability) for item in result['rows'][0]['memberships']):abort(403)
        with archive.reader() as db:
            row=db.execute('SELECT recording,ts FROM report_cdr WHERE pbx=? AND source_key=?',(pbx,recording_id)).fetchone()
        if not row or not row['recording']:abort(404)
        if not recording_permitted(archive,recording_id,capability,can_queue,
                                   fallback_queues=[item['queue'] for item in result['rows'][0]['memberships']]):abort(403)
        return serve_recording(row,recording_id,download)

    def authorized_detail(visit_id,*,by_identity=False,query_archive=None):
        detail_archive=query_archive or archive
        if by_identity:
            if 'reports' not in sections():abort(403)
            if not archive.path.is_file():abort(503,description='report_archive_not_initialized')
            # A job is already tied to an opaque visit. UI date/queue filters
            # are not authority for that identity; current grants still are.
            with detail_archive.reader() as db:
                visit=db.execute('SELECT queue,entered FROM report_visits WHERE pbx=? AND id=?',(pbx,visit_id)).fetchone()
            if visit is None or not can_queue(visit['queue'],'view'):abort(404)
            own=role()=='agent'
            scope=queries.Scope((visit['queue'],),tuple(own_interfaces()),own,own_since() if own else 0)
            start=float(visit['entered']);end=start+1
        else:scope, start, end = context()
        result = queries.detail(detail_archive, scope, start, end, visit_id)
        if result is None:
            abort(404)
        return result

    def quality_context():
        scope,start,end=context()
        if role() not in ('admin','supervisor') or 'audit' not in sections():abort(403)
        if not quality_ready:raise QualityUnavailable('quality_storage_unavailable')
        return scope,start,end

    def ai_authorized(visit_id,recording_id,*,by_identity=False,deadline=None):
        detail_archive=archive
        if deadline is not None:
            from sanequeue.reporting.transcript_search import DeadlineArchive
            detail_archive=DeadlineArchive(archive,deadline)
            g.report_recording_deadline=min(g.get('report_recording_deadline',deadline),deadline)
        result=authorized_detail(visit_id,by_identity=by_identity,query_archive=detail_archive);queue=result['visit']['queue']
        if not ai_ready:raise AIUnavailable('ai_storage_unavailable')
        if role() not in ('admin','supervisor') or 'audit' not in sections():abort(403)
        if not can_queue(queue,'caller_details') or not can_queue(queue,'recording_play'):abort(403)
        if recording_id not in {item['id'] for item in result['recordings']}:abort(404)
        if not recording_permitted(archive,recording_id,'recording_play',can_queue):abort(403)
        proof=g.get('report_recording_proofs',{}).get((recording_id,()))
        if not proof or not all(can_queue(item,'caller_details') for item in proof):abort(403)
        return queue,tuple(sorted(proof))

    @app.route('/api/history/visits/<visit_id>/recordings/<recording_id>/ai',methods=['GET','POST'])
    @login_required
    @safe
    def history_ai_recording(visit_id,recording_id):
        queue,proof=ai_authorized(visit_id,recording_id)
        enabled=os.getenv('SANEQUEUE_REPORT_AI_ENABLED')=='1'
        if request.method=='GET':
            rows=[job for job in ai_store.list(current_user.get_id()) if
                  job['spec']['visit_id']==visit_id and job['spec']['recording_id']==recording_id and
                  all(can_queue(item,cap) for item in job['spec'].get('queues',[job['spec']['queue']])
                      for cap in ('view','recording_play','caller_details'))]
            return jsonify(enabled=enabled,jobs=rows)
        export_csrf()
        if not enabled:raise AIUnavailable('ai_disabled')
        body=request.get_json(silent=True)
        if not isinstance(body,dict) or body.get('language','fa')!='fa':raise ValueError('local_ai_persian_only')
        job=ai_store.create(current_user.get_id(),visit_id,recording_id,queue,'fa',body.get('request_key'),queues=proof)
        return jsonify(job=job),202

    @app.get('/api/history/transcripts/search')
    @login_required
    @safe
    def history_transcript_search():
        if 'reports' not in sections() or 'audit' not in sections() or role() not in ('admin','supervisor'):
            abort(403)
        if not ai_ready:raise AIUnavailable('ai_storage_unavailable')
        from werkzeug.exceptions import Forbidden, NotFound
        rows=[];search_deadline=time.monotonic()+2
        for candidate in ai_store.search_text(current_user.get_id(),request.args.get('q','')):
            if time.monotonic()>=search_deadline:break
            job=candidate['job'];spec=job['spec']
            try:
                ai_authorized(spec['visit_id'],spec['recording_id'],by_identity=True,deadline=search_deadline)
                if not all(can_queue(queue,capability) for queue in spec.get('queues',[spec['queue']])
                           for capability in ('view','recording_play','caller_details')):continue
            except (Forbidden,NotFound):continue
            rows.append(dict(id=job['id'],visit_id=spec['visit_id'],queue=spec['queue'],
                             created=job['created'],excerpt=candidate['excerpt']))
            if len(rows)>=20:break
        # No hidden-candidate totals or pagination counters are disclosed.
        return jsonify(rows=rows,bounded=True,limit=20,policy='owner_and_current_audio_scope')

    @app.route('/api/history/ai-jobs/<ident>',methods=['GET','POST'])
    @login_required
    @safe
    def history_ai_job(ident):
        if not ai_ready:raise AIUnavailable('ai_storage_unavailable')
        job=ai_store.get(ident,current_user.get_id())
        if job is None:abort(404)
        if job['spec']['pbx']!=pbx:abort(404)
        ai_authorized(job['spec']['visit_id'],job['spec']['recording_id'],by_identity=True)
        if not all(can_queue(queue,capability) for queue in job['spec'].get('queues',[job['spec']['queue']])
                   for capability in ('view','recording_play','caller_details')):abort(403)
        if request.method=='POST':
            export_csrf()
            return jsonify(cancelled=ai_store.cancel(ident,current_user.get_id()))
        return jsonify(job=job)

    @app.route('/api/history/quality/forms',methods=['GET','POST'])
    @login_required
    @safe
    def history_quality_forms():
        quality_context()
        if request.method=='GET':return jsonify(forms=quality_store.forms(),can_edit=role()=='admin')
        if role()!='admin':abort(403)
        export_csrf();body=request.get_json(silent=True)
        if not isinstance(body,dict):raise ValueError('invalid_quality_body')
        if body.get('id'):
            form=quality_store.revise_form(body['id'],body.get('criteria'),current_user.get_id(),name=body.get('name'))
        else:form=quality_store.save_form(body.get('name'),body.get('criteria'),current_user.get_id())
        if form is None:abort(404)
        return jsonify(form=form),201

    @app.get('/api/history/quality/summary')
    @login_required
    @safe
    def history_quality_summary():
        scope,start,end=quality_context()
        return jsonify(quality_store.aggregate(scope.queues,start,end,reviewers=True))

    @app.route('/api/history/visits/<visit_id>/reviews',methods=['GET','POST'])
    @login_required
    @safe
    def history_quality_reviews(visit_id):
        quality_context();detail=authorized_detail(visit_id);queue=detail['visit']['queue']
        if request.method=='GET':
            page=quality_store.page([queue],visit_id,before=request.args.get('before'))
            for review in page['rows']:
                allowed=can_queue(queue,'caller_details')
                if review['recording_id']:
                    allowed=allowed and recording_permitted(archive,review['recording_id'],'recording_play',can_queue)
                    proof=g.get('report_recording_proofs',{}).get((review['recording_id'],())) or ()
                    frozen=review.get('recording_queues',[])
                    allowed=allowed and bool(frozen) and bool(proof) and set(proof).issubset(frozen) and all(
                        can_queue(item,cap) for item in set(frozen)|set(proof) for cap in ('view','caller_details','recording_play'))
                if not allowed:
                    review.update(comment='',notes=[],recording_id=None,recording_queues=[],content_redacted=True)
                else:review['content_redacted']=False
            return jsonify(page)
        export_csrf();body=request.get_json(silent=True)
        if not isinstance(body,dict):raise ValueError('invalid_quality_body')
        if not can_queue(queue,'caller_details'):abort(403)
        recording_id=body.get('recording_id');notes=body.get('notes') or []
        if not isinstance(notes,list) or len(notes)>100:raise ValueError('quality_note_limit')
        recording_queues=[]
        if recording_id or notes:
            if not recording_id or recording_id not in {item['id'] for item in detail['recordings']}:abort(403)
            if not can_queue(queue,'recording_play') or not recording_permitted(archive,recording_id,'recording_play',can_queue):abort(403)
            proof=g.get('report_recording_proofs',{}).get((recording_id,()))
            if not proof or not all(can_queue(item,'caller_details') for item in proof):abort(403)
            recording_queues=sorted(proof)
            with archive.reader() as db:
                recording=db.execute('SELECT recording,ts FROM report_cdr WHERE pbx=? AND source_key=?',(pbx,recording_id)).fetchone()
            if not recording:abort(404)
            try:fd,_=open_recording(recording_root,recording['recording'])
            except FileNotFoundError:
                if '/' in recording['recording']:abort(404)
                folder=datetime.fromtimestamp(recording['ts'],ZoneInfo('Asia/Tehran')).strftime('%Y/%m/%d/')
                fd,_=open_recording(recording_root,folder+recording['recording'])
            with os.fdopen(fd,'rb') as stream:
                if notes:
                    try:duration=duration_seconds(stream)
                    except AudioDurationUnavailable as error:abort(415,description=str(error))
            for note in notes:
                if not isinstance(note,dict) or isinstance(note.get('offset_seconds'),bool):raise ValueError('invalid_quality_note')
                offset=float(note.get('offset_seconds',-1))
                if not 0<=offset<=min(duration,14400):raise ValueError('quality_note_outside_recording')
        review=quality_store.create_review(visit_id,queue,current_user.get_id(),body.get('form_id'),
            body.get('form_version'),body.get('scores'),body.get('comment',''),body.get('request_key'),
            recording_id=recording_id,notes=notes,recording_queues=recording_queues)
        return jsonify(review=review),201

    def require_audit():
        if role() not in ('admin', 'supervisor') or 'audit' not in sections():
            abort(403)
        if not audit_ready:
            raise AuditUnavailable('recording_audit_unavailable')

    @app.get('/api/history/visits/<visit_id>/recordings/<recording_id>/access')
    @login_required
    @safe
    def history_recording_access(visit_id, recording_id):
        require_audit()
        result = authorized_detail(visit_id)
        if recording_id not in {row['id'] for row in result['recordings']}:
            abort(404)
        if not any(recording_permitted(archive, recording_id, cap, can_queue)
                   for cap in ('recording_play', 'recording_download')):
            abort(403)
        return jsonify(audit_store.page(recording_id, before=request.args.get('before')))

    @app.get('/api/history/outbound-pauses/<recording_id>/access')
    @login_required
    @safe
    def history_outbound_access(recording_id):
        require_audit()
        scope, start, end = context()
        result = outbound.page(archive, scope, start, end, ident=recording_id,
                               direction=request.args.get('pause_direction', 'outbound'))
        if not result['rows']:
            abort(404)
        queues = [item['queue'] for item in result['rows'][0]['memberships']]
        if not any(recording_permitted(archive, recording_id, cap, can_queue, fallback_queues=queues)
                   for cap in ('recording_play', 'recording_download')):
            abort(403)
        return jsonify(audit_store.page(recording_id, before=request.args.get('before')))

    @app.get('/api/history/visits/<visit_id>/journey')
    @login_required
    @safe
    def history_journey(visit_id):
        scope,start,end=context()
        data=journey.explain(archive,scope,start,end,visit_id)
        if data is None:abort(404)
        # Expanded legs must never gain stronger number visibility than any
        # queue authorized for this request. Graph evidence grants no audio.
        full=bool(scope.queues) and all(can_queue(queue,'caller_details') for queue in scope.queues)
        secret=hashlib.sha256(('sanequeue.reporting.numbers:'+str(app.secret_key)).encode()).digest()
        data['numbers']={key:display_number(value,mode='full' if full else 'masked',secret=secret,
                          tenant='default',pbx=pbx,version='1') for key,value in data['numbers'].items()}
        return jsonify(data)

    @app.get('/api/history/visits/<visit_id>')
    @login_required
    @safe
    def history_detail(visit_id):
        result = authorized_detail(visit_id)
        result['visit'] = protect_number(result['visit'])
        queue = result['visit']['queue']
        result['can_play'] = role() in ('admin','supervisor') and can_queue(queue, 'recording_play')
        result['can_download'] = role() in ('admin','supervisor') and can_queue(queue, 'recording_download')
        result['can_review'] = quality_ready and role() in ('admin','supervisor') and 'audit' in sections() and can_queue(queue,'caller_details')
        if not result['can_play'] and not result['can_download']:
            result['recordings'] = []
        else:
            permitted_refs=[]
            for recording in result['recordings']:
                recording.pop('uid',None)
                recording.pop('linkedid',None)
                recording['can_play']=result['can_play'] and recording_permitted(archive,recording['id'],'recording_play',can_queue)
                recording['can_download']=result['can_download'] and recording_permitted(archive,recording['id'],'recording_download',can_queue)
                recording['can_audit']='audit' in sections() and (recording['can_play'] or recording['can_download'])
                recording['can_ai']=ai_ready and recording['can_play'] and 'audit' in sections() and can_queue(queue,'caller_details')
                if recording['can_play'] or recording['can_download']:permitted_refs.append(recording)
            result['recordings']=permitted_refs
        return jsonify(result)

    @app.get('/api/history/visits/<visit_id>/recordings/<recording_id>')
    @login_required
    @safe
    def history_recording(visit_id, recording_id):
        result = authorized_detail(visit_id)
        # Independent audio ceiling; queue view alone never grants sound access.
        download = request.args.get('download') == '1'
        capability = 'recording_download' if download else 'recording_play'
        if role() not in ('admin', 'supervisor') or not can_queue(result['visit']['queue'], capability):
            abort(403)
        if recording_id not in {r['id'] for r in result['recordings']}:
            abort(404)
        if not recording_permitted(archive,recording_id,capability,can_queue):
            abort(403)
        with archive.reader() as db:
            row = db.execute('SELECT recording,ts FROM report_cdr WHERE pbx=? AND source_key=?', (pbx, recording_id)).fetchone()
        if row is None:
            abort(404)
        return serve_recording(row,recording_id,download)

    def serve_recording(row,recording_id,download):
        reference = row['recording']
        suffix = Path(reference).suffix.lower()
        if not download and suffix not in ('.wav', '.mp3', '.ogg'):
            abort(415, description='recording_codec_requires_conversion')
        try:
            fd, size = open_recording(recording_root, reference)
        except FileNotFoundError:
            # Issabel commonly stores a basename in CDR, in a dated directory.
            if '/' in reference:
                abort(404)
            date = datetime.fromtimestamp(row['ts'], ZoneInfo('Asia/Tehran')).strftime('%Y/%m/%d/')
            try:
                fd, size = open_recording(recording_root, date + reference)
            except FileNotFoundError:
                abort(404)
        try:
            start, end, partial = byte_range(request.headers.get('Range'), size)
        except ValueError:
            os.close(fd)
            return Response(status=416, headers={'Content-Range': f'bytes */{size}'})
        if request.method != 'HEAD':
            try:
                if not audit_ready:
                    raise AuditUnavailable('recording_audit_unavailable')
                audit_store.append(str(current_user.get_id()), recording_id,
                                   'download_request' if download else 'play_request')
            except AuditUnavailable:
                os.close(fd)
                raise
        stream = os.fdopen(fd, 'rb')
        def chunks():
            try:
                stream.seek(start)
                left = end - start + 1 if size else 0
                while left:
                    chunk = stream.read(min(65536, left))
                    if not chunk:
                        break
                    left -= len(chunk)
                    yield chunk
            finally:
                stream.close()
        response = Response(chunks(), status=206 if partial else 200,
                            mimetype={'.wav': 'audio/wav', '.mp3': 'audio/mpeg', '.ogg': 'audio/ogg'}.get(suffix, 'application/octet-stream'))
        response.headers['Content-Length'] = str(end - start + 1 if size else 0)
        response.headers['Accept-Ranges'] = 'bytes'
        response.headers['Content-Disposition'] = ('attachment' if download else 'inline') + f'; filename="recording-{recording_id[:12]}{suffix if suffix in (".wav", ".mp3", ".ogg", ".gsm") else ".bin"}"'
        if partial:
            response.headers['Content-Range'] = f'bytes {start}-{end}/{size}'
        response.call_on_close(stream.close)
        app.logger.info('report recording user=%r id=%r action=%s', current_user.get_id(),
                        recording_id, 'download' if download else 'play')
        return response

    @app.get('/api/history/export.csv')
    @app.get('/api/history/export.xlsx')
    @login_required
    @safe
    def history_export():
        scope, start, end = context()
        if role() not in ('admin', 'supervisor') or not all(can_queue(q, 'report_export') for q in scope.queues):
            abort(403)
        # Synchronous exports are deliberately one bounded page. Large exports
        # belong to a resource-limited background job, not a long read cursor.
        result = queries.visits(archive, scope, start, end, limit=200, queue=request.args.get('queue'), outcome=request.args.get('outcome'))
        if result['next'] is not None:
            return jsonify(error='export_too_large_narrow_filters', maximum_rows=200), 422
        language = request.args.get('lang', 'en')
        if language not in ('fa', 'en'):
            raise ValueError('invalid_export_language')
        rows = [protect_number(row) for row in result['rows']]
        if request.path.endswith('.xlsx'):
            period = datetime.fromtimestamp(start, ZoneInfo('Asia/Tehran')).date().isoformat()+' .. '+datetime.fromtimestamp(end-1, ZoneInfo('Asia/Tehran')).date().isoformat()
            content = exports.xlsx_bytes(rows, language, period=period)
            app.logger.info('report export user=%r rows=%d format=xlsx', current_user.get_id(), len(rows))
            return Response(content, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                            headers={'Content-Disposition': 'attachment; filename="sanequeue-visits.xlsx"'})
        if request.args.get('layout') != 'raw':
            app.logger.info('report export user=%r rows=%d format=csv', current_user.get_id(), len(rows))
            return Response(exports.csv_bytes(rows, language), mimetype='text/csv; charset=utf-8',
                            headers={'Content-Disposition': 'attachment; filename="sanequeue-visits.csv"'})
        output = io.StringIO(newline='')
        fields = ('id', 'queue', 'entered', 'answered', 'ended', 'caller', 'agent', 'outcome', 'wait_seconds', 'talk_seconds', 'segment_ended_by', 'coverage')
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        for raw in result['rows']:
            row = protect_number(raw)
            # Neutralize spreadsheet formulas, including user-controlled names.
            writer.writerow({k: "'" + v if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else v for k, v in row.items()})
        app.logger.info('report export user=%r rows=%d', current_user.get_id(), len(result['rows']))
        return Response('\ufeff' + output.getvalue(), mimetype='text/csv; charset=utf-8',
                        headers={'Content-Disposition': 'attachment; filename="sanequeue-visits.csv"'})

    from sanequeue.api.report_builder import install as install_report_builder
    install_report_builder(app,archive,context=context,role=role,sections=sections,can_queue=can_queue,pbx=pbx)
