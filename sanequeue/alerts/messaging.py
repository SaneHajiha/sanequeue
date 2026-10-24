"""Private notification configuration and bounded Telegram/Bale transport."""
import json
import os
import re
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

PROVIDERS = {'telegram': 'https://api.telegram.org', 'bale': 'https://tapi.bale.ai'}
TOKEN = re.compile(r'\d{5,20}:[A-Za-z0-9_-]{20,120}\Z')
CHAT = re.compile(r'-?\d{1,22}\Z')


class MessagingError(Exception):
    """Only stable, non-sensitive error codes leave the transport."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise MessagingError('redirect_refused')


def call(provider, token, method, payload, *, timeout=5):
    if provider not in PROVIDERS or not TOKEN.fullmatch(str(token)):
        raise MessagingError('invalid_configuration')
    if method not in ('sendMessage', 'getMe', 'getUpdates', 'getWebhookInfo'):
        raise MessagingError('method_forbidden')
    request = urllib.request.Request(
        PROVIDERS[provider] + '/bot' + token + '/' + method,
        json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=timeout) as response:
            data = response.read(131073)
            if len(data) > 131072:
                raise MessagingError('response_too_large')
            result = json.loads(data)
            if not isinstance(result, dict) or result.get('ok') is not True:
                raise MessagingError('provider_rejected')
            return result.get('result')
    except MessagingError:
        raise
    except Exception:
        # HTTPError includes the credential-bearing URL. Never expose its text.
        raise MessagingError('provider_unavailable') from None


def alert_text(alert):
    # Fixed projection: no caller IDs, channels, URLs, or arbitrary message body.
    labels = {'waiting_count': 'Waiting callers', 'waiting_time': 'Longest wait (s)',
              'ready_below': 'Available agents'}
    kind = labels.get(alert.get('type'), 'Queue threshold')
    label = str(alert.get('label') or alert.get('queue', ''))[:65]
    label = ''.join(c for c in label if c.isprintable())
    return f"SaneQueue | {label}\n{kind}: {float(alert['value']):g} (threshold {float(alert['threshold']):g})"


class NotificationSettings:
    """One-process atomic, owner-only storage; never return stored tokens."""
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()

    def _read(self):
        if not self.path.exists():
            return {}
        with self.path.open(encoding='utf-8') as stream:
            return json.load(stream)

    def public(self):
        with self.lock:
            config = self._read()
            return {p: {'enabled': config.get(p, {}).get('enabled') is True,
                        'configured': bool(config.get(p, {}).get('token') and config.get(p, {}).get('chat_id')),
                        'chat_id': config.get(p, {}).get('chat_id', '')} for p in PROVIDERS}

    def replace(self, payload):
        if not isinstance(payload, dict) or any(p not in PROVIDERS for p in payload):
            raise ValueError('invalid_notification_settings')
        with self.lock:
            config = self._read()
            for provider, value in payload.items():
                if not isinstance(value, dict) or not isinstance(value.get('enabled', False), bool):
                    raise ValueError('invalid_notification_settings')
                old = config.get(provider, {})
                token = value.get('token') or old.get('token', '')
                chat = str(value.get('chat_id', old.get('chat_id', ''))).strip()
                enabled = value.get('enabled', False)
                if (token and not TOKEN.fullmatch(str(token))) or (chat and not CHAT.fullmatch(chat)):
                    raise ValueError('invalid_notification_settings')
                if enabled and not (token and chat):
                    raise ValueError('notification_configuration_required')
                config[provider] = dict(token=token, chat_id=chat, enabled=enabled)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix='.notifications-', dir=self.path.parent)
            try:
                with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                    json.dump(config, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return self.public()

    def enabled(self):
        return {p for p, value in self.public().items() if value['enabled'] and value['configured']}

    def send(self, provider, alert=None, *, test=False):
        with self.lock:
            value = self._read().get(provider, {})
        if provider not in PROVIDERS or not value.get('enabled') or not value.get('chat_id'):
            raise MessagingError('provider_disabled')
        text = 'SaneQueue | Notification connection test. No caller information included.' if test else alert_text(alert)
        result = call(provider, value.get('token', ''), 'sendMessage', {'chat_id': value['chat_id'], 'text': text})
        return isinstance(result, dict) and 'message_id' in result
