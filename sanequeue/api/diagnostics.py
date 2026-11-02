"""Queue-visit diagnostics v1; never fetch live PBX data or infer user intent."""
import hashlib
import hmac
import json
import math
import sqlite3
import time
from functools import wraps
from flask import abort, jsonify, request, session
from flask_login import current_user, login_required
from werkzeug.exceptions import HTTPException
from sanequeue.diagnostics.store import Store, Scope, Conflict, Unavailable
from sanequeue.diagnostics.health import source_health
from sanequeue.diagnostics.rules import short_after_answer
from sanequeue.reporting import queries
from sanequeue.reporting.store import Archive, QueryDeadline


def install(app, archive, *, context, role, sections, can_queue, pbx='primary'):
    store = Store(archive.path.parent / 'diagnostics.sqlite3', pbx=pbx)
    try:
        store.initialize(); ready = True
    except (ValueError, OSError, sqlite3.Error, Unavailable):
        ready = False

    @app.after_request
    def diagnostics_private_response(response):
        if request.endpoint and request.endpoint.startswith('diagnostics_'):
            response.headers['Cache-Control'] = 'private, no-store'
            response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    def safe(function):
        @wraps(function)
        def call(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except Conflict:
                return jsonify(error='diagnostics_conflict'), 409
            except PermissionError:
                return jsonify(error='diagnostics_access_denied'), 403
            except QueryDeadline:
                return jsonify(error='diagnostics_query_deadline'), 422
            except (Unavailable, OSError, sqlite3.Error):
                return jsonify(error='diagnostics_storage_unavailable'), 503
            except (ValueError, TypeError, OverflowError, RecursionError):
                return jsonify(error='invalid_diagnostics_request'), 400
            except HTTPException as error:
                return jsonify(error={403:'diagnostics_access_denied',404:'diagnostics_not_found',
                                      413:'diagnostics_request_too_large',415:'diagnostics_json_required',
                                      503:'diagnostics_source_unavailable'}.get(error.code,'diagnostics_request_failed')), error.code
        return call

    def actor():
        if role() not in ('admin', 'supervisor', 'agent') or 'reports' not in sections():
            abort(403)
        if not ready:
            abort(503)
        if request.method == 'POST':
            expected, actual = session.get('csrf_token'), request.headers.get('X-CSRF-Token')
            if not isinstance(expected,str) or not expected or not isinstance(actual,str) or not hmac.compare_digest(expected,actual):
                abort(403)
        # An opaque stable actor, not a raw username. Rotation conservatively
        # changes own-only visibility until an explicit account migration.
        key = hashlib.sha256(('sanequeue.diagnostics.actor:'+str(app.secret_key)).encode()).digest()
        return hmac.new(key, str(current_user.get_id()).encode(), hashlib.sha256).hexdigest()

    def scopes():
        ident = actor(); report_scope, start, end = context()
        queues = tuple(q for q in report_scope.queues if can_queue(q,'view'))
        return ident, report_scope, Scope(queues, actor=ident, own_only=role()=='agent'), start, end

    def body(allowed):
        if not request.is_json:
            abort(415)
        raw = request.stream.read(8193)
        if len(raw) > 8192:
            abort(413)
        value = json.loads(raw)
        if not isinstance(value,dict) or set(value)-set(allowed):
            raise ValueError('invalid_diagnostics_request')
        return value

    def authorized_visits(ids, report_scope):
        ids = tuple(dict.fromkeys(ident for ident in ids if isinstance(ident,str) and len(ident)==64 and all(c in '0123456789abcdef' for c in ident)))
        if not ids or not report_scope.queues:
            return {}
        if len(ids)>100:
            raise ValueError('diagnostics_page_limit')
        bounded = Archive(archive.path, pbx=archive.pbx, read_seconds=min(1, archive.read_seconds))
        clause, args = queries._scope(archive.pbx, report_scope)
        with bounded.reader() as db:
            projection = db.execute('SELECT after_id FROM report_projection WHERE pbx=?',(archive.pbx,)).fetchone()
            head = db.execute('SELECT MAX(id) FROM events WHERE pbx=?',(archive.pbx,)).fetchone()[0] or 0
            if projection is None or projection[0] < head:
                abort(503)
            # Recheck present ownership and all queue visits of this UID. A
            # previously stored queue set never authorizes a newly found leg.
            sql = '''SELECT id,queue,entered,answered,ended,talk_seconds,outcome,coverage FROM report_visits WHERE '''+clause+'''
                AND entered>=? AND id IN ('''+','.join('?' for _ in ids)+''')
                AND NOT EXISTS (SELECT 1 FROM report_visits foreign_visit
                  WHERE foreign_visit.pbx=report_visits.pbx AND foreign_visit.callid=report_visits.callid
                    AND foreign_visit.queue NOT IN ('''+','.join('?' for _ in report_scope.queues)+'))'
            rows = db.execute(sql, (*args, report_scope.not_before, *ids, *report_scope.queues)).fetchall()
        return {row['id']:dict(row) for row in rows}

    def protect(row, ident, visit):
        row = dict(row)
        full = all(can_queue(q,'caller_details') for q in row['queues'])
        own = row['reporter']==ident
        if not full and not own:
            row['description'] = None
        if 'actions' in row:
            row['actions'] = [{**action, 'note':action['note'] if full or action['actor']==ident else None}
                              for action in row['actions']]
        row['text_policy'] = 'full' if full else 'own_text_only'
        row['root_cause'] = 'unavailable'; row['human_intent'] = 'unavailable'
        if row['kind']=='short_after_answer' and row['evidence_count']:
            row['classification_scope']='historical_queue_segment'
            policy=row.get('rule_parameters')
            row['current_rule_match']=(short_after_answer(visit,threshold_seconds=policy['threshold_seconds']) is not None
                                       if isinstance(policy,dict) and 'threshold_seconds' in policy else None)
            row['current_state_verified']=False
            # A human workflow resolution does not turn an automatic duration
            # flag into a verified cause or current source reconciliation.
            if row['current_rule_match'] is not True:
                row['classification_state']='historical_candidate_requires_review'
        return row

    def final_guard(ident, row):
        fresh_actor, fresh_report, fresh_scope, _, _=scopes()
        current=authorized_visits((row['visit_id'],),fresh_report)
        if (fresh_actor!=ident or not current or not set(row['queues'])<=set(fresh_scope.queues)
                or fresh_scope.own_only and row['reporter']!=ident):
            abort(403)
        return current[row['visit_id']]

    @app.get('/api/diagnostics/source-health')
    @login_required
    @safe
    def diagnostics_source_health():
        actor()
        if role()!='admin' or not all(can_queue(q,'view') for q in queries.queues(archive)):
            abort(403)
        result=source_health(archive, now=time.time())
        actor()
        if role()!='admin' or not all(can_queue(q,'view') for q in queries.queues(archive)):
            abort(403)
        return jsonify(result)

    @app.route('/api/diagnostics/incidents', methods=['GET','POST'])
    @login_required
    @safe
    def diagnostics_incidents():
        ident, report_scope, scope, start, end = scopes()
        if request.method=='POST':
            value=body(('kind','visit_id','occurred_at','description'))
            if value.get('kind') not in ('one_way_audio','unexpected_disconnect','media_quality'):
                raise ValueError('invalid_manual_incident_kind')
            visit=authorized_visits((value.get('visit_id'),), report_scope).get(value.get('visit_id'))
            if visit is None:
                abort(404)
            now=time.time(); occurred=value.get('occurred_at',visit['ended'] or visit['answered'] or visit['entered'])
            if type(occurred) not in (int,float) or not math.isfinite(occurred) or not visit['entered']<=occurred<=min(visit['ended'] or now,now)+5:
                raise ValueError('invalid_incident_time')
            row=store.create_manual(value['kind'],(visit['queue'],),ident,occurred,
                                    description=value.get('description',''), visit_id=visit['id'])
            fresh_ident, fresh_report, fresh_scope, _, _=scopes()
            if fresh_ident!=ident or not authorized_visits((visit['id'],),fresh_report):
                abort(403)
            result=store.get(row['id'],fresh_scope)
            if result is None:
                abort(403)
            current=final_guard(ident,result)
            return jsonify(incident=protect(result,ident,current)),201
        raw_before=request.args.get('before','')
        if len(raw_before)>200:
            raise ValueError('invalid_diagnostics_cursor')
        before=json.loads(raw_before) if raw_before else None
        limit=int(request.args.get('limit',50))
        if not 1<=limit<=100:
            raise ValueError('diagnostics_page_limit')
        candidates=[]; cursor=before; scanned=0; more=False
        # Skip changed-ownership rows using a bounded internal cursor. Hidden
        # IDs stay server-side. A scan ceiling is explicit, never "end of data".
        while scanned<200 and len(candidates)<limit:
            page=store.page(scope,before=cursor,limit=min(50,200-scanned),
                            kind=request.args.get('kind'),status=request.args.get('status'),start=start,end=end)
            fresh_ident, fresh_report, fresh_scope, _, _=scopes()
            if fresh_ident!=ident:
                abort(403)
            visible=authorized_visits((row['visit_id'] for row in page['rows']),fresh_report)
            allowed=set(fresh_scope.queues)
            valid=[row for row in page['rows'] if row['visit_id'] in visible and set(row['queues'])<=allowed
                   and (not fresh_scope.own_only or row['reporter']==ident)]
            space=limit-len(candidates);candidates.extend(valid[:space])
            scanned+=len(page['rows']);cursor=page['next'];more=cursor is not None or len(valid)>space
            if not more or not page['rows']:
                break
        # One final authorization pass follows the last private-store read.
        fresh_ident,fresh_report,fresh_scope,_,_=scopes()
        if fresh_ident!=ident:
            abort(403)
        visible=authorized_visits((row['visit_id'] for row in candidates),fresh_report)
        rows=[protect(row,ident,visible[row['visit_id']]) for row in candidates if row['visit_id'] in visible
              and set(row['queues'])<=set(fresh_scope.queues) and (not fresh_scope.own_only or row['reporter']==ident)]
        authorization_changed=len(rows)!=len(candidates)
        # Never publish the ID/timestamp of a filtered incident as a cursor.
        next_cursor=[rows[-1]['created'],rows[-1]['id']] if rows and more and not authorization_changed else None
        return jsonify(rows=rows,next=next_cursor,scan_limited=(more and scanned>=200) or authorization_changed,
                       refresh_required=authorization_changed,
                       contract=dict(unit='incident',time_filter='reported_at',
                       complete_conversation=False,root_cause_inference=False,standalone_internal_calls=False))

    @app.route('/api/diagnostics/incidents/<ident>', methods=['GET','POST'])
    @login_required
    @safe
    def diagnostics_incident(ident):
        actor_id, report_scope, scope, _, _=scopes()
        row=store.get(ident,scope)
        if row is None or not authorized_visits((row['visit_id'],),report_scope):
            abort(404)
        if request.method=='POST':
            value=body(('action','note','expected_version'))
            if role()=='agent' and value.get('action')!='comment':
                abort(403)
            if value.get('action')!='comment' and (type(value.get('expected_version')) is not int or value['expected_version']<1):
                raise ValueError('diagnostic_version_required')
            row=store.add_action(ident,scope,actor_id,value.get('action'),note=value.get('note',''),
                                 expected_version=value.get('expected_version'))
        fresh_actor, fresh_report, fresh_scope, _, _=scopes()
        current=authorized_visits((row['visit_id'],),fresh_report)
        if fresh_actor!=actor_id or not current:
            abort(403)
        row=store.get(ident,fresh_scope)
        if row is None:
            abort(403)
        visit=final_guard(actor_id,row)
        return jsonify(incident=protect(row,actor_id,visit))
