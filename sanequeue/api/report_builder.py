"""Private report-builder HTTP adapter; archive queries remain read-only."""
import hashlib
import hmac
import json
import sqlite3
import threading
from flask import abort,jsonify,request,session,Response
from flask_login import current_user,login_required
from sanequeue.reporting.report_builder import Templates,BuilderConflict,BuilderUnavailable,definition,preview,export_csv,COLUMNS,GROUPS
from sanequeue.reporting.store import QueryDeadline


def install(app,archive,*,context,role,sections,can_queue,pbx='primary'):
    store=Templates(archive.path.parent/'report-builder.sqlite3',pbx=pbx)
    export_slots=threading.BoundedSemaphore(1)
    try:store.initialize();ready=True
    except (OSError,sqlite3.Error,ValueError,BuilderUnavailable):ready=False
    @app.after_request
    def builder_private_response(response):
        # Also covers login_required redirects/401 and Flask HTTP errors,
        # which occur outside the safe route wrapper.
        if request.endpoint and request.endpoint.startswith('builder_'):
            response.headers['Cache-Control']='private, no-store'
            response.headers['X-Content-Type-Options']='nosniff'
        return response
    def actor():
        if role() not in ('admin','supervisor','agent') or 'reports' not in sections():abort(403)
        if not ready:abort(503)
        if request.method=='POST':
            expected=session.get('csrf_token');actual=request.headers.get('X-CSRF-Token')
            if not isinstance(expected,str) or not expected or not isinstance(actual,str) or not hmac.compare_digest(expected,actual):abort(403)
            if request.content_length is not None and request.content_length>16384:abort(413)
        return str(current_user.get_id())
    def allowed(spec,scope):
        if not set(spec['queues']).issubset(scope.queues) or not all(can_queue(q,'view') for q in spec['queues']):abort(403)
    def payload():
        if not request.is_json:abort(415)
        raw=request.stream.read(16385)
        if len(raw)>16384:abort(413)
        body=json.loads(raw)
        if not isinstance(body,dict):raise ValueError()
        return body
    def safe(function):
        from functools import wraps
        @wraps(function)
        def call(*args,**kwargs):
            try:return function(*args,**kwargs)
            except BuilderConflict as error:return jsonify(error=str(error)),409
            except FileNotFoundError:abort(404)
            except PermissionError:return jsonify(error='builder_scope_revoked'),403
            except (BuilderUnavailable,sqlite3.Error,OSError):return jsonify(error='builder_storage_unavailable'),503
            except QueryDeadline:return jsonify(error='builder_query_deadline'),422
            except ValueError as error:
                code=str(error)
                public={'builder_range_limit','builder_group_limit','builder_field_limit','invalid_builder_threshold','invalid_builder_cursor','invalid_builder_limit','builder_export_row_limit','builder_export_byte_limit'}
                return jsonify(error=code if code in public else 'invalid_builder_request'),400
            except (TypeError,OverflowError):return jsonify(error='invalid_builder_request'),400
        return call
    @app.route('/api/history/builder/templates',methods=['GET','POST'])
    @login_required
    @safe
    def builder_templates():
        owner=actor();scope,_,_=context(restrict_queue=False)
        if request.method=='GET':
            return jsonify(templates=[row for row in store.list(owner) if set(row['definition']['queues']).issubset(scope.queues)],columns=COLUMNS,groups=GROUPS)
        body=payload()
        spec=definition(body.get('definition'));allowed(spec,scope)
        return jsonify(template=store.save(owner,body.get('name'),spec)),201
    @app.route('/api/history/builder/templates/<ident>',methods=['GET','POST'])
    @login_required
    @safe
    def builder_template(ident):
        owner=actor();scope,_,_=context(restrict_queue=False);row=store.get(ident,owner)
        if row is None:abort(404)
        allowed(row['definition'],scope)
        if request.method=='POST':
            body=payload()
            spec=definition(body.get('definition'));allowed(spec,scope)
            row=store.save(owner,body.get('name'),spec,ident=ident,expected_version=body.get('expected_version'))
        return jsonify(template=row)
    @app.post('/api/history/builder/preview')
    @login_required
    @safe
    def builder_preview():
        owner=actor();scope,start,end=context(restrict_queue=False);body=payload()
        if body.get('template_id'):
            saved=store.get(body['template_id'],owner)
            if saved is None:abort(404)
            spec=saved['definition']
        else:spec=definition(body.get('definition'))
        allowed(spec,scope)
        modes={q:'full' if can_queue(q,'caller_details') else 'masked' for q in spec['queues']}
        secret=hashlib.sha256(('sanequeue.reporting.numbers:'+str(app.secret_key)).encode()).digest()
        return jsonify(preview(archive,scope,start,end,spec,number_modes=modes,number_key=secret,before=body.get('before'),limit=body.get('limit',50)))
    @app.post('/api/history/builder/export.csv')
    @login_required
    @safe
    def builder_export():
        owner=actor()
        if role() not in ('admin','supervisor'):abort(403)
        scope,start,end=context(restrict_queue=False);body=payload()
        if body.get('template_id'):
            saved=store.get(body['template_id'],owner)
            if saved is None:abort(404)
            spec=saved['definition']
        else:spec=definition(body.get('definition'))
        allowed(spec,scope)
        if not all(can_queue(q,'report_export') for q in spec['queues']):abort(403)
        modes={q:'full' if can_queue(q,'caller_details') else 'masked' for q in spec['queues']}
        secret=hashlib.sha256(('sanequeue.reporting.numbers:'+str(app.secret_key)).encode()).digest()
        if not export_slots.acquire(blocking=False):return jsonify(error='builder_export_busy'),429
        try:
            content,meta=export_csv(archive,scope,start,end,spec,number_modes=modes,number_key=secret,language=body.get('language','en'))
            # Never publish content under stale role, agent/cutoff or queue grants.
            if actor()!=owner or role() not in ('admin','supervisor'):abort(403)
            current,_,_=context(restrict_queue=False);allowed(spec,current)
            if (current.agents,current.self_only,current.not_before)!=(scope.agents,scope.self_only,scope.not_before):abort(403)
            if not all(can_queue(q,'report_export') and (modes[q]!='full' or can_queue(q,'caller_details')) for q in spec['queues']):abort(403)
            response=Response(content,content_type='text/csv; charset=utf-8')
            response.headers['Content-Disposition']='attachment; filename="sanequeue-custom-'+str(int(start))+'-'+str(int(end))+'.csv"'
            response.headers['X-SaneQueue-Export-Rows']=str(meta['rows'])
            response.headers['X-SaneQueue-Definition-SHA256']=meta['definition_sha256']
            response.headers['X-SaneQueue-Projection']=str(meta['projection']['after_id']) if meta['projection'] else 'unknown'
            response.headers['X-SaneQueue-Period-Start']=str(start);response.headers['X-SaneQueue-Period-End']=str(end)
            response.headers['X-SaneQueue-Unit']=meta['unit']
            app.logger.info('bounded custom report export user=%r rows=%d definition=%s',owner,meta['rows'],meta['definition_sha256'])
            return response
        finally:export_slots.release()
