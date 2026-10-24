"""SaneQueue operations UI, scoped reports, and explicit supervisor controls."""
import csv
import hmac
import io
import os
import re
import secrets
import time
import math
import threading
import json
from contextlib import nullcontext
from datetime import datetime, timedelta
from flask import jsonify, request, session, abort, Response, url_for, g
from flask_login import current_user, login_required
from qpanel.reporting import QueueReports, number
from qpanel.privacy import public_queue_snapshot
from Asterisk.Manager import ActionFailed, PermissionDenied, CommunicationError, GoneAwayError, InternalError

AMI_ERRORS = (Exception, ActionFailed, PermissionDenied, CommunicationError, GoneAwayError, InternalError)


def install(app, cfg, backend, get_data, render):
    action_lock = threading.RLock()
    audit_lock = threading.Lock()
    control_endpoints = ('spy', 'whisper', 'barge', 'hangup_call', 'remove_from_queue', 'pause_member', 'ops_control')
    def option(key, default):
        return cfg.get_value_set_default('sanequeue', key, default)

    def role():
        if not cfg.has_users() or current_user.get_id() in (None, 'withoutlogin', 'external_login'):
            return 'viewer'
        return cfg.get_value_set_default('roles', current_user.get_id(), 'viewer')

    def policy_store():
        return app.config.get('SANEQUEUE_POLICY_STORE')

    def queue_lock(queue):
        ledger=app.config.get('SANEQUEUE_ACTION_LEDGER')
        return ledger.queue_lock(queue) if ledger else nullcontext()

    def internal_extensions():
        provider=app.config.get('SANEQUEUE_EXTENSION_PROVIDER')
        return provider() if callable(provider) else app.config.get('SANEQUEUE_INTERNAL_EXTENSIONS',())

    def scope_data(data):
        store = policy_store()
        return store.visible(current_user.get_id() or '', role(), data) if store else {}

    def can_access_queue(queue, permission='view'):
        store = policy_store()
        return bool(store and store.access(current_user.get_id() or '', role(), queue, permission))

    def csrf():
        if 'csrf_token' not in session:
            session['csrf_token'] = secrets.token_hex(32)
        return session['csrf_token']

    def sections():
        from sanequeue.security.permissions import sections_for
        provider=app.config.get('SANEQUEUE_MENU_PROVIDER')
        return provider(current_user.get_id(),role()) if callable(provider) else sections_for(role())

    @app.context_processor
    def security_context():
        return dict(csrf_token=csrf, user_role=role(), can_view_section=lambda key:key in sections())

    @app.before_request
    def protect_sections():
        if not request.path.startswith('/api/') or not current_user.is_authenticated:return
        required=None
        path=request.path
        if path in ('/api/accounts','/api/accounts/with-grants'):required={'users'}
        elif path=='/api/policies':required={'policies','users','agents'} if request.method=='GET' else {'policies','users'}
        elif path.startswith('/api/notifications'):required={'settings'}
        elif path=='/api/pbx/health':required={'pbx','users'}
        elif path=='/api/quality':required={'pbx','control'}
        elif path in ('/api/control','/api/control/options') or path.startswith('/api/commands/'):required={'control','calls','waiting','agents','queues'}
        elif path=='/api/members/pause':required={'agents','queues','control'}
        elif path=='/api/operations':required={'live','queues','calls','waiting','agents','presence','wallboard','alerts','control'}
        elif path.startswith('/api/audit'):required={'audit'}
        elif path.startswith('/api/planning/'):required={path.rsplit('/',1)[-1]}
        if required is not None and not (sections() & required):abort(403)

    @app.before_request
    def protect_controls():
        if request.endpoint not in control_endpoints:
            return
        # Retired endpoints are forbidden in ANY deployment mode, not only demo.
        if request.endpoint in ('spy','whisper','barge','hangup_call','remove_from_queue'):
            abort(410)
        # Demo controls may be enabled ONLY by an in-process, temporary,
        # queue-scoped TEST gate. Unconfigured instances remain read-only.
        # Fail closed for ALL entrypoints, not just the local demo runtime.
        gate = app.config.get('SANEQUEUE_TEST_CONTROL_GUARD')
        if not callable(gate) or not gate(request):
            abort(403)
        if role() not in ('supervisor', 'admin') and not (role() == 'agent' and request.endpoint == 'pause_member'):
            abort(403)
        token = request.headers.get('X-CSRF-Token', request.form.get('csrf_token', ''))
        if not token or not hmac.compare_digest(token, session.get('csrf_token', '')):
            abort(400)
        data = scope_data(get_data())
        selected_queue = request.form.get('queue')
        permission = {'pause_member':'pause','remove_from_queue':'membership','ops_control':{'add':'membership','remove':'membership','penalty':'membership','spy':'monitor','whisper':'monitor','barge':'monitor','priority':'priority','first':'priority','hangup':'hangup','transfer':'transfer','attended_transfer':'transfer','cancel_transfer':'transfer','park':'park','retrieve':'park','pickup':'pickup','dial':'dial','hangup_active':'hangup'}.get(request.form.get('action'))}.get(request.endpoint, None)
        if not selected_queue or not permission or not can_access_queue(selected_queue,permission):
            abort(403)
        if request.endpoint in ('remove_from_queue', 'pause_member', 'ops_control'):
            if not selected_queue:
                abort(400)
            if selected_queue not in data:
                abort(403)
            agent = request.form.get('agent')
            members = data[selected_queue].get('members', {})
            adding = request.endpoint == 'ops_control' and request.form.get('action') == 'add'
            if agent and not adding and agent not in members and not any(agent == m.get('Location') for m in members.values()):
                abort(403)
            if role() == 'agent':
                own = cfg.get_value_set_default('agent_interfaces', current_user.get_id(), '').split(',')
                if not agent or agent not in [v.strip() for v in own]:
                    abort(403)
        else:
            # Only channels actually present in this user's visible queues.
            channel = request.form.get('channel', '')
            channels = set()
            for queue in data.values():
                for entry in queue.get('entries', {}).values():
                    channels.add(str(entry.get('Channel', '')))
                for key, member in queue.get('members', {}).items():
                    channels.update(str(v) for v in (key, member.get('Location', ''), member.get('StateInterface', '')) if v)
            if not channel or channel not in channels:
                abort(403)
        destination = request.form.get('to_exten')
        if destination and not re.match(r'^(SIP|PJSIP|Local)/[A-Za-z0-9_.@/+-]{1,100}$', destination):
            abort(400)
        if request.endpoint in ('spy', 'whisper', 'barge'):
            allowed = [s.strip() for s in cfg.get_value_set_default('supervisor_extensions', current_user.get_id(), '').split(',')]
            if destination not in allowed:
                abort(403)

    @app.after_request
    def audit_controls(response):
        if request.method == 'POST' and request.endpoint in control_endpoints:
            app.logger.info('audit user=%r action=%r queue=%r status=%s', current_user.get_id(), request.endpoint, request.form.get('queue'), response.status_code)
            record = dict(timestamp=int(time.time()), user=current_user.get_id(), action=request.form.get('action', request.endpoint), queue=request.form.get('queue'), agent=request.form.get('agent'), status=response.status_code)
            path = option('audit_path', os.path.join(app.root_path, '..', 'var', 'audit.jsonl'))
            try:
                with audit_lock:
                    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
                    # Bounded audit: keep current and one previous 5 MB file.
                    if os.path.exists(path) and os.path.getsize(path) > 5 * 1024 * 1024:
                        os.replace(path, path + '.1')
                    with open(path, 'a', encoding='utf-8') as stream:
                        stream.write(json.dumps(record, ensure_ascii=False) + '\n')
            except (OSError, UnicodeError):
                app.logger.exception('Audit file unavailable; event retained in service log')
        if request.endpoint and request.endpoint.startswith('ops_'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.route('/operations')
    @login_required
    def ops_home():
        from sanequeue.security.permissions import ROLE_SECTIONS,ROLE_ACTIONS
        from qpanel.user_help import GUIDES
        return render('operations.html', ops_config=dict(
            build_version=__import__('qpanel').__version__, test_controls_enabled=bool(app.config.get('SANEQUEUE_TEST_CONTROLS_STATUS', lambda:False)()), controls_status_url='/api/ami/control-status', controls_toggle_url='/api/ami/control-toggle', data_url=url_for('ops_data'), report_url=url_for('ops_reports'), pause_url=url_for('pause_member'), control_url=url_for('ops_control'), audit_url=url_for('ops_audit'),
            interval=max(2000, cfg.interval * 1000), csrf=csrf(), role=role(), demo_mode=str(option('demo_mode','false')).lower()=='true',
            wait_threshold=number(option('wait_threshold', 60)),
            pause_threshold=number(option('pause_threshold', 900)),
            own_interfaces=[v.strip() for v in cfg.get_value_set_default('agent_interfaces', current_user.get_id() or '', '').split(',')],
            reports_enabled=str(option('reports_enabled', 'false')).lower() == 'true',
            destinations=[v.strip() for v in cfg.get_value_set_default('supervisor_extensions', current_user.get_id() or '', '').split(',') if v.strip()],
            realtime_push=bool(app.config.get('SANEQUEUE_REALTIME_PUSH')), websocket_url='/ws/operations',
            logged_in_user=current_user.get_id(), assigned_phone=cfg.get_value_set_default('supervisor_extensions',current_user.get_id() or '',''),
            allowed_sections=sorted(sections()),
            role_sections={key:sorted(value) for key,value in ROLE_SECTIONS.items()},
            role_actions={key:sorted(value) for key,value in ROLE_ACTIONS.items()},
            help={key:GUIDES[key]['fa' if session.get('language',cfg.language)=='fa' else 'en'] for key in sections() if key in GUIDES},
            control_mode=app.config.get('SANEQUEUE_CONTROL_MODE','test-gate'),
            queue_url=url_for('queue', name='__QUEUE__'), language_url=url_for('language', language='__LANG__'), ami_settings_url='/api/ami/settings', ami_test_url='/api/ami/test', ami_connect_url='/api/ami/connect'))

    @app.route('/api/notifications', methods=['GET','POST'])
    @login_required
    def ops_notifications():
        if role()!='admin':abort(403)
        settings=app.config.get('SANEQUEUE_NOTIFICATIONS')
        if settings is None:return jsonify(error='notification_service_unavailable'),503
        if request.method=='GET':return jsonify(providers=settings.public())
        if not hmac.compare_digest(request.headers.get('X-CSRF-Token',''),session.get('csrf_token','')) or not session.get('csrf_token'):
            abort(403)
        if (request.content_length or 0)>4096:return jsonify(error='payload_too_large'),413
        try:return jsonify(providers=settings.replace(request.get_json(silent=True)))
        except ValueError:return jsonify(error='invalid_notification_settings'),400

    @app.route('/api/notifications/test', methods=['POST'])
    @login_required
    def ops_notifications_test():
        if role()!='admin':abort(403)
        if not session.get('csrf_token') or not hmac.compare_digest(request.headers.get('X-CSRF-Token',''),session['csrf_token']):abort(403)
        settings=app.config.get('SANEQUEUE_NOTIFICATIONS')
        if settings is None:return jsonify(error='notification_service_unavailable'),503
        if time.time()-session.get('notification_test_at',0)<10:return jsonify(error='test_rate_limited'),429
        payload=request.get_json(silent=True)
        if not isinstance(payload,dict) or payload.get('provider') not in ('telegram','bale'):return jsonify(error='invalid_provider'),400
        session['notification_test_at']=time.time()
        from sanequeue.alerts.messaging import MessagingError
        try:
            success=settings.send(payload['provider'],test=True)
            return jsonify(accepted=success),200 if success else 502
        except MessagingError as error:return jsonify(error=str(error)),502

    @app.route('/api/operations')
    @login_required
    def ops_data():
        from qpanel.queue_policies import ALLOWED_GRANTS
        data = scope_data(get_data())
        if getattr(g, 'sanequeue_state_error', getattr(backend, 'last_error', False)):
            return jsonify(error='pbx_unavailable'), 503
        channel_details = False
        provider = app.config.get('SANEQUEUE_CHANNEL_PROVIDER')
        if callable(provider):
            from qpanel.compatibility import device_channel
            try:
                channels = provider(data.keys())
                channel_details = True
                for queue in data.values():
                    for interface, member in queue.get('members', {}).items():
                        try:
                            target = device_channel(member, interface, channels)
                        except ValueError:
                            continue
                        match = next((c for c in channels if c.get('Channel') == target), None)
                        if match:
                            member.update(LiveDuration=str(match['Duration']), LiveHoldSeconds=match['HoldSeconds'],
                                LiveCaller=match.get('CallerIDNum',''), LiveChannelState=match.get('ChannelStateDesc',''),
                                LiveChannel=match['Channel'])
            except Exception:
                return jsonify(error='collector_unavailable'),503
        elif not backend.is_freeswitch() and str(option('live_channels', 'true')).lower() == 'true':
            manager = backend._connect()
            try:
                channels = manager.connection.CoreShowChannels()
                channel_details = True
                for queue in data.values():
                    for key, member in queue.get('members', {}).items():
                        prefixes = [str(v).removesuffix('/n') if hasattr(str, 'removesuffix') else re.sub(r'/n$', '', str(v)) for v in (key, member.get('StateInterface', key))]
                        match = next((c for c in channels if any(str(c.get('Channel', '')).startswith(prefix + '-') for prefix in prefixes)), None)
                        if match:
                            member['LiveDuration'] = str(match.get('Duration', ''))
                            member['LiveCaller'] = str(match.get('ConnectedLineNum') or match.get('CallerIDNum') or '')
                            member['LiveChannelState'] = str(match.get('ChannelStateDesc') or '')
                            member['LiveChannel'] = str(match.get('Channel') or '')
            except AMI_ERRORS:
                app.logger.debug('Channel details unavailable; QueueStatus remains usable')
            finally:
                if manager.connection:
                    try:
                        manager.connection.close()
                    except AMI_ERRORS:
                        pass
        store = policy_store()
        alert_provider=app.config.get('SANEQUEUE_ALERT_PROVIDER')
        policy_result = dict(alert_provider(data.keys()),notify=[]) if callable(alert_provider) else store.evaluate(data) if store and getattr(backend, 'live_source', '') == 'ami-live' else {'alerts':[], 'notify':[], 'notification_status':{}}
        if policy_result['notify'] and os.getenv('SANEQUEUE_ENABLE_BALE_ALERTS') == '1' and os.getenv('SANEQUEUE_BALE_BOT_TOKEN') and os.getenv('SANEQUEUE_BALE_CHAT_ID'):
            from qpanel.queue_policies import send_bale_alert
            def _push_alerts(alert_list):
                for alert in alert_list:
                    try:
                        ok = send_bale_alert(alert, os.getenv('SANEQUEUE_BALE_BOT_TOKEN'), os.getenv('SANEQUEUE_BALE_CHAT_ID'))
                        store.note_delivery(ok, '' if ok else 'bale_declined')
                    except Exception:
                        # Never log request URLs, tokens, chat IDs, or caller data.
                        store.note_delivery(False, 'delivery_failed')
            threading.Thread(target=_push_alerts, args=(policy_result['notify'],), daemon=True).start()
        # The read-only call journey engine is independent of queue membership.
        # Only callers whose queues are authorized are returned. The browser
        # never receives AMI Uniqueid/Linkedid or raw channel identifiers.
        journey_provider = app.config.get('SANEQUEUE_CALL_JOURNEYS')
        numbers_allowed = (role() == 'admin' or (role() == 'supervisor' and all(
            can_access_queue(q, 'caller_details') for q in data)))
        journeys = journey_provider(data.keys(), numbers_allowed) if callable(journey_provider) and getattr(backend, 'live_source', '') == 'ami-live' else {
            'connected': False, 'records': [], 'complete_history': False}
        return jsonify(permissions={q:sorted(action for action in ALLOWED_GRANTS if can_access_queue(q,action)) for q in data},call_journeys=journeys, queues=public_queue_snapshot(data, privileged=role() in ('admin','supervisor'), reveal_numbers=(role()=='admin' or (role()=='supervisor' and all(can_access_queue(q,'caller_details') for q in data)))), policy_alerts=policy_result['alerts'], notification_status=policy_result['notification_status'],timestamp=int(time.time()), role=role(), caller_numbers_visible=(role()=='admin' or (role()=='supervisor' and all(can_access_queue(q,'caller_details') for q in data))),
                       control_status=(app.config.get('SANEQUEUE_CONTROL_STATE') or (lambda:None))(),
                       channel_details=channel_details, controls_enabled=bool(app.config.get('SANEQUEUE_TEST_CONTROLS_STATUS', lambda:False)()) and getattr(backend, 'live_source', '') == 'ami-live',
                       minimum_ready=number(option('minimum_ready', 0)), minimum_ready_percent=number(option('minimum_ready_percent', 0)),
                       stats_scope='since_queue_reset', observed_at=getattr(backend, 'latest_sample_unix', None), backend='freeswitch' if backend.is_freeswitch() else 'asterisk', data_source=getattr(backend, 'live_source', 'demo' if str(option('demo_mode','false')).lower()=='true' else 'pbx'))

    @app.route('/api/members/pause', methods=['POST'])
    @login_required
    def pause_member():
        queue, agent = request.form.get('queue', ''), request.form.get('agent', '')
        if not queue or not agent or backend.is_freeswitch():
            abort(400)
        paused = request.form.get('paused')
        if paused not in ('true', 'false'):
            abort(400)
        reason = request.form.get('reason', '')[:80]
        if any(c in reason + agent + queue for c in '\r\n\x00'):
            abort(400)
        with action_lock, queue_lock(queue):
            visible = get_data(queue)
            store = policy_store()
            if store:
                try:
                    store.validate_reason(queue, reason if paused == 'true' else '')
                except ValueError:
                    return jsonify(error='invalid_pause_reason'), 400
                if paused == 'true' and queue in store.export()['queues']:
                    permitted, issue = store.reserve_leave(queue, visible, agent)
                    if not permitted: return jsonify(error=issue), 409
            if paused == 'true' and not staffing_allows(visible, agent):
                if store:store.release_leave(queue,agent)
                return jsonify(error='minimum_ready'), 409
            result = ami_action('QueuePause', {'Queue': cfg.realname_queue(queue), 'Interface': agent, 'Paused': paused, 'Reason': reason})
            if store and ((paused == 'true' and definitely_rejected(result)) or paused == 'false'):
                store.release_leave(queue, agent)
            return result

    def staffing_allows(queue, excluded):
        members = queue.get('members', {})
        minimum = max(number(option('minimum_ready', 0)), math.ceil(len(members) * min(100, number(option('minimum_ready_percent', 0))) / 100))
        # 'Ready to take the NEXT queue call' differs from on-duty.
        # Busy/ringing/on-hold membership must not be treated as Ready.
        available = sum(1 for key, member in members.items()
                        if str(member.get('Status', '0')) == '1'
                        and str(member.get('Paused', '0')).lower() in ('0', 'false')
                        and str(member.get('InCall', '0')).lower() in ('0', 'false')
                        and member.get('Ready',True) is not False
                        and excluded not in (key, member.get('Location')))
        return available >= minimum

    def definitely_rejected(response):
        if app.config.get('SANEQUEUE_ACTION_LEDGER'):
            return (response.get_json(silent=True) or {}).get('state')=='rejected'
        return response.status_code>=400

    def ami_action(name, fields):
        executor=app.config.get('SANEQUEUE_ACTION_EXECUTOR')
        if callable(executor):return app.make_response(executor(name,fields))
        manager = backend._connect()
        try:
            action_id = 'sq-' + secrets.token_hex(8)
            fields = dict(fields, ActionID=action_id)
            action = manager.connection._write_action(name, fields)
            result = manager.connection._translate_response(manager.connection.read_response(action))
            if not isinstance(result, dict) or str(result.get('Response', '')).lower() != 'success':
                return app.make_response((jsonify(error='asterisk_action_rejected'), 502))
            return app.make_response((jsonify(ok=True, state='ami_accepted_unverified', confirmed=False, action_id=action_id), 202))
        except AMI_ERRORS:
            app.logger.warning('AMI action failed: %s', name)
            return app.make_response((jsonify(error='asterisk_action_failed_or_disconnected'), 502))
        finally:
            if manager.connection:
                try:
                    manager.connection.close()
                except AMI_ERRORS:
                    pass

    @app.route('/api/control', methods=['POST'])
    @login_required
    def ops_control():
        if backend.is_freeswitch():
            abort(400)
        action = request.form.get('action', '')
        queue = request.form.get('queue', '')
        agent = request.form.get('agent', '')
        channel = request.form.get('channel', '')
        if any(c in queue + agent + channel for c in '\r\n\x00'):
            abort(400)
        with action_lock, queue_lock(queue):
            data = get_data(queue)
            from sanequeue.actions.plans import PERMISSIONS, plan
            if action in PERMISSIONS:
                if action not in app.config.get('SANEQUEUE_ADVANCED_ACTIONS',()):
                    return jsonify(error='action_not_enabled_for_this_pbx'),409
                private=app.config.get('SANEQUEUE_PRIVATE_STATE')
                if not callable(private):return jsonify(error='persistent_collector_required'),409
                from sanequeue.api.state import StateUnavailable
                try:
                    state=private()
                    allowed=list(scope_data(get_data()))
                    own=cfg.get_value_set_default('supervisor_extensions',current_user.get_id(),'')
                    name,fields=plan(state,queue,action,channel,destination=request.form.get('extension',''),
                        own_phone=own,extensions=internal_extensions(),
                        context=app.config.get('SANEQUEUE_TRANSFER_CONTEXT','from-internal'),
                        parkinglot=app.config.get('SANEQUEUE_PARKING_LOT','default'),allowed_queues=allowed)
                except StateUnavailable:return jsonify(error='collector_unavailable'),503
                except ValueError as exc:return jsonify(error=str(exc)),409
                return ami_action(name,fields)
            base = {'Queue': cfg.realname_queue(queue)}
            if action in ('priority', 'first', 'hangup'):
                entries = list(data.get('entries', {}).values())
                if not channel or not any(str(e.get('Channel')) == channel for e in entries):
                    return jsonify(error='call_not_waiting_in_selected_queue'),409
                if action == 'hangup':
                    return ami_action('Hangup', {'Channel': channel})
                try:
                    priority = max([int(e.get('Priority', 0)) for e in entries] + [0]) + 1 if action == 'first' else int(request.form.get('priority', ''))
                    if not -1000000 <= priority <= 1000000:
                        raise ValueError()
                except ValueError:
                    abort(400)
                base.update(Caller=channel, Priority=str(priority), Immediate='yes')
                return ami_action('QueueChangePriorityCaller', base)
            if action in ('spy', 'whisper', 'barge'):
                member = next((m for key, m in data.get('members', {}).items() if agent in (key, m.get('Location'))), None)
                if member is None:
                    abort(403)
                # Only intercept an established conversation on the test queue.
                if str(member.get('InCall','0')).lower() not in ('1','true'):
                    return jsonify(error='agent_not_in_active_call'),409
                # Never trust the destination sent by the browser. It is bound to
                # the authenticated account, not an arbitrary phone number.
                allowed = [s.strip() for s in cfg.get_value_set_default('supervisor_extensions',current_user.get_id(),'').split(',') if s.strip()]
                if len(allowed)!=1 or not re.fullmatch(r'(SIP|PJSIP)/[A-Za-z0-9_.-]{1,48}',allowed[0]):
                    return jsonify(error='assigned_supervisor_phone_required'), 403
                destination=allowed[0]
                submitted=request.form.get('destination','')
                if submitted and submitted!=destination:
                    return jsonify(error='destination_not_allowed'), 403
                from qpanel.compatibility import spy_target
                channels = []
                provider = app.config.get('SANEQUEUE_CHANNEL_PROVIDER')
                if callable(provider):
                    channels = provider([queue])
                elif str(member.get('StateInterface', '')).startswith('hint:'):
                    resolver = backend._connect()
                    try:
                        channels = resolver.connection.CoreShowChannels()
                    except AMI_ERRORS:
                        return jsonify(error='device_channel_discovery_unavailable'), 409
                    finally:
                        if resolver.connection:
                            try: resolver.connection.close()
                            except AMI_ERRORS: pass
                overrides = dict(cfg.get_items('device_channels') or [])
                try:
                    if callable(provider):
                        from qpanel.compatibility import device_channel
                        target = device_channel(member, agent, channels, overrides)
                    else:
                        target = spy_target(member, agent, channels, overrides)
                    if target == destination or target.startswith(destination+'-'):
                        return jsonify(error='supervisor_cannot_monitor_own_phone'),409
                except ValueError as exc:
                    return jsonify(error=str(exc)), 409
                mode = {'spy': 'q', 'whisper': 'qw', 'barge': 'qB'}[action]
                return ami_action('Originate', {'Channel': destination, 'Application': 'ChanSpy', 'Data': str(target) + ',' + mode, 'Async': 'true', 'Timeout': '60000', 'CallerID': 'SaneQueue <'+destination.split('/',1)[1]+'>'})
            if action in ('add', 'remove', 'penalty'):
                if not re.match(r'^(SIP|PJSIP|Local)/[A-Za-z0-9_.@/+-]{1,100}$', agent):
                    abort(400)
                base['Interface'] = agent
                if action == 'remove':
                    member = next((m for key,m in data.get('members', {}).items()
                                   if agent in (key, m.get('Location'))), None)
                    if member is not None and str(member.get('Membership','')).lower() == 'static':
                        return jsonify(error='static_member_must_be_managed_in_issabel'), 409
                    store = policy_store()
                    if store and queue in store.export()['queues']:
                        permitted, issue = store.reserve_leave(queue, data, agent)
                        if not permitted:return jsonify(error=issue), 409
                    if not staffing_allows(data, agent):
                        if store:store.release_leave(queue,agent)
                        return jsonify(error='minimum_ready'), 409
                    response = ami_action('QueueRemove', base)
                    if store and definitely_rejected(response):store.release_leave(queue, agent)
                    return response
                try:
                    penalty = int(request.form.get('penalty', '0'))
                    if not 0 <= penalty <= 100:
                        raise ValueError()
                except ValueError:
                    abort(400)
                base['Penalty'] = str(penalty)
                if action == 'add':
                    store = policy_store()
                    if store and queue in store.export()['queues']:
                        roster = store.queue(queue)['staffing']['roster_size']
                        if not roster:
                            return jsonify(error='configure_roster_size_before_joining'),409
                        if len(data.get('members',{})) >= roster:
                            return jsonify(error='queue_roster_full'),409
                    if role() != 'admin':
                        abort(403)
                    base.update(Paused='false', MemberName=agent)
                return ami_action('QueueAdd' if action == 'add' else 'QueuePenalty', base)
            abort(400)

    @app.route('/api/audit')
    @login_required
    def ops_audit():
        if role() not in ('admin', 'supervisor'):
            abort(403)
        allowed = scope_data(get_data())
        path = option('audit_path', os.path.join(app.root_path, '..', 'var', 'audit.jsonl'))
        from collections import deque
        rows = []
        try:
            with open(path, encoding='utf-8') as stream:
                for line in deque(stream, maxlen=100):
                    try:
                        row = json.loads(line)
                        if row.get('queue') in allowed or (role() == 'admin' and row.get('queue') is None):
                            rows.append(row)
                    except ValueError:
                        continue
        except FileNotFoundError:
            pass
        return jsonify(events=list(reversed(rows)))

    @app.route('/api/commands/<ident>')
    @login_required
    def command_state(ident):
        ledger=app.config.get('SANEQUEUE_ACTION_LEDGER')
        if not ledger or not re.fullmatch(r'sq-[0-9a-f]{32}',ident):abort(404)
        result=ledger.public(ident,current_user.get_id(),scope_data(get_data()))
        if result is None:abort(404)
        return jsonify(result)

    @app.route('/api/control/options')
    @login_required
    def control_options():
        if role() not in ('admin','supervisor'):abort(403)
        allowed=scope_data(get_data())
        queue=request.args.get('queue','')
        if queue not in allowed:abort(403)
        private=app.config.get('SANEQUEUE_PRIVATE_STATE')
        if not callable(private):return jsonify(actions=[],targets=[],parked=[],extensions=[])
        from sanequeue.actions.plans import PERMISSIONS
        from sanequeue.api.state import scoped_channels, StateUnavailable
        from qpanel.compatibility import device_channel
        try:state=private()
        except StateUnavailable:return jsonify(error='collector_unavailable'),503
        channels=scoped_channels(state,allowed)
        candidates=[dict(Channel=c.get('channel','')) for c in channels.values() if queue in c['queues']]
        targets=[]
        for agent,member in allowed[queue].get('members',{}).items():
            try:channel=device_channel(member,agent,candidates)
            except ValueError:continue
            targets.append(dict(agent=agent,channel=channel,label=member.get('Name') or agent))
        known={target['channel'] for target in targets}
        for channel in candidates:
            name=channel['Channel']
            if name not in known and name.startswith(('SIP/','PJSIP/')):
                targets.append(dict(agent='',channel=name,label=name.rsplit('-',1)[0]))
                known.add(name)
        parked=[dict(key=k,space=v.get('parkingspace'),lot=v.get('parkinglot')) for k,v in state.get('parked',{}).items()
                if queue in v.get('queues',[]) and set(v['queues']).issubset(allowed)]
        actions=[a for a in app.config.get('SANEQUEUE_ADVANCED_ACTIONS',()) if a in PERMISSIONS and can_access_queue(queue,PERMISSIONS[a])]
        return jsonify(actions=actions,targets=targets,parked=parked,extensions=list(internal_extensions()))

    @app.route('/api/quality')
    @login_required
    def media_quality():
        if role() not in ('admin','supervisor'):abort(403)
        allowed=scope_data(get_data())
        private=app.config.get('SANEQUEUE_PRIVATE_STATE')
        if not callable(private):return jsonify(error='persistent_collector_required'),409
        from sanequeue.api.state import scoped_channels, StateUnavailable
        try:state=private()
        except StateUnavailable:return jsonify(error='collector_unavailable'),503
        rows=[]
        for channel in scoped_channels(state,allowed).values():
            quality=channel.get('rtcp')
            if quality:
                rows.append(dict(queues=channel['queues'],technology=channel.get('channel','').split('/')[0],
                    rtt_ms=quality.get('rtt_ms'),loss_pct=quality.get('loss_pct'),
                    jitter_ticks=quality.get('jitter_ticks'),sampled_at=quality.get('sampled_at'),
                    stale=time.time()-quality.get('sampled_at',0)>30,direction=quality.get('direction')))
        return jsonify(streams=rows[:200],source='observed_rtcp',mos=None,
                       jitter_unit='rtp_timestamp_ticks',complete=False)


    @app.route('/api/queue/summary')
    @login_required
    def ops_queue_summary():
        queue = request.args.get('queue','')
        if not queue or not can_access_queue(queue): abort(403)
        data = scope_data(get_data())
        if queue not in data:abort(404)
        store = policy_store()
        if not store:return jsonify(error='policy_store_unavailable'),503
        return jsonify(store.summary(queue,data[queue]))

    @app.route('/api/reports')
    @login_required
    def ops_reports():
        if str(option('reports_enabled', 'false')).lower() != 'true':
            return jsonify(error='reports_deferred'), 404
        if backend.is_freeswitch():
            return jsonify(error='asterisk_only'), 400
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            start = datetime.strptime(request.args.get('from', today), '%Y-%m-%d')
            end = datetime.strptime(request.args.get('to', today), '%Y-%m-%d') + timedelta(days=1)
            if end <= start or (end - start).days > 93:
                raise ValueError()
        except ValueError:
            return jsonify(error='invalid_date_range'), 400
        # Even when reports are explicitly enabled, never disclose queues
        # outside the authenticated user's policy scope.
        if policy_store() is None:
            abort(403)
        data = scope_data(get_data())
        if getattr(g, 'sanequeue_state_error', getattr(backend, 'last_error', False)):
            return jsonify(error='pbx_unavailable'), 503
        selected = request.args.get('queue', '')
        if selected and selected not in data:
            abort(403)
        names = [selected] if selected else list(data)
        allowed = {cfg.realname_queue(name): name for name in names}
        database = option('report_database', os.path.join(app.root_path, '..', 'var', 'reports.sqlite3'))
        reports = QueueReports(database)
        try:
            ingestion = reports.ingest(option('queue_log_path', '/var/log/asterisk/queue_log'))
            result = reports.report(start.timestamp(), end.timestamp(), allowed, number(option('sla_seconds', 20)))
        except (OSError, __import__('sqlite3').Error):
            app.logger.exception('Queue reports unavailable')
            return jsonify(error='report_source_unavailable'), 503
        for row in result['rows']:
            row['queue'] = allowed[row['queue']]
        result.update(ingestion=ingestion, timezone=time.tzname[0], start=start.isoformat(), end=end.isoformat())
        if request.args.get('format') == 'csv':
            output = io.StringIO()
            writer = csv.writer(output)
            fields = ['queue', 'agent', 'entered', 'answered', 'abandoned', 'completed', 'missed', 'within_sla', 'wait_seconds', 'talk_seconds']
            writer.writerow(fields)
            for row in result['rows']:
                writer.writerow([("'" + str(row[f])) if str(row[f]).lstrip().startswith(('=', '+', '-', '@')) else row[f] for f in fields])
            return Response('\ufeff' + output.getvalue(), mimetype='text/csv; charset=utf-8', headers={'Content-Disposition': 'attachment; filename="sanequeue-report.csv"'})
        return jsonify(result)

    return ops_home
