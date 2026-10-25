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


def alert_text(alert, language='fa'):
    # Fixed projection: no caller IDs, channels, URLs, or arbitrary message body.
    labels = {'waiting_count': ('تعداد منتظرها','Waiting callers'), 'waiting_time': ('بیشترین انتظار (ثانیه)','Longest wait (s)'),
              'ready_below': ('کارشناسان آماده','Available agents'), 'trunk_down':('ترانک از دسترس خارج است','Trunk unavailable'),
              'monitoring_unavailable':('ارتباط مانیتورینگ قطع است','Monitoring connection unavailable'),
              'inventory_stale':('اطلاعات سلامت به‌روز نیست','Health inventory is stale'),
              'disk_critical':('فضای دیسک بحرانی است','Disk space critical')}
    pair=labels.get(alert.get('type'),('هشدار صف','Queue threshold'))
    label = str(alert.get('label') or alert.get('queue', ''))[:65]
    label = ''.join(c for c in label if c.isprintable())
    fa_label={'AMI / Collector':'ارتباط زنده مرکز تلفن','PBX inventory':'اطلاعات سلامت مرکز تلفن','PBX disk':'دیسک سرور'}.get(label,label)
    fa=f"SaneQueue | {fa_label}\n{pair[0]}: {float(alert['value']):g} · آستانه: {float(alert['threshold']):g}"
    en=f"SaneQueue | {label}\n{pair[1]}: {float(alert['value']):g} · threshold: {float(alert['threshold']):g}"
    return fa+'\n\n'+en if language=='both' else en if language=='en' else fa


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
                        'chat_id': config.get(p, {}).get('chat_id', ''),
                        'language':config.get(p,{}).get('language','fa')} for p in PROVIDERS}

    def system_rules(self):
        with self.lock:return clean_system_rules(self._read().get('system',{}))

    def replace(self, payload):
        if not isinstance(payload, dict) or any(p not in (*PROVIDERS,'system') for p in payload):
            raise ValueError('invalid_notification_settings')
        with self.lock:
            config = self._read()
            if 'system' in payload:config['system']=clean_system_rules(payload['system'])
            for provider, value in payload.items():
                if provider=='system':continue
                if not isinstance(value, dict) or not isinstance(value.get('enabled', False), bool):
                    raise ValueError('invalid_notification_settings')
                old = config.get(provider, {})
                token = value.get('token') or old.get('token', '')
                chat = str(value.get('chat_id', old.get('chat_id', ''))).strip()
                enabled = value.get('enabled', False)
                language=value.get('language',old.get('language','fa'))
                if language not in ('fa','en','both'):raise ValueError('invalid_notification_language')
                if (token and not TOKEN.fullmatch(str(token))) or (chat and not CHAT.fullmatch(chat)):
                    raise ValueError('invalid_notification_settings')
                if enabled and not (token and chat):
                    raise ValueError('notification_configuration_required')
                config[provider] = dict(token=token, chat_id=chat, enabled=enabled,language=language)
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

    def destinations(self,provider,token=''):
        if provider not in PROVIDERS:raise MessagingError('invalid_configuration')
        with self.lock:secret=token or self._read().get(provider,{}).get('token','')
        info=call(provider,secret,'getWebhookInfo',{})
        if isinstance(info,dict) and info.get('url'):raise MessagingError('webhook_active_use_manual_chat_id')
        updates=call(provider,secret,'getUpdates',{'limit':20,'timeout':0,'allowed_updates':['message','channel_post']})
        found={}
        for update in updates if isinstance(updates,list) else []:
            message=update.get('message') or update.get('channel_post') or {}
            chat=message.get('chat',{});ident=str(chat.get('id',''))
            if CHAT.fullmatch(ident):found[ident]=dict(id=ident,title=str(chat.get('title') or chat.get('first_name') or chat.get('type','chat'))[:80])
        return list(found.values())[:20]

    def send(self, provider, alert=None, *, test=False):
        with self.lock:
            value = self._read().get(provider, {})
        if provider not in PROVIDERS or not value.get('enabled') or not value.get('chat_id'):
            raise MessagingError('provider_disabled')
        language=value.get('language','fa')
        messages={'fa':'SaneQueue | آزمون اتصال هشدار؛ اطلاعات تماس‌گیرنده ارسال نشده است.', 'en':'SaneQueue | Notification connection test. No caller information included.'}
        text=(messages['fa']+'\n\n'+messages['en'] if language=='both' else messages.get(language,messages['fa'])) if test else alert_text(alert,language)
        result = call(provider, value.get('token', ''), 'sendMessage', {'chat_id': value['chat_id'], 'text': text})
        return isinstance(result, dict) and 'message_id' in result


def clean_system_rules(value):
    if not isinstance(value,dict):raise ValueError('invalid_system_rules')
    result={key:value.get(key,True) for key in ('trunk_down','monitoring_unavailable','inventory_stale','disk_critical','telegram_enabled','bale_enabled')}
    if any(not isinstance(v,bool) for v in result.values()):raise ValueError('invalid_system_switch')
    for key,default,lo,hi in (('debounce_seconds',10,5,120),('cooldown_seconds',300,60,86400),('disk_used_percent',95,80,99)):
        n=value.get(key,default)
        if isinstance(n,bool) or not isinstance(n,int) or not lo<=n<=hi:raise ValueError('invalid_system_threshold')
        result[key]=n
    return result
