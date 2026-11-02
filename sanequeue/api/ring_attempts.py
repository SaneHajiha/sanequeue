"""Restricted read-only RINGNOANSWER attempt API; no raw call/channel data."""
import sqlite3
import csv
import io
from functools import wraps
from flask import abort,jsonify,request,Response
from flask_login import login_required,current_user
from werkzeug.exceptions import HTTPException
from sanequeue.reporting.ring_attempts import report
from sanequeue.reporting.store import QueryDeadline


def install(app,archive,context,*,role,sections,can_queue):
    """context() supplies the existing current queue scope and timezone range.

    This first version deliberately rejects agent roles: queue member names
    are not proven historical account assignments. No startup DDL is needed.
    """
    @app.after_request
    def ring_attempts_private_headers(response):
        if request.endpoint and request.endpoint.startswith('ring_attempts_'):
            response.headers['Cache-Control']='private, no-store'
            response.headers['X-Content-Type-Options']='nosniff'
        return response
    def safe(function):
        @wraps(function)
        def call(*args,**kwargs):
            try:return function(*args,**kwargs)
            except QueryDeadline:return jsonify(error='ring_attempt_query_limit'),422
            except (ValueError,TypeError,OverflowError):return jsonify(error='invalid_ring_attempt_request'),400
            except (sqlite3.Error,OSError):return jsonify(error='ring_attempt_archive_unavailable'),503
            except HTTPException as error:return jsonify(error='ring_attempt_access_denied' if error.code==403 else 'ring_attempt_unavailable'),error.code
        return call
    @app.get('/api/history/ring-attempts.csv')
    @app.get('/api/history/ring-attempts')
    @login_required
    @safe
    def ring_attempts_report():
        if role() not in ('admin','supervisor') or 'reports' not in sections():abort(403)
        scope,start,end=context()
        if scope.self_only or not all(can_queue(q,'view') for q in scope.queues):abort(403)
        exporting=request.path.endswith('.csv')
        can_export=bool(scope.queues) and all(can_queue(q,'report_export') for q in scope.queues)
        if exporting and not can_export:abort(403)
        language=request.args.get('lang','en')
        if language not in ('fa','en'):raise ValueError()
        raw_limit=request.args.get('limit','100')
        if not raw_limit.isascii() or not raw_limit.isdecimal() or len(raw_limit)>3:raise ValueError()
        result=report(archive,scope,start,end,before=request.args.get('before'),limit=int(raw_limit))
        if exporting:
            output=io.StringIO(newline='');writer=csv.writer(output)
            def write(values):writer.writerow(["'"+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@','\t','\r','\n')) else v for v in values])
            write(['SaneQueue', 'queue_member_ring_attempt', request.args.get('from'), request.args.get('to'), 'Asia/Tehran'])
            write(['صف','داخلی','پیشنهاد بی‌پاسخ','مدت معلوم؛ تعداد','مدت نامعلوم؛ تعداد','جمع زنگ معلوم؛ ثانیه','میانگین زنگ معلوم؛ ثانیه','انتساب معلوم به مراجعه','انتساب نامعلوم'] if language=='fa' else ['Queue','Endpoint','Unanswered offers','Known duration count','Unknown duration count','Known ring sum; seconds','Known ring average; seconds','Matched visit attempts','Unmatched visit attempts'])
            keys=('queue','agent','attempts','known_duration_attempts','unknown_duration_attempts','known_ring_seconds','average_known_ring_seconds','matched_visit_attempts','unmatched_visit_attempts')
            for row in result['groups']:write([row.get(key) for key in keys])
            content=('\ufeff'+output.getvalue()).encode('utf-8')
            if len(content)>512*1024:raise QueryDeadline('ring_attempt_export_size')
            app.logger.info('ring attempt export user=%r groups=%d',current_user.get_id(),len(result['groups']))
            return Response(content,mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':'attachment; filename="sanequeue-ring-attempts.csv"'})
        result['can_export']=can_export
        return jsonify(result)
