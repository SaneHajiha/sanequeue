import os
import sys
import time
import copy
import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch
import secrets
from qpanel.test_control_gate import TestControlGate
from AMI_READONLY_TEST import ReadOnlyAMI
from qpanel.ami_live import read_queue_data
from qpanel.call_journey_listener import JourneyListener, parse_trunk_map
from qpanel.ami_targets import validate_target
from qpanel.queue_visibility import filter_queue_data, normalize_visible_queues, is_queue_visible, parse_visible_queues
from qpanel.queue_policies import QueuePolicyStore, DEFAULT_QUEUE
from qpanel.ami_connection_qa import classify_error, safe_stage
from qpanel.local_accounts import bootstrap, read_accounts, set_account, public_accounts
import threading

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
SERVER_MODE = os.getenv('SANEQUEUE_RUNTIME') == 'server'
STATE = Path(os.environ.get('SANEQUEUE_STATE_DIR', str(ROOT))).resolve()
STATE.mkdir(parents=True, exist_ok=True)
if SERVER_MODE and not os.getenv('QPANEL_CONFIG_FILE'):
    raise RuntimeError('Server mode requires QPANEL_CONFIG_FILE')
if not SERVER_MODE:
    os.environ['QPANEL_CONFIG_FILE'] = str(ROOT / 'tests/data/configs/config_default.ini')
import qpanel.backend as qbackend
with patch.object(qbackend.Backend, '_connect'):
    from qpanel import app as module
from flask import session, request, jsonify, abort
from flask_login import login_required, current_user
from qpanel.backend import Backend

# Never use an example config secret to sign live-control cookies.
secret_path = STATE / 'session.key'
if not secret_path.exists():
    fd=os.open(str(secret_path),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as stream: stream.write(secrets.token_hex(32))
module.app.secret_key = secret_path.read_text(encoding='utf-8').strip()
module.app.config['SESSION_COOKIE_HTTPONLY'] = True
module.app.config['MAX_CONTENT_LENGTH'] = 1024 * 1024
module.app.config['SANEQUEUE_REQUIRE_SESSION_VERSION'] = SERVER_MODE
module.app.config['SESSION_COOKIE_SAMESITE'] = 'Strict'
module.app.config['SESSION_COOKIE_SECURE'] = os.getenv('SANEQUEUE_HTTPS') == '1'
if os.getenv('SANEQUEUE_TRUST_PROXY') == '1':
    from werkzeug.middleware.proxy_fix import ProxyFix
    module.app.wsgi_app = ProxyFix(module.app.wsgi_app, x_proto=1, x_host=1)


cfg = module.cfg
cfg.language = cfg.language if SERVER_MODE else 'fa'
for section in ('users', 'roles', 'supervisor_extensions', 'sanequeue'):
    if not cfg.config.has_section(section):
        cfg.config.add_section(section)
ACCOUNTS_PATH = STATE / 'local_accounts.json'
if SERVER_MODE and not read_accounts(ACCOUNTS_PATH):
    raise RuntimeError('Initialize accounts first: python scripts/init_accounts.py --state '+str(STATE))
first_password = None if SERVER_MODE else bootstrap(ACCOUNTS_PATH)
if first_password:
    print('\n'+'='*62,flush=True)
    print('FIRST RUN ADMIN LOGIN - SAVE THIS PASSWORD NOW',flush=True)
    print('Username: admin',flush=True)
    print('Password: '+first_password,flush=True)
    print('This password is shown only once and is stored HASHED.',flush=True)
    print('='*62+'\n',flush=True)
def sync_accounts():
    for section in ('users','roles','supervisor_extensions','agent_interfaces'):
        if cfg.config.has_section(section): cfg.config.remove_section(section)
        cfg.config.add_section(section)
    for username, account in read_accounts(ACCOUNTS_PATH).items():
        cfg.config.set('users',username,account['password_hash'])
        cfg.config.set('roles',username,account['role'])
        if account.get('phone'):
            cfg.config.set('supervisor_extensions',username,account['phone'])
            if not cfg.config.has_section('agent_interfaces'):
                cfg.config.add_section('agent_interfaces')
            cfg.config.set('agent_interfaces',username,account['phone']+(',Local/'+account['phone'].split('/',1)[1]+'@from-queue/n' if account['phone'].startswith(('PJSIP/','SIP/')) else ''))
        else:
            cfg.config.remove_option('supervisor_extensions',username)
            if cfg.config.has_section('agent_interfaces'):
                cfg.config.remove_option('agent_interfaces',username)
sync_accounts()
from sanequeue.security.permissions import sections_for
from qpanel.local_accounts import canonical_username,delete_account,LOCK as ACCOUNT_LOCK
module.app.config['SANEQUEUE_ACCOUNT_CANONICALIZER']=lambda username:canonical_username(ACCOUNTS_PATH,username)
def account_sections(username,role):
    account=read_accounts(ACCOUNTS_PATH).get(username)
    return sections_for(role,account) if account is not None else frozenset()
module.app.config['SANEQUEUE_MENU_PROVIDER']=account_sections
from sanequeue.security.profile import install as install_profile
install_profile(module.app,ACCOUNTS_PATH,STATE,sync_accounts)
from sanequeue.security.organization import install as install_organization,disabled as module_disabled
install_organization(module.app,STATE,lambda:cfg.get_value_set_default('roles',current_user.get_id() or '','viewer'))

@module.app.before_request
def maintenance_controls():
    if module_disabled() and (request.path in ('/api/control','/api/members/pause') or request.path.startswith('/api/ami/')):
        return jsonify(error='module_disabled'),503
cfg.config.set('sanequeue', 'minimum_ready_percent', cfg.get_value_set_default('sanequeue','minimum_ready_percent','0'))  # Isolated test queue may have only one agent.
cfg.config.set('sanequeue', 'demo_mode', 'false' if SERVER_MODE else 'true')
cfg.config.set('sanequeue', 'live_channels', 'false')
if SERVER_MODE:
    AMI_BOOTSTRAP = cfg.get_value_set_default('manager','password','')
    cfg.config.set('sanequeue','audit_path',str(STATE / 'audit.jsonl'))  # QueueStatus read-only first; detailed calls need a separate validated adapter

now = int(time.time())

def member(name, status, calls, paused='0'):
    return dict(
        Name=name,
        Status=status,
        CallsTaken=calls,
        Paused=paused,
        InCall='1' if status == '10' else '0',
        LastCallAgo='۲ دقیقه پیش',
        LastPause=now - 1000 if paused == '1' else 0,
        PausedReason='استراحت' if paused == '1' else ''
    )

DATA = {
 'پشتیبانی مشتریان': dict(Completed='128', Abandoned='7', Calls='3', Strategy='rrmemory', ServicelevelPerf='92', Holdtime='24', TalkTime='180',
  members={'PJSIP/101': member('کارشناس نمونه ۱', '1', '42'), 'PJSIP/102': member('کارشناس نمونه ۲', '10', '38'), 'PJSIP/103': member('کارشناس نمونه ۳', '1', '48')},
  entries={'1': dict(Channel='PJSIP/demo-1', CallerIDName='تماس آزمایشی', CallerIDNum='02100000001', Position='1', Wait='82', Priority='0'), '2': dict(Channel='PJSIP/demo-2', CallerIDNum='02100000002', Position='2', Wait='35', Priority='0'), '3': dict(Channel='PJSIP/demo-3', CallerIDNum='02100000003', Position='3', Wait='12', Priority='0')}),
 'مشاوره و فروش': dict(Completed='64', Abandoned='2', Calls='0', Strategy='ringall', ServicelevelPerf='97', Holdtime='12', TalkTime='210',
  members={'PJSIP/201': member('کارشناس نمونه ۴', '1', '34'), 'PJSIP/202': member('کارشناس نمونه ۵', '1', '30', '1')}, entries={}),
 'خدمات سازمانی': dict(Completed='35', Abandoned='0', Calls='0', Strategy='leastrecent', ServicelevelPerf='100', Holdtime='8', TalkTime='200',
  members={'PJSIP/301': member('کارشناس نمونه ۶', '1', '35')}, entries={})
}

SETTINGS_PATH = STATE / 'local_ami_settings.json'
CONTROL_GATE = TestControlGate()
POLICIES = QueuePolicyStore(STATE / 'local_queue_policies.json')
module.app.config['SANEQUEUE_POLICY_STORE'] = POLICIES
# AMI password lives ONLY in process memory; no plaintext secrets are written to disk.
AMI_RUNTIME = {'password': AMI_BOOTSTRAP if SERVER_MODE else '', 'enabled': SERVER_MODE and bool(AMI_BOOTSTRAP)}
AMI_LOCK = threading.RLock()
JOURNEY_LISTENER = JourneyListener()
module.app.config['SANEQUEUE_CALL_JOURNEYS'] = lambda queue_names, numbers: JOURNEY_LISTENER.snapshot(queue_names, numbers=numbers)
PERSISTENT_READER = None
if os.environ.get('SANEQUEUE_COLLECTOR_CONFIG'):
    from redis import Redis
    from sanequeue.realtime.config import Settings
    from sanequeue.api.state import StateReader, legacy_queues, journey_projection, scoped_channels
    collector_settings = Settings.load(os.environ['SANEQUEUE_COLLECTOR_CONFIG'])
    PERSISTENT_READER = StateReader(Redis.from_url(collector_settings.redis_url, decode_responses=True,
        socket_timeout=2, socket_connect_timeout=2, max_connections=16), collector_settings.pbx_id)
    def persistent_journeys(queue_names, numbers):
        state, health = PERSISTENT_READER.read()
        return journey_projection(state, queue_names, numbers)
    def persistent_channels(queue_names):
        state, health = PERSISTENT_READER.read()
        now = time.time()
        return [dict(Channel=c.get('channel',''), Uniqueid=uid,
                     ChannelStateDesc=c.get('channelstatedesc',''),
                     CallerIDNum=c.get('connectedlinenum') or c.get('calleridnum',''),
                     Duration=str(max(0,int(now-c.get('answered_at',c.get('bridge_entered_at',c.get('created_at',now)))))),
                     HoldSeconds=int(c.get('hold_seconds',0)+max(0,now-c['held_since']) if c.get('held_since') else c.get('hold_seconds',0)),
                     Queues=c['queues']) for uid,c in scoped_channels(state,queue_names).items()]
    module.app.config['SANEQUEUE_CALL_JOURNEYS'] = persistent_journeys
    module.app.config['SANEQUEUE_CHANNEL_PROVIDER'] = persistent_channels
    module.app.config['SANEQUEUE_REALTIME_PUSH'] = True
    cfg.config.set('sanequeue','live_channels','true')
    from sanequeue.actions.ledger import ActionLedger, QueueBusy
    from sanequeue.actions.transport import send_action
    ACTION_LEDGER=ActionLedger(STATE/'actions.sqlite3',reservation_seconds=collector_settings.reconcile_seconds+30)
    POLICIES.reservation_backend=ACTION_LEDGER
    module.app.config['SANEQUEUE_ACTION_LEDGER']=ACTION_LEDGER
    def execute_persistent_action(name, fields):
        state,health=PERSISTENT_READER.read(fresh=True)
        if time.time()-health.get('published_at',0)>3:
            return jsonify(error='collector_not_fresh_enough'),409
        control=os.environ.get('SANEQUEUE_CONTROL_CONFIG')
        if not control:return jsonify(error='separate_control_identity_required'),403
        ident=ACTION_LEDGER.create(current_user.get_id(),request.form.get('queue',''),name,fields)
        try:
            accepted=send_action(control,name,fields,ident)
        except PermissionError:
            ACTION_LEDGER.update(ident,'rejected','control_identity_rejected')
            return jsonify(error='control_identity_rejected',action_id=ident,state='rejected'),502
        except Exception:
            ACTION_LEDGER.update(ident,'unknown','transport_failed_no_automatic_retry')
            return jsonify(error='command_outcome_unknown',action_id=ident,state='unknown'),502
        if not accepted:
            ACTION_LEDGER.update(ident,'rejected','ami_rejected')
            return jsonify(error='asterisk_action_rejected',action_id=ident,state='rejected'),502
        return jsonify(ok=True,action_id=ident,state='pending',confirmed=False),202
    module.app.config['SANEQUEUE_ACTION_EXECUTOR']=execute_persistent_action
    module.app.config['SANEQUEUE_PRIVATE_STATE']=lambda: PERSISTENT_READER.read(fresh=True)[0]
    module.app.config['SANEQUEUE_INTERNAL_EXTENSIONS']=tuple(v.strip() for v in os.environ.get('SANEQUEUE_INTERNAL_EXTENSIONS','').split(',') if v.strip())
    if os.getenv('SANEQUEUE_AUTO_EXTENSIONS')=='1':
        def _discovered_internal_extensions():
            from sanequeue.realtime.local_inventory import read_snapshot
            inventory=read_snapshot(os.getenv('SANEQUEUE_LOCAL_INVENTORY','/run/sanequeue/inventory.json'))
            return tuple(sorted({row['endpoint'] for row in (inventory or {}).get('endpoints',[]) if row['category']=='extension' and re.fullmatch(r'\d{1,12}',row['endpoint'])}))
        module.app.config['SANEQUEUE_EXTENSION_PROVIDER']=_discovered_internal_extensions
    module.app.config['SANEQUEUE_TRANSFER_CONTEXT']=os.environ.get('SANEQUEUE_TRANSFER_CONTEXT','from-internal')
    module.app.config['SANEQUEUE_PARKING_LOT']=os.environ.get('SANEQUEUE_PARKING_LOT','default')
    module.app.config['SANEQUEUE_ADVANCED_ACTIONS']=tuple(v.strip() for v in os.environ.get('SANEQUEUE_ADVANCED_ACTIONS','').split(',') if v.strip())
    from sanequeue.security.sessions import SessionRegistry
    module.app.config['SANEQUEUE_AUTH_SESSIONS']=SessionRegistry(STATE/'sessions.sqlite3')
    @module.app.errorhandler(QueueBusy)
    def queue_busy(error):
        return jsonify(error='queue_action_in_progress'),409
    from sanequeue.api.state import StateUnavailable
    @module.app.errorhandler(StateUnavailable)
    def state_unavailable(error):
        return jsonify(error='collector_unavailable'),503
    from sanequeue.alerts.outbox import AlertOutbox
    ACTION_OUTBOX=AlertOutbox(STATE/'alerts.sqlite3')
    from sanequeue.alerts.messaging import NotificationSettings
    NOTIFICATIONS=NotificationSettings(STATE/'notifications.json')
    module.app.config['SANEQUEUE_NOTIFICATIONS']=NOTIFICATIONS
    WORKER_HEALTH={'reconcile_last_ok':None,'reconcile_failures':0,'delivery_failures':0}
    module.app.config['SANEQUEUE_WORKER_HEALTH']=WORKER_HEALTH
    module.app.config['SANEQUEUE_ALERT_PROVIDER']=ACTION_OUTBOX.report
    def bale_enabled():
        return os.getenv('SANEQUEUE_ENABLE_BALE_ALERTS')=='1' and bool(os.getenv('SANEQUEUE_BALE_BOT_TOKEN') and os.getenv('SANEQUEUE_BALE_CHAT_ID'))
    def reconcile_commands():
        while True:
            time.sleep(2)
            try:
                state,health=PERSISTENT_READER.read()
                ACTION_LEDGER.reconcile(state)
                report=POLICIES.evaluate(legacy_queues(state))
                ACTION_OUTBOX.observe(report['alerts'],POLICIES,delivery_enabled=NOTIFICATIONS.enabled() | ({'bale'} if bale_enabled() else set()))
                WORKER_HEALTH['reconcile_last_ok']=time.time()
            except Exception:
                WORKER_HEALTH['reconcile_failures']+=1
                try:ACTION_LEDGER.reconcile({})
                except Exception:pass
    def deliver_notifications():
        from qpanel.queue_policies import send_bale_alert
        while True:
            time.sleep(2)
            if module_disabled():continue
            enabled=NOTIFICATIONS.enabled() | ({'bale'} if bale_enabled() else set())
            if not enabled:continue
            try:
                job=ACTION_OUTBOX.claim(enabled)
                if job is None:continue
                try:
                    if job['provider'] in NOTIFICATIONS.enabled():
                        success=NOTIFICATIONS.send(job['provider'],job['payload'])
                    else:
                        success=send_bale_alert(job['payload'],os.environ['SANEQUEUE_BALE_BOT_TOKEN'],os.environ['SANEQUEUE_BALE_CHAT_ID'])
                except Exception:success=False
                if not success:WORKER_HEALTH['delivery_failures']+=1
                ACTION_OUTBOX.finish(job,success)
            except Exception:
                # No URLs, credentials, chat IDs or caller data in logs.
                WORKER_HEALTH['delivery_failures']+=1
# One process-wide short-lived snapshot for simultaneous dashboards. Not an
# event-driven collector; replace with a persistent AMI listener for production.
LIVE_CACHE = {'signature': None, 'time': 0.0, 'unix': 0.0, 'queues': None}
LIVE_CACHE_SECONDS = 5.0
from qpanel.snapshot_cache import SnapshotCache
SNAPSHOTS = SnapshotCache(ttl=max(5, cfg.interval))

SNAPSHOT_PATH = STATE / 'ami_snapshot.json'
_real_get_data = Backend.get_data_queues.__get__(module.backend, Backend)
module.backend.live_source = 'sample-data'
module.backend.last_error = False


def _default_settings():
    return {
        'host': cfg.get_value_set_default('manager','host','127.0.0.1') if SERVER_MODE else '127.0.0.1',
        'port': 5038,
        'user': cfg.get_value_set_default('manager','user','') if SERVER_MODE else '',
        'queue': '*',
        'visible_queues': '!default',  # Auto monitor all Asterisk queues except the special default queue.
        'enabled': False,
        'updated_at_utc': None,
    }


def _load_settings():
    data = _default_settings()
    if SETTINGS_PATH.exists():
        try:
            stored = json.loads(SETTINGS_PATH.read_text(encoding='utf-8'))
            if isinstance(stored, dict):
                data.update(stored)
        except Exception:
            pass
    try:
        data['port'] = int(data.get('port') or 15038)
    except Exception:
        data['port'] = 15038
    # Redact legacy beta.5 settings only when the file actually contains unsafe keys.
    if SETTINGS_PATH.exists():
        try:
            stored = json.loads(SETTINGS_PATH.read_text(encoding='utf-8'))
            if isinstance(stored, dict) and any(key in stored for key in ('password','save_password','enabled')):
                clean = {k:v for k,v in stored.items() if k not in ('password','save_password','enabled')}
                SETTINGS_PATH.write_text(json.dumps(clean,ensure_ascii=False,indent=2),encoding='utf-8')
        except (ValueError,OSError,TypeError):
            pass
    try:
        data['visible_queues'] = normalize_visible_queues(data.get('visible_queues', '!default'))
    except ValueError:
        data['visible_queues'] = '!default'
    data['enabled'] = AMI_RUNTIME['enabled']
    data['password'] = AMI_RUNTIME['password']
    return data


def _public_settings(data=None):
    data = dict(data or _load_settings())
    password = data.pop('password', '')
    data['has_password'] = bool(password)
    return data



def _save_settings(data):
    previous_visible = _load_settings().get('visible_queues', '!default')
    merged = _default_settings()
    merged.update(data or {})
    merged['visible_queues'] = normalize_visible_queues(merged.get('visible_queues','!default'))
    AMI_RUNTIME['password'] = merged.get('password', '')
    AMI_RUNTIME['enabled'] = bool(merged.get('enabled', False))
    LIVE_CACHE.update(signature=None, time=0.0, unix=0.0, queues=None)
    SNAPSHOTS.invalidate()
    if AMI_RUNTIME['enabled']:
        try:
            JOURNEY_LISTENER.configure(merged, parse_trunk_map(os.getenv('SANEQUEUE_TRUNK_MAP_JSON', '')))
        except (ValueError, TypeError):
            module.app.logger.warning('Call journey listener could not start with selected AMI target')
    else:
        JOURNEY_LISTENER.shutdown()
    if not AMI_RUNTIME['enabled'] or merged['visible_queues'] != previous_visible:
        CONTROL_GATE.disarm()
    merged['updated_at_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    safe = {k:v for k,v in merged.items() if k not in ('password','enabled','save_password')}
    SETTINGS_PATH.write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding='utf-8')
    return merged


def _collect_payload():
    payload = request.get_json(silent=True) or request.form.to_dict() or {}
    stored = _load_settings()
    data = dict(stored)
    for key in ('host', 'user', 'password', 'queue', 'visible_queues'):
        value = payload.get(key)
        if value is not None and value != '':
            data[key] = value
    if payload.get('port') not in (None, ''):
        data['port'] = int(payload.get('port'))
    if 'enabled' in payload:
        data['enabled'] = str(payload.get('enabled')).lower() in ('1', 'true', 'yes', 'on')
    host, port, queue = validate_target(data.get('host'), data.get('port'), data.get('queue'))
    data.update(host=host, port=port, queue=queue)
    data['visible_queues'] = normalize_visible_queues(data.get('visible_queues', '!default'))
    return data


def _summarize(queue_data, queue_requested=''):
    queue_requested = queue_requested or ''
    summary = {
        'checked_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'connected': True,
        'queue_requested': queue_requested,
        'queue_count': len(queue_data),
        'members': 0,
        'member_states': {},
        'waiting_calls': 0,
        'snapshot_complete': True,
        'caller_data': 'masked',
    }
    data = queue_data.get(queue_requested) if queue_requested and queue_requested in queue_data else None
    if data is None and queue_data and queue_requested != '*':
        _, data = next(iter(queue_data.items()))
    selected = list(queue_data.values()) if queue_requested == '*' else ([data] if data else [])
    for queue in selected:
        members = queue.get('members', {})
        summary['members'] += len(members)
        for member in members.values():
            key = f"status_{member.get('Status', '0')}"
            summary['member_states'][key] = summary['member_states'].get(key, 0) + 1
        summary['waiting_calls'] += int(queue.get('Calls', len(queue.get('entries', {}))) or 0)
    return summary


def _write_snapshot(payload):
    SNAPSHOT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def _probe_ami(settings):
    """Socket-level login and QueueStatus probe, independent from dashboard parsing."""
    validate_target(settings['host'], settings['port'], settings.get('queue'))
    client = None
    try:
        client = ReadOnlyAMI(settings['host'], int(settings['port']), timeout=10)
        client.login(settings['user'], settings['password'])
        snapshot = client.queue_snapshot(settings['queue'], timeout=20)
        if not snapshot.get('snapshot_complete') or snapshot.get('queue_count',0) < 1:
            raise RuntimeError('QueueStatus was incomplete or selected queue missing')
        snapshot['checked_at_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        snapshot['stage'] = 'ami-probe'
        _write_snapshot(snapshot)
        return snapshot
    finally:
        if client is not None:
            client.close()


def _diagnostic_error(exc):
    """Return safe errors without exposing AMI credentials or customer data."""
    import socket
    if isinstance(exc, PermissionError): return 'authentication_or_action_denied'
    if isinstance(exc, (socket.timeout, TimeoutError)): return 'connection_timeout'
    if isinstance(exc, ConnectionRefusedError): return 'ssh_tunnel_refused'
    if isinstance(exc, OSError): return 'ssh_tunnel_or_network_error'
    if isinstance(exc, ValueError): return 'invalid_test_scope'
    return 'ami_or_parser_error'


def _test_live(settings, *, persist=True):
    validate_target(settings['host'], settings['port'], settings.get('queue'))
    # Asterisk 20 native read adapter avoids unnecessary UI parser dependencies.
    data = read_queue_data(settings['host'], settings['port'], settings['user'],
                           settings['password'], settings['queue'])
    # Only after a verified read, set in-memory connection fields for staged controls.
    module.backend.host = settings['host']
    module.backend.port = int(settings['port'])
    module.backend.user = settings['user']
    module.backend.password = settings['password']
    module.backend.last_error = False
    # AMI reports all Asterisk queues, but only approved Issabel GUI queues are shown.
    # Raw queues are never mutated on the PBX.
    data = filter_queue_data(data, settings.get('visible_queues', '!default'))
    if not data:
        raise ValueError('no_issabel_queues_matched')
    summary = _summarize(data, settings.get('queue', ''))
    summary['stage'] = 'live-parser'
    if persist:
        _write_snapshot(summary)
    return data, summary


def _runtime_get_data(user=None):
    settings = _load_settings()
    if PERSISTENT_READER is not None:
        try:
            from flask import has_request_context
            fresh=has_request_context() and request.endpoint in ('ops_control','pause_member')
            state, health = PERSISTENT_READER.read(fresh=fresh)
            data = filter_queue_data(legacy_queues(state), settings.get('visible_queues','!default'))
            module.backend.latest_sample_unix = health['published_at']
            module.backend.realtime_health = health
            module.backend.live_source, module.backend.last_error = 'ami-live', False
            from flask import g, has_request_context
            if has_request_context(): g.sanequeue_state_error = False
            return data
        except Exception:
            module.backend.latest_sample_unix = None
            module.backend.live_source, module.backend.last_error = 'collector-stale', True
            from flask import g, has_request_context
            if has_request_context(): g.sanequeue_state_error = True
            return {}
    if settings.get('enabled'):
        try:
            JOURNEY_LISTENER.configure(settings, parse_trunk_map(os.getenv('SANEQUEUE_TRUNK_MAP_JSON','')))
        except (ValueError, TypeError):
            module.app.logger.warning('Call journey listener target invalid')
        signature = (settings['host'],settings['port'],settings['user'],
                     settings['queue'],settings['visible_queues'])
        # Always refresh authorization-relevant data before a mutating action.
        from flask import has_request_context
        fresh_required = (has_request_context() and request.endpoint in
                          ('ops_control','pause_member'))
        try:
            (data, summary), observed = SNAPSHOTS.get(signature, lambda: _test_live(settings, persist=False), fresh=fresh_required)
            module.backend.latest_sample_unix = observed
            module.backend.live_source = 'ami-live'
            module.backend.ami_summary = summary
            module.backend.last_error = False
            return data
        except Exception:
            with AMI_LOCK:
                LIVE_CACHE.update(signature=None, time=0.0, unix=0.0, queues=None)
            module.backend.latest_sample_unix = None
            module.backend.live_source = 'ami-error'
            module.backend.last_error = True
            module.backend.ami_summary = {
                'connected': False,
                'error': 'AMI request failed; current data unavailable',
                'checked_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            }
            return {}  # Never substitute stale/demo data after a live error.
    module.backend.latest_sample_unix = None
    module.backend.live_source = 'disconnected' if SERVER_MODE else 'sample-data'
    module.backend.last_error = SERVER_MODE
    return {} if SERVER_MODE else copy.deepcopy(DATA)


module.backend.get_data_queues = _runtime_get_data


def _conditional_connect():
    if PERSISTENT_READER is not None:
        import configparser
        path = os.environ.get('SANEQUEUE_CONTROL_CONFIG')
        if not path:
            raise PermissionError('separate_control_identity_required')
        control = configparser.ConfigParser(interpolation=None)
        if not control.read(path):
            raise PermissionError('control_configuration_unavailable')
        from qpanel.asterisk import AsteriskAMI
        a = control['ami']
        return AsteriskAMI(a['host'],a.getint('port',5038),a['user'],a['password'])
    if _load_settings().get('enabled'):
        settings=_load_settings()
        from qpanel.asterisk import AsteriskAMI
        return AsteriskAMI(settings['host'], settings['port'], settings['user'], settings['password'])
    manager = MagicMock()
    manager.connection.CoreShowChannels.return_value = [
        dict(Channel='PJSIP/102-000011', ChannelStateDesc='Up', Duration='00:03:41', ConnectedLineNum='02100000004'),
    ]
    manager.connection._translate_response.return_value = {'Response': 'Success'}
    return manager

module.backend._connect = _conditional_connect



def _gate_session_nonce():
    if 'sq_control_nonce' not in session:
        session['sq_control_nonce'] = secrets.token_hex(16)
    return session['sq_control_nonce']


RBAC_CONTROLS=os.getenv('SANEQUEUE_CONTROL_MODE')=='rbac' and PERSISTENT_READER is not None
module.app.config['SANEQUEUE_CONTROL_MODE']='rbac' if RBAC_CONTROLS else 'test-gate'

def _gate_is_active():
    if module_disabled():return False
    if RBAC_CONTROLS:
        return current_user.is_authenticated and cfg.get_value_set_default('roles',current_user.get_id() or '','viewer') in ('admin','supervisor','agent') and AMI_RUNTIME['enabled'] and module.backend.live_source=='ami-live'
    return CONTROL_GATE.active(owner_user=current_user.get_id() or '',
                               owner_session=_gate_session_nonce())


def _gate_remaining():
    if RBAC_CONTROLS:return 0
    return CONTROL_GATE.remaining_seconds(owner_user=current_user.get_id() or '',
                                          owner_session=_gate_session_nonce())


def _test_control_guard(req):
    if RBAC_CONTROLS:return _gate_is_active()
    return CONTROL_GATE.authorize(req.endpoint, req.form.to_dict(),
                                  AMI_RUNTIME['enabled'] and module.backend.live_source == 'ami-live',
                                  bool(AMI_RUNTIME['password']),
                                  owner_user=current_user.get_id() or '',
                                  owner_session=_gate_session_nonce())

@module.app.errorhandler(403)
def descriptive_action_denial(error):
    # Only reveal scoped reason to authenticated callers; no PBX credentials or numbers.
    if request.path in ('/api/control', '/api/members/pause') and current_user.is_authenticated:
        if not _gate_is_active():
            return jsonify(error='control_gate_not_armed_for_current_session'),403
        if not RBAC_CONTROLS and str(request.form.get('queue','')) != CONTROL_GATE.queue:
            return jsonify(error='control_queue_mismatch', armed_queue=CONTROL_GATE.queue),403
        return jsonify(error='action_not_permitted_by_role_or_target'),403
    return error


module.app.config['SANEQUEUE_TEST_CONTROL_GUARD'] = _test_control_guard
module.app.config['SANEQUEUE_TEST_CONTROLS_STATUS'] = _gate_is_active

@module.app.before_request
def _server_landing():
    if SERVER_MODE and request.path in ('/', '/all_queues'):
        from flask import redirect
        return redirect('/operations')

@module.app.before_request
def _secure_local_control_post():
    if request.method != 'POST':
        return
    if PERSISTENT_READER is not None and request.path in ('/api/ami/settings','/api/ami/connect'):
        return jsonify(error='manage_collector_configuration_on_server'),409
    if request.path not in ('/api/ami/settings','/api/ami/test','/api/ami/connect','/api/ami/control-toggle','/api/ami/diagnose','/api/policies'):
        return
    from flask import abort
    from hmac import compare_digest
    origin=request.headers.get('Origin')
    current_port = int(os.environ.get('SANEQUEUE_DEMO_PORT', '18895'))
    if origin and origin.rstrip('/') != request.host_url.rstrip('/'):
        abort(403)
    supplied=request.headers.get('X-CSRF-Token','')
    expected=session.get('csrf_token','')
    if not expected or not compare_digest(supplied,expected):
        abort(403)

@module.app.after_request
def _security_headers(response):
    if request.method == 'POST' and request.endpoint in ('ops_control','pause_member') and response.status_code < 300:
        SNAPSHOTS.invalidate()
    response.headers['X-Frame-Options']='DENY'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Cache-Control']='no-store'
    response.headers['Referrer-Policy']='no-referrer'
    return response

@module.app.before_request
def enforce_authenticated_admin_settings():
    if request.path=='/api/ami/control-status':
        if not current_user.is_authenticated:abort(403)
        return
    if request.path.startswith('/api/ami/') or request.path in ('/api/accounts','/api/pbx/health','/__sanequeue__/ami-snapshot'):
        if not current_user.is_authenticated or cfg.get_value_set_default('roles',current_user.get_id() or '','viewer')!='admin':
            abort(403)

def _validate_account_phone(phone):
    if not phone or PERSISTENT_READER is None:return
    from sanequeue.realtime.local_inventory import read_snapshot
    inventory=read_snapshot(os.getenv('SANEQUEUE_LOCAL_INVENTORY','/run/sanequeue/inventory.json'))
    if inventory is None:raise ValueError('extension_inventory_unavailable')
    valid={row['technology']+'/'+row['endpoint'] for row in inventory.get('endpoints',[]) if row['category']=='extension'}
    if phone not in valid:raise ValueError('select_a_discovered_internal_phone')

@module.app.route('/api/accounts',methods=['GET','POST'])
@login_required
def local_accounts_api():
    if cfg.get_value_set_default('roles', current_user.get_id() or '', 'viewer')!='admin':abort(403)
    if request.method=='GET':
        return jsonify(accounts=public_accounts(ACCOUNTS_PATH))
    from hmac import compare_digest
    if not compare_digest(request.headers.get('X-CSRF-Token',''),session.get('csrf_token','')):
        abort(403)
    if request.content_length and request.content_length>8192:return jsonify(error='payload_too_large'),413
    obj=request.get_json(silent=True) or {}
    try:
        username=str(obj.get('username','')).strip()
        if obj.get('action')=='delete':
            with ACCOUNT_LOCK:
                try:delete_account(ACCOUNTS_PATH,username,current_user.get_id(),lambda:POLICIES.remove_subject(username))
                except ValueError as error:return jsonify(error=str(error)),404 if str(error)=='unknown_user' else 409
                sync_accounts()
                registry=module.app.config.get('SANEQUEUE_AUTH_SESSIONS')
                if registry:registry.revoke_user(username)
        else:
            role=str(obj.get('role','')).strip()
            phone=str(obj.get('phone','')).strip()
            _validate_account_phone(phone)
            set_account(ACCOUNTS_PATH,username,role,phone,obj.get('password') or None)
            sync_accounts()
    except (ValueError,TypeError) as exc:
        return jsonify(error=str(exc)),400
    CONTROL_GATE.disarm()
    return jsonify(ok=True,accounts=public_accounts(ACCOUNTS_PATH))

@module.app.before_request
def block_legacy_call_controls():
    # Retired routes cannot bypass SaneQueue's queue-scoped test gate.
    if request.path in ('/spy','/whisper','/barge','/hangup','/remove_from_queue'):
        abort(403)

@module.app.before_request
def _hide_classic_routes():
    from flask import redirect
    if request.path in ('/', '/all_queues') or request.path.startswith('/queue/'):
        return redirect('/operations', code=302)



@module.app.after_request
def demo_label(response):
    if response.mimetype == 'text/html':
        response.set_data(response.get_data(as_text=True).replace('دید روشن، پاسخ بهتر', 'SaneQueue · پیش‌نمایش حرفه‌ای و عملیات زنده'))
    return response


@module.app.route('/api/policies', methods=['GET', 'POST'])
@login_required
def queue_policies_api():
    # Single-user loopback test app: 'demo' is always admin. Real user auth
    # Local account auth is active; API writes require an admin session.
    if request.method == 'POST':
        if cfg.get_value_set_default('roles', current_user.get_id() or '', 'viewer') != 'admin':
            abort(403)
        payload=request.get_json(silent=True)
        if request.content_length and request.content_length>65536:
            return jsonify(error='policy_too_large'),413
        try:
            visible = _load_settings()['visible_queues']
            allowed = set(filter_queue_data(_runtime_get_data(), visible)) if AMI_RUNTIME['enabled'] else set(parse_visible_queues(visible) or ())
            normalized=POLICIES.replace(payload, visible_queues=allowed)
        except (ValueError,TypeError,KeyError):
            return jsonify(error='invalid_queue_policy'),400
        CONTROL_GATE.disarm()
        return jsonify(ok=True,policies=normalized)
    store=POLICIES.export()
    role = cfg.get_value_set_default('roles', current_user.get_id() or '', 'viewer')
    if role not in ('admin', 'supervisor'):
        abort(403)
    if role != 'admin':
        store['supervisors'] = {current_user.get_id():store['supervisors'].get(current_user.get_id(),{'queues':[],'actions':['view']})}
    visible = _load_settings()['visible_queues']
    allowed=list(filter_queue_data(_runtime_get_data(), visible)) if AMI_RUNTIME['enabled'] else list(parse_visible_queues(visible) or ())
    if role != 'admin':
        allowed=[q for q in allowed if POLICIES.access(current_user.get_id(),role,q)]
    for q in allowed:
        store['queues'].setdefault(q, POLICIES.queue(q))
    return jsonify(policies=store,available_queues=allowed,
                   bale_configured=bool(os.getenv('SANEQUEUE_BALE_BOT_TOKEN') and os.getenv('SANEQUEUE_BALE_CHAT_ID') and os.getenv('SANEQUEUE_ENABLE_BALE_ALERTS')=='1'))



# Diagnostic is independent from Enable Live Data; never changes live controls, AMI state or stored password.
_LAST_DIAG = {'ready':False, 'stages':[], 'error_code':None}

def _run_ami_diagnostic(settings):
    stages=[]
    client=None
    stage='target'
    try:
        validate_target(settings['host'],settings['port'],settings.get('queue','*'))
        stages.append(safe_stage('target',True))
        stage='tcp'
        client=ReadOnlyAMI(settings['host'],int(settings['port']),timeout=10)
        stages.append(safe_stage('tcp',True))
        stage='login'
        client.login(settings['user'],settings['password'])
        stages.append(safe_stage('login',True))
        stage='queue_status'
        snap=client.queue_snapshot(settings.get('queue','*'),timeout=20)
        if not snap.get('snapshot_complete') or snap.get('queue_count',0)<1:
            raise TimeoutError('queue status incomplete')
        stages.append(safe_stage('queue_status',True))
    except Exception as exc:
        code=classify_error(exc,stage)
        stages.append(safe_stage(stage,False,code))
        return {'ready':False,'stages':stages,'error_code':code,'data_source':'unverified'}
    finally:
        if client:
            client.close()
    stage='live_parser'
    try:
        raw=read_queue_data(settings['host'],settings['port'],settings['user'],settings['password'],settings.get('queue','*'))
        stages.append(safe_stage('live_parser',True))
        stage='visibility'
        shown=filter_queue_data(raw,settings.get('visible_queues','!default'))
        if not shown:
            raise ValueError('No currently visible Issabel queue exists')
        stages.append(safe_stage('visibility',True))
        return {'ready':True,'stages':stages,'error_code':None,'data_source':'verified_live_ami',
                'queue_count':len(raw),'displayed_queue_count':len(shown)}
    except Exception as exc:
        code=classify_error(exc,stage)
        stages.append(safe_stage(stage,False,code))
        return {'ready':False,'stages':stages,'error_code':code,'data_source':'unverified'}


@module.app.route('/api/ami/diagnose', methods=['GET','POST'])
def ami_diagnose_api():
    if request.method=='GET':
        return jsonify(_LAST_DIAG)
    try:
        settings=_collect_payload()
    except (ValueError,TypeError):
        result={'ready':False,'stages':[safe_stage('target',False,'invalid_ami_target')],'error_code':'invalid_ami_target'}
        _LAST_DIAG.update(result)
        return jsonify(result)
    if not settings.get('password') or not settings.get('user'):
        result={'ready':False,'stages':[safe_stage('login',False,'missing_credentials')],'error_code':'missing_credentials'}
    else:
        result=_run_ami_diagnostic(settings)
    _LAST_DIAG.clear();_LAST_DIAG.update(result)
    return jsonify(result)

@module.app.route('/api/ami/settings', methods=['GET', 'POST'])
def ami_settings_api():
    if request.method == 'POST':
        try:
            data = _save_settings(_collect_payload())
        except (ValueError, TypeError):
            return jsonify(error='invalid_test_scope'),400
        return jsonify(ok=True, settings=_public_settings(data))
    settings = _public_settings()
    snapshot = None
    if SNAPSHOT_PATH.exists():
        try:
            snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding='utf-8'))
        except Exception:
            snapshot = {'connected': False, 'snapshot_complete': False}
    return jsonify(ok=True, settings=settings, snapshot=snapshot)


@module.app.route('/api/ami/test', methods=['POST'])
def ami_test_api():
    try:
        settings = _collect_payload()
    except (ValueError, TypeError):
        return jsonify(error='invalid_test_scope'), 400
    if not settings.get('host') or not settings.get('user') or not settings.get('password'):
        return jsonify(error='missing_credentials'), 400
    try:
        summary = _probe_ami(settings)
        # Only store safe host/user/queue preferences after a successful probe.
        # Do not modify the existing live/session state or clear the password field.
        return jsonify(ok=True, settings=_public_settings(settings), snapshot=summary, stage='probe')
    except Exception as exc:
        return jsonify(error=_diagnostic_error(exc), stage='probe',
                       snapshot={'connected': False, 'snapshot_complete': False}), 502


@module.app.route('/api/ami/connect', methods=['POST'])
def ami_connect_api():
    try:
        settings = _collect_payload()
    except (ValueError, TypeError):
        return jsonify(error='invalid_test_scope'),400
    action = (request.get_json(silent=True) or request.form.to_dict() or {}).get('action', 'enable')
    if action == 'disable':
        data = _save_settings({**settings, 'enabled': False})
        return jsonify(ok=True, enabled=False, settings=_public_settings(data))
    if not settings.get('host') or not settings.get('user') or not settings.get('password'):
        return jsonify(error='missing_credentials'), 400
    try:
        # Stage one: credentials, tunnel, and queue access work.
        probe = _probe_ami(settings)
    except Exception as exc:
        return jsonify(error=_diagnostic_error(exc), stage='probe',
                       snapshot={'connected': False, 'snapshot_complete': False}), 502
    try:
        # Stage two: native Asterisk 20 adapter provides structured live queue data.
        with AMI_LOCK:
            data, summary = _test_live(settings)
            enabled = _save_settings({**settings, 'enabled': True})
        return jsonify(ok=True, enabled=True, settings=_public_settings(enabled),
                       snapshot=summary, stage='parser', probe=probe)
    except Exception as exc:
        # A failed *new* connection attempt must not silently deactivate an
        # independently verified, already running session. No new settings
        # were saved because commit happens only after the live parser passes.
        return jsonify(error='live_adapter_failed', stage='adapter',
                       diagnostic='no_visible_queues_match' if isinstance(exc,ValueError) else _diagnostic_error(exc), probe=probe), 502



@module.app.route('/api/ami/control-status')
def ami_control_status():
    return jsonify(enabled=_gate_is_active(), remaining_seconds=_gate_remaining(),
                   mode='rbac' if RBAC_CONTROLS else 'test-gate',queue='*' if RBAC_CONTROLS else CONTROL_GATE.queue, allowed_agents=sorted(CONTROL_GATE.agents), supervisor=cfg.get_value_set_default('supervisor_extensions',current_user.get_id() or '',''),
                   live=AMI_RUNTIME['enabled'] and module.backend.live_source == 'ami-live')


module.app.config['SANEQUEUE_CONTROL_STATE']=lambda: dict(enabled=_gate_is_active(),remaining_seconds=_gate_remaining(),mode='rbac' if RBAC_CONTROLS else 'test-gate',queue='*' if RBAC_CONTROLS else CONTROL_GATE.queue,allowed_agents=sorted(CONTROL_GATE.agents))

@module.app.route('/api/ami/control-toggle', methods=['POST'])
def ami_control_toggle():
    if RBAC_CONTROLS:return jsonify(error='controls_managed_by_rbac'),409
    payload=request.get_json(silent=True) or {}
    if payload.get('action')=='disable':
        if _gate_is_active():
            CONTROL_GATE.disarm()
        return ami_control_status()
    if payload.get('action')!='enable':
        return jsonify(error='unknown_action'),400
    selected_queue = str(payload.get('queue') or '').strip()
    if selected_queue == '*' or not selected_queue:
        return jsonify(error='choose_one_test_queue'),400
    if not POLICIES.access(current_user.get_id() or '', cfg.get_value_set_default('roles',current_user.get_id() or '','viewer'),selected_queue,'pause'):
        return jsonify(error='supervisor_scope_denied'),403
    if not is_queue_visible(selected_queue, _load_settings().get('visible_queues', '!default')):
        return jsonify(error='queue_not_in_issabel_allowlist'),403
    try:
        validate_target(_load_settings()['host'], _load_settings()['port'],selected_queue)
        # Refresh QueueStatus for this queue directly before authorizing writes.
        settings=_load_settings()
        if PERSISTENT_READER is not None:
            state,health=PERSISTENT_READER.read(fresh=True)
            selected_data=legacy_queues(state)
        else:
            selected_data=read_queue_data(settings['host'],settings['port'],settings['user'],
                                          settings['password'],selected_queue)
        member_data=selected_data[selected_queue].get('members',{})
        allowed=set(member_data)
        allowed.update(str(m.get('Location') or '') for m in member_data.values())
        allowed.discard('')
        if cfg.get_value_set_default('roles',current_user.get_id() or '', 'viewer') == 'admin':
            allowed.update(account.get('phone','') for account in read_accounts(ACCOUNTS_PATH).values() if account.get('phone'))
        if not allowed:
            return jsonify(error='test_queue_has_no_members'),409
    except (ValueError,KeyError,RuntimeError,PermissionError,OSError,TimeoutError):
        return jsonify(error='test_queue_validation_failed'),409
    # Explicit action scope is computed on the backend from the authenticated
    # user's per-queue policy. No browser-supplied permission set is trusted.
    granted_actions = {
        name for name, permission in (
            ('pause_member', 'pause'), ('add', 'membership'),
            ('remove', 'membership'), ('penalty', 'membership'),
            ('spy', 'monitor'), ('whisper', 'monitor'), ('barge', 'monitor'),
            ('priority', 'priority'), ('first', 'priority'), ('hangup', 'hangup'),
            ('transfer','transfer'),('attended_transfer','transfer'),('cancel_transfer','transfer'),
            ('park','park'),('retrieve','park'),('pickup','pickup'),('dial','dial'),('hangup_active','hangup'))
        if POLICIES.access(current_user.get_id() or '',
                           cfg.get_value_set_default('roles', current_user.get_id() or '', 'viewer'),
                           selected_queue, permission)
    }
    if not CONTROL_GATE.arm(payload.get('confirmation',''),
                            AMI_RUNTIME['enabled'] and module.backend.live_source=='ami-live',
                            bool(AMI_RUNTIME['password']), queue=selected_queue, agents=allowed,
                            owner_user=current_user.get_id() or '',
                            owner_session=_gate_session_nonce(),
                            allowed_actions=granted_actions):
        return jsonify(error='controls_require_live_connection_and_confirmation'),403
    return ami_control_status()




HEALTH_CACHES = {}
HEALTH_CACHE_LOCK = threading.Lock()

@module.app.route('/api/pbx/health', methods=['GET'])
def pbx_health():
    """On-demand and read-only; no fake PBX data and no exposed caller IDs."""
    kind = request.args.get('kind','channels')
    if kind not in ('channels','extensions','trunks','parking','contacts','registrations','permissions'):
        return jsonify(error='unsupported_action'), 400
    if kind in ('extensions','trunks'):
        from sanequeue.realtime.local_inventory import read_snapshot,projection
        inventory=read_snapshot(os.getenv('SANEQUEUE_LOCAL_INVENTORY','/run/sanequeue/inventory.json'))
        if inventory is not None:
            return jsonify(projection(inventory,'extension' if kind=='extensions' else 'trunk'))
        if kind=='trunks':return jsonify(kind=kind,supported=False,reason='local_inventory_unavailable'),503
    if PERSISTENT_READER is not None:
        from sanequeue.api.state import StateUnavailable
        from sanequeue.realtime.inventory import inventory_projection
        try:
            state, _ = PERSISTENT_READER.read()
            return jsonify(inventory_projection(state,kind))
        except StateUnavailable:
            return jsonify(error='collector_unavailable',supported=False),503
    settings = _load_settings()
    if not AMI_RUNTIME['enabled'] or not settings.get('password'):
        return jsonify(error='live_ami_required', supported=False), 409
    from qpanel.ami_health import read_health, read_capabilities
    kind = request.args.get('kind','channels')
    if kind not in ('channels','extensions','parking','contacts','registrations','permissions'):
        return jsonify(error='unsupported_action'), 400
    try:
        if kind == 'permissions':
            collector = lambda: read_capabilities(settings['host'],settings['port'],settings['user'],settings['password'],settings['queue'])
        else:
            def collector():
                result = read_health(settings['host'],settings['port'],settings['user'],settings['password'],settings['queue'],kind)
                if kind in ('extensions','registrations'):
                    legacy = read_health(settings['host'],settings['port'],settings['user'],settings['password'],settings['queue'],'sip_'+kind)
                    if legacy.get('supported'):
                        if not result.get('supported'): return dict(legacy,kind=kind)
                        if kind=='extensions':
                            result['data']['endpoints'] += legacy['data']['endpoints']
                        for field in ('total','available','registrations','registered','unregistered'):
                            if field in legacy.get('data',{}): result['data'][field]=result['data'].get(field,0)+legacy['data'][field]
                return result
        with HEALTH_CACHE_LOCK:
            cache=HEALTH_CACHES.setdefault(kind,SnapshotCache(ttl=30))
        key=(settings['host'],settings['port'],settings['user'],settings['password'])
        result, observed = cache.get(key,collector)
        return jsonify(dict(result,observed_at=observed))
    except Exception as exc:
        return jsonify(error=_diagnostic_error(exc), supported=False), 502

@module.app.route('/__sanequeue__/build')
def _sanequeue_build():
    from qpanel import __version__
    settings = _load_settings()
    result = jsonify({
        'application': 'SaneQueue',
        'version': __version__,
        'mode': 'test-stage' ,
        'fake_data': not settings.get('enabled'),
        'live_data_enabled': settings.get('enabled', False),
        'data_source': getattr(module.backend, 'live_source', 'sample-data'),
        'controls_locked': not _gate_is_active(), 'control_seconds_left': _gate_remaining()
    })
    result.headers['Cache-Control'] = 'no-store'
    return result


@module.app.after_request
def _no_cache_demo(response):
    if response.mimetype == 'text/html':
        response.headers['Cache-Control'] = 'no-store, max-age=0'
    return response


@module.app.route('/__sanequeue__/ami-snapshot')
def _sanequeue_ami_snapshot():
    if not SNAPSHOT_PATH.exists():
        response = jsonify({
            'source': 'local AMI diagnostic',
            'status': 'not-run',
            'message': 'Run a test from the AMI settings panel',
            'demo_ui_fake_data': True
        })
    else:
        try:
            data = json.loads(SNAPSHOT_PATH.read_text(encoding='utf-8'))
            response = jsonify({
                'source': 'local AMI diagnostic',
                'status': 'snapshot',
                'demo_ui_fake_data': not _load_settings().get('enabled', False),
                **data
            })
        except Exception:
            response = jsonify({'source': 'local AMI diagnostic', 'status': 'snapshot-error'}), 503
            return response
    response.headers['Cache-Control'] = 'no-store'
    return response


def _background_alert_loop():
    """Optional best-effort in-process polling; no outbound sends without explicit opt-in."""
    from qpanel.queue_policies import send_bale_alert
    while True:
        time.sleep(30)
        if not AMI_RUNTIME['enabled']:
            continue
        if not (os.getenv('SANEQUEUE_BALE_BOT_TOKEN') and os.getenv('SANEQUEUE_BALE_CHAT_ID')):
            continue
        try:
            with AMI_LOCK:
                live_data = _runtime_get_data()
            if module.backend.last_error:
                continue
            report = POLICIES.evaluate(live_data)
            for alert in report['notify'][:10]:
                try:
                    sent = send_bale_alert(alert, os.getenv('SANEQUEUE_BALE_BOT_TOKEN'),
                                           os.getenv('SANEQUEUE_BALE_CHAT_ID'))
                    POLICIES.note_delivery(sent, '' if sent else 'bale_declined')
                except Exception:
                    POLICIES.note_delivery(False, 'delivery_failed')
        except Exception:
            # Never send AMI credentials, contact numbers or bot tokens to logs.
            module.app.logger.warning('Alert worker check failed; check AMI connectivity')


@module.app.route('/api/accounts/with-grants', methods=['POST'])
@login_required
def accounts_and_grants_api():
    """Single save button for local beta users, phone and queue/action RBAC.

    Refuses to save a partial account when a queue policy fails. App is
    loopback-only and cannot provide distributed atomicity across processes.
    """
    from hmac import compare_digest
    from qpanel.account_grants import save_account_with_grants
    if cfg.get_value_set_default('roles',current_user.get_id() or '', 'viewer') != 'admin':
        abort(403)
    if not session.get('csrf_token') or not compare_digest(
            request.headers.get('X-CSRF-Token',''),session['csrf_token']):
        abort(403)
    if request.content_length and request.content_length > 16384:
        return jsonify(error='payload_too_large'),413
    obj=request.get_json(silent=True)
    try:
        if not isinstance(obj, dict):
            return jsonify(error='invalid_payload'),400
        if obj.get('username')==current_user.get_id() and obj.get('role')=='admin' and obj.get('menus') is not None and not {'users','settings'}.issubset(set(obj['menus'])):
            return jsonify(error='keep_own_users_and_settings_access'),400
        _validate_account_phone(str(obj.get('phone','')).strip())
        visible=_load_settings()['visible_queues']
        scope=set(filter_queue_data(_runtime_get_data(),visible)) if AMI_RUNTIME['enabled'] else set(parse_visible_queues(visible) or ())
        result=save_account_with_grants(ACCOUNTS_PATH,POLICIES,scope,obj)
        sync_accounts()
        CONTROL_GATE.disarm()
        return jsonify(ok=True,**result)
    except (ValueError,TypeError,KeyError) as exc:
        return jsonify(error=str(exc)),400

@module.app.route('/api/runtime/metrics')
@login_required
def runtime_metrics():
    if cfg.get_value_set_default('roles',current_user.get_id() or '', 'viewer') != 'admin':abort(403)
    if PERSISTENT_READER is not None:
        try:
            state, health = PERSISTENT_READER.read()
            return jsonify(collector=health, redis_reads=PERSISTENT_READER.reads,
                           snapshot_collections=0, cache_seconds=PERSISTENT_READER.cache_seconds,
                           websocket_enabled=True, single_worker_required=True, workers=WORKER_HEALTH)
        except Exception:
            return jsonify(error='collector_unavailable'),503
    return jsonify(snapshot_collections=SNAPSHOTS.collections,cache_seconds=SNAPSHOTS.ttl,
                   consecutive_failures=SNAPSHOTS.failures,
                   retry_after_seconds=max(0,round(SNAPSHOTS.retry_at-time.monotonic(),1)),
                   health_cache_seconds=30,single_worker_required=True)

from qpanel.planning import PlanningStore
PLANNING = PlanningStore(STATE / 'planning.sqlite3')

@module.app.route('/api/planning/<kind>', methods=['GET','POST'])
@login_required
def planning_api(kind):
    if kind not in ('shifts','directory'): abort(404)
    role=cfg.get_value_set_default('roles',current_user.get_id() or '', 'viewer')
    data=_runtime_get_data()
    allowed=POLICIES.visible(current_user.get_id() or '',role,data)
    if request.method=='POST':
        from hmac import compare_digest
        if role not in ('admin','supervisor'):abort(403)
        if not session.get('csrf_token') or not compare_digest(request.headers.get('X-CSRF-Token',''),session['csrf_token']):abort(403)
        obj=request.get_json(silent=True)
        try:
            PLANNING.save(kind,obj,allowed)
        except PermissionError:return jsonify(error='queue_not_allowed'),403
        except (ValueError,TypeError) as exc:return jsonify(error=str(exc)),400
        module.app.logger.info('planning user=%r kind=%s queue=%r',current_user.get_id(),kind,obj.get('queue'))
    rows=PLANNING.list(kind,allowed)
    if role not in ('admin','supervisor'):
        if kind=='directory':
            from qpanel.privacy import mask_phone
            for row in rows:row['phone']=mask_phone(row['phone'])
        else:rows=[row for row in rows if row['agent']==current_user.get_id()]
    return jsonify(rows=rows,queues=list(allowed),editable=role in ('admin','supervisor'))

if PERSISTENT_READER is not None and SERVER_MODE:
    threading.Thread(target=reconcile_commands,name='command-alert-reconcile',daemon=True).start()
    threading.Thread(target=deliver_notifications,name='alert-delivery',daemon=True).start()
elif os.getenv('SANEQUEUE_ENABLE_BALE_ALERTS') == '1':
    threading.Thread(target=_background_alert_loop, name='sanequeue-bale-alerts', daemon=True).start()


from qpanel import __version__
port = int(os.environ.get('SANEQUEUE_DEMO_PORT', '18895'))
if not (1024 <= port <= 65535):
    raise SystemExit('Invalid demo port')
print('SaneQueue BUILD:', __version__, '| server' if SERVER_MODE else '| local preview', '| controls locked', flush=True)
print('Open http://127.0.0.1:%d/operations' % port, flush=True)
print('Build info: http://127.0.0.1:%d/__sanequeue__/build' % port, flush=True)
if __name__ == '__main__':
    module.app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False, threaded=True)

