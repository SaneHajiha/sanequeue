"""Versioned inbound notices. Saving never changes a PBX route.

Bindings are an operator-owned allowlist; the web user cannot supply dialplan.
FastAGI consumes only the root-published snapshot, never this web store.
"""
from contextlib import contextmanager
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile
import threading
import time
import wave

from flask import abort, jsonify, request, send_file
from flask_login import current_user, login_required

IDENT = re.compile(r'[A-Za-z0-9_-]{1,64}\Z')
HASH = re.compile(r'[a-f0-9]{64}\Z')
MAX_NOTICE_SECONDS = 7 * 86400
PUBLICATION_LOCK = threading.RLock()


def bindings(path='/etc/sanequeue/incident-bindings.json', *, require_root=True):
    """Missing/unsafe registry means no supported hook, never wildcard scope."""
    path = Path(path)
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(fd, 'rb') as stream:
            meta = os.fstat(stream.fileno())
            if not stat.S_ISREG(meta.st_mode) or meta.st_size > 32768 or meta.st_nlink != 1:
                return {}
            if os.name != 'nt' and require_root and (meta.st_uid != 0 or meta.st_mode & 0o022):
                return {}
            value = json.loads(stream.read(32769))
        if not isinstance(value, dict) or len(value) > 64:
            return {}
        result = {}
        for key, row in value.items():
            if not IDENT.fullmatch(key) or not isinstance(row, dict):return {}
            context, queue = row.get('context'), row.get('queue')
            if not isinstance(context, str) or not IDENT.fullmatch(context):return {}
            if not isinstance(queue, str) or not IDENT.fullmatch(queue):return {}
            label = row.get('label', key)
            if not isinstance(label, str) or not 1 <= len(label) <= 100 or not label.isprintable():return {}
            result[key] = dict(context=context, queue=queue, label=label)
        return result
    except (OSError, ValueError, TypeError):
        return {}


def validate_notice(value, allowed):
    if not isinstance(value, dict):raise ValueError('invalid_notice')
    binding = value.get('binding')
    if not isinstance(binding, str) or binding not in allowed:raise ValueError('unsupported_notice_binding')
    enabled = value.get('enabled')
    if not isinstance(enabled, bool):raise ValueError('invalid_notice_enabled')
    title = value.get('title', '')
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 100 or not title.isprintable():raise ValueError('invalid_notice_title')
    audio = value.get('audio', '')
    if not isinstance(audio, str) or not HASH.fullmatch(audio):raise ValueError('notice_audio_required')
    start, end = value.get('starts_at'), value.get('expires_at')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (start, end)):
        raise ValueError('invalid_notice_period')
    if not 0 <= start < end <= 32503680000 or end - start > MAX_NOTICE_SECONDS:raise ValueError('notice_period_max_7_days')
    return dict(binding=binding, enabled=enabled, title=title.strip(), audio=audio, starts_at=start, expires_at=end)


class IncidentStore:
    def __init__(self, state):
        self.state = Path(state)
        self.path = self.state / 'incident-notices.sqlite3'
        self.sounds = self.state / 'incident-sounds'

    @contextmanager
    def db(self):
        if self.state.is_symlink() or self.path.is_symlink():raise ValueError('invalid_notice_store')
        self.state.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=2)
        db.row_factory = sqlite3.Row
        if os.name != 'nt':os.chmod(self.path, 0o600)
        try:
            with db:
                db.execute('CREATE TABLE IF NOT EXISTS notices (revision INTEGER PRIMARY KEY AUTOINCREMENT, binding TEXT NOT NULL, payload TEXT NOT NULL, actor TEXT NOT NULL, created_at REAL NOT NULL)')
                db.execute('CREATE INDEX IF NOT EXISTS notices_binding ON notices(binding, revision)')
                yield db
        finally:db.close()

    def current(self, *, read_only=False, allowed=None):
        if read_only:
            # The privileged publisher must never initialize/mutate a web-owned DB.
            if self.state.is_symlink() or self.path.is_symlink() or not self.path.is_file() or self.path.stat().st_size > 16*1024*1024:
                raise ValueError('invalid_notice_store')
            db = sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro', uri=True, timeout=1)
            db.row_factory = sqlite3.Row
            deadline = time.monotonic()+.25
            db.set_progress_handler(lambda: int(time.monotonic()>deadline), 1000)
            db.execute('PRAGMA trusted_schema=OFF')
            try:return self._current(db,allowed)
            finally:db.close()
        with self.db() as db:return self._current(db,allowed)

    @staticmethod
    def _current(db,allowed):
        if allowed is not None and not allowed:return []
        where=' WHERE binding IN ('+','.join('?' for _ in allowed)+')' if allowed is not None else ''
        rows = db.execute('SELECT n.* FROM notices n JOIN (SELECT binding, MAX(revision) AS revision FROM notices'+where+' GROUP BY binding) c ON n.revision=c.revision ORDER BY n.revision DESC LIMIT 64',tuple(allowed or ())).fetchall()
        return [dict(json.loads(r['payload']), revision=r['revision'], actor=r['actor'], created_at=r['created_at']) for r in rows]

    def save(self, value, allowed, actor):
        notice = validate_notice(value, allowed)
        expected = value.get('expected_revision')
        if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:raise ValueError('notice_revision_required')
        self.audio(notice['audio'])
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            latest = db.execute('SELECT MAX(revision) FROM notices WHERE binding=?', (notice['binding'],)).fetchone()[0] or 0
            if expected != latest:raise ValueError('notice_changed_reload')
            if db.execute('SELECT COUNT(*) FROM notices').fetchone()[0] >= 10000:raise ValueError('notice_history_capacity')
            cur = db.execute('INSERT INTO notices(binding,payload,actor,created_at) VALUES (?,?,?,?)',
                (notice['binding'], json.dumps(notice), str(actor)[:100], time.time()))
            return dict(notice, revision=cur.lastrowid)

    def audio(self, ident):
        if not isinstance(ident, str) or not HASH.fullmatch(ident):raise ValueError('invalid_notice_audio')
        path = self.sounds / (ident + '.wav')
        if self.sounds.is_symlink() or path.is_symlink():raise ValueError('invalid_notice_audio')
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
            with os.fdopen(fd, 'rb') as stream:
                meta = os.fstat(stream.fileno())
                if not stat.S_ISREG(meta.st_mode) or meta.st_size > 1100000 or meta.st_nlink != 1:raise ValueError('invalid_notice_audio')
                content = stream.read(1100001)
            if hashlib.sha256(content).hexdigest() != ident:raise ValueError('notice_audio_hash_mismatch')
            with wave.open(io.BytesIO(content), 'rb') as sound:
                if (sound.getnchannels(), sound.getsampwidth(), sound.getframerate(), sound.getcomptype()) != (1, 2, 8000, 'NONE') or not 0 < sound.getnframes() <= 480000:
                    raise ValueError('invalid_notice_audio')
            return path, content
        except (OSError, EOFError, wave.Error):raise ValueError('notice_audio_unavailable') from None

    def upload(self, content):
        from .features import CONVERSION, convert_audio
        if not CONVERSION.acquire(blocking=False):raise ValueError('audio_conversion_busy')
        try:audio, seconds = convert_audio(content)
        finally:CONVERSION.release()
        ident = hashlib.sha256(audio).hexdigest()
        if self.sounds.is_symlink():raise ValueError('invalid_notice_audio_directory')
        self.sounds.mkdir(parents=True, mode=0o750, exist_ok=True)
        with PUBLICATION_LOCK:
            target=self.sounds/(ident+'.wav')
            if len(list(self.sounds.glob('*.wav'))) >= 30 and not target.exists():raise ValueError('notice_audio_capacity')
            fd,name=tempfile.mkstemp(prefix='.notice-',dir=self.sounds)
            try:
                with os.fdopen(fd,'wb') as stream:stream.write(audio);stream.flush();os.fsync(stream.fileno())
                if os.name!='nt':os.chmod(name,0o640)
                # Publish only complete bytes, without replacing an existing file.
                try:os.link(name,target)
                except FileExistsError:self.audio(ident)
            finally:os.unlink(name)
        return dict(audio=ident, seconds=seconds)


def snapshot(store, allowed):
    """Root helper input; excludes unsupported bindings and verifies audio bytes."""
    rows = {}
    try:current=store.current(read_only=True,allowed=allowed)
    except (OSError, ValueError, sqlite3.Error):return {}
    for row in current:
        try:
            value = validate_notice(row, allowed)
            store.audio(value['audio'])
        except ValueError:continue
        rows[value['binding']] = dict(value, revision=row['revision'], **allowed[value['binding']])
    return rows


def select_notice(config, binding, context, queue, now):
    """Exact hook identity only; any malformed snapshot falls back to no notice."""
    try:
        row = config.get('incidents', {}).get(binding)
        if not isinstance(row, dict) or row.get('context') != context or row.get('queue') != queue:return None
        value = validate_notice(row, {binding: row})
        if not value['enabled'] or not value['starts_at'] <= now < value['expires_at']:return None
        revision = row.get('revision')
        if isinstance(revision, bool) or not isinstance(revision, int) or revision <= 0:return None
        return dict(audio='custom/sanequeue/' + value['audio'], revision=revision)
    except (ValueError, TypeError):return None


def dialplan(token):
    """A subroutine only. Operators must add an explicit reviewed Gosub hook.

    ARG1=binding, ARG2=original context, ARG3=queue. No Goto/Dial/Hangup.
    Playback uses noanswer so the notice never answers a ringing call itself.
    """
    if not isinstance(token, str) or not HASH.fullmatch(token):raise ValueError('invalid_adapter_token')
    return '''
[sanequeue-inbound-notice]
exten => s,1,Set(SQ_NOTICE_ENABLED=0)
 same => n,Set(SQ_NOTICE_AUDIO=)
 same => n,GotoIf($[${STAT(e,/var/spool/asterisk/sanequeue/disabled)}=1]?done)
 same => n,AGI(agi://127.0.0.1:19051/TOKEN/incident,${ARG1},${ARG2},${ARG3})
 same => n,GotoIf($["${SQ_NOTICE_ENABLED}"!="1"]?done)
 same => n,TryExec(Playback(${SQ_NOTICE_AUDIO},noanswer))
 same => n(done),Return()
'''.replace('TOKEN', token)


def install(app, state, role, admin, csrf):
    store = IncidentStore(state)
    registry = lambda: bindings(app.config.get('SANEQUEUE_INCIDENT_BINDINGS', '/etc/sanequeue/incident-bindings.json'))
    @app.before_request
    def notice_upload_limit():
        if request.path == '/api/pbx/incidents/audio':request.max_content_length = 8 * 1024 * 1024 + 65536

    @app.route('/api/pbx/incidents', methods=['GET', 'POST'])
    @login_required
    def incident_notices():
        admin()
        allowed = registry()
        if request.method == 'POST':
            csrf()
            if (request.content_length or 0) > 16384:return jsonify(error='payload_too_large'), 413
            try:store.save(request.get_json(silent=True), allowed, current_user.get_id())
            except ValueError as error:return jsonify(error=str(error)), 409 if str(error) == 'notice_changed_reload' else 400
        response = jsonify(bindings=allowed, notices=store.current(allowed=allowed), integration='explicit_dialplan_hook_required', max_period_seconds=MAX_NOTICE_SECONDS)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.route('/api/pbx/incidents/audio', methods=['POST'])
    @login_required
    def incident_upload():
        admin();csrf()
        if not registry():return jsonify(error='no_supported_notice_bindings'), 409
        uploaded = request.files.get('audio')
        if not uploaded:return jsonify(error='audio_required'), 400
        try:return jsonify(store.upload(uploaded.read(8 * 1024 * 1024 + 1)))
        except ImportError:return jsonify(error='audio_dependency_unavailable'), 503
        except ValueError as error:return jsonify(error=str(error)), 400

    @app.route('/api/pbx/incidents/audio/<ident>')
    @login_required
    def incident_audio(ident):
        admin()
        try:_, content = store.audio(ident)
        except ValueError:abort(404)
        response = send_file(io.BytesIO(content), mimetype='audio/wav', conditional=False)
        response.headers['Cache-Control'] = 'no-store'
        return response
