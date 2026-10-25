"""Authenticated historical reports backed only by the local reporting archive."""
import csv
from datetime import datetime, timedelta
import hashlib
import io
import os
from pathlib import Path
import sqlite3
import time
from zoneinfo import ZoneInfo

from flask import abort, jsonify, request, Response, g
from flask_login import login_required, current_user
from werkzeug.exceptions import HTTPException

from sanequeue.reporting import queries
from sanequeue.reporting import exports
from sanequeue.reporting import activity_queries
from sanequeue.reporting import outbound
from sanequeue.reporting.recording_scope import ownership as recording_ownership
from sanequeue.reporting.audio import byte_range, open_recording
from sanequeue.reporting.privacy import display_number
from sanequeue.reporting.store import Archive, QueryDeadline


def install(app, path, *, role, sections, can_queue, own_interfaces=lambda: (), own_since=lambda: 0,
            recording_root='/var/spool/asterisk/monitor', pbx='primary',reason_label=lambda queue,reason:reason):
    archive = Archive(path, pbx=pbx)
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

    def context():
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
            except (sqlite3.Error, OSError):
                response = app.make_response((jsonify(error='report_archive_unavailable'), 503))
            except HTTPException as error:
                message = {403: 'report_access_denied', 404: 'report_not_found',
                           415: 'recording_codec_requires_conversion',
                           503: 'report_archive_not_initialized'}.get(error.code, 'report_request_failed')
                response = app.make_response((jsonify(error=message), error.code))
            response.headers['Cache-Control'] = 'private, no-store'
            response.headers['X-Content-Type-Options'] = 'nosniff'
            return response
        return wrapped

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

    @app.get('/api/history/agents')
    @login_required
    @safe
    def history_agents():
        scope, start, end = context()
        return jsonify(queries.agents(archive, scope, start, end))

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

    def authorized_detail(visit_id):
        scope, start, end = context()
        result = queries.detail(archive, scope, start, end, visit_id)
        if result is None:
            abort(404)
        return result

    @app.get('/api/history/visits/<visit_id>')
    @login_required
    @safe
    def history_detail(visit_id):
        result = authorized_detail(visit_id)
        result['visit'] = protect_number(result['visit'])
        queue = result['visit']['queue']
        result['can_play'] = role() in ('admin','supervisor') and can_queue(queue, 'recording_play')
        result['can_download'] = role() in ('admin','supervisor') and can_queue(queue, 'recording_download')
        if not result['can_play'] and not result['can_download']:
            result['recordings'] = []
        else:
            permitted_refs=[]
            for recording in result['recordings']:
                recording.pop('uid',None)
                recording.pop('linkedid',None)
                recording['can_play']=result['can_play'] and recording_permitted(archive,recording['id'],'recording_play',can_queue)
                recording['can_download']=result['can_download'] and recording_permitted(archive,recording['id'],'recording_download',can_queue)
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
