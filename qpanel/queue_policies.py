"""Scoped SaneQueue operations policy for a single local beta app.

No AMI secrets or caller numbers are stored here. This is NOT a replacement
for independent PBX access control and a real authenticated user directory.
"""
from copy import deepcopy
from pathlib import Path
from threading import RLock
import json
import math
import os
import re
import time
import urllib.request

QUEUE_ID = re.compile(r'^[A-Za-z0-9_-]{1,32}$')
USER_ID = re.compile(r'^[A-Za-z0-9_.@-]{1,70}$')
REASON_ID = re.compile(r'^[a-z][a-z0-9_-]{0,31}$')
ALLOWED_GRANTS = frozenset({'view', 'pause', 'membership', 'monitor', 'hangup', 'priority', 'caller_details','transfer','park','pickup','dial'})
DEFAULT_REASONS = [
    {'id':'break', 'label':'استراحت'},
    {'id':'lunch', 'label':'ناهار'},
    {'id':'training', 'label':'آموزش'},
    {'id':'meeting', 'label':'جلسه'},
    {'id':'after_call', 'label':'کار پس از تماس'},
    {'id':'follow_up', 'label':'پیگیری تلفنی مشتری'},
    {'id':'manual_calls', 'label':'تماس خروجی با فهرست مشتریان'},
    {'id':'technical', 'label':'مشکل فنی'},
]
DEFAULT_QUEUE = {
  'label':'',
  'directory_external_dialing':False,
  'alerts':{'waiting_above':5, 'wait_seconds_above':300, 'min_ready':0,'cooldown_seconds':300,'bale_enabled':False,'telegram_enabled':False,'count_enabled':True,'time_enabled':True,'match_mode':'any'},
  'staffing':{'enabled':False,'roster_size':0,'max_absent_percent':50,'max_absent_count':5,'min_on_duty':0},
  'pause_reasons':deepcopy(DEFAULT_REASONS),
}
DEFAULT_CONFIG = {'version':1,'queues':{},'supervisors':{}}

def _bounded_int(value, low, high, field):
    if isinstance(value, bool) or str(value).strip() == '' or not re.fullmatch(r'-?\d+',str(value)):
        raise ValueError('invalid_'+field)
    num=int(value)
    if not low <= num <= high: raise ValueError('invalid_'+field)
    return num

def validate_config(raw):
    if not isinstance(raw, dict): raise ValueError('invalid_policy')
    queues=raw.get('queues',{})
    users=raw.get('supervisors',{})
    if not isinstance(queues,dict) or len(queues)>100 or not isinstance(users,dict) or len(users)>100:
        raise ValueError('invalid_policy_structure')
    cleaned={'version':1,'queues':{},'supervisors':{}}
    for name, q in queues.items():
        if not QUEUE_ID.fullmatch(name) or not isinstance(q,dict): raise ValueError('invalid_queue')
        base=deepcopy(DEFAULT_QUEUE)
        label=q.get('label','')
        if not isinstance(label,str) or len(label)>65 or any(x in label for x in '\r\n\x00'): raise ValueError('invalid_label')
        base['label']=label
        base['directory_external_dialing']=q.get('directory_external_dialing',False) is True
        alerts=q.get('alerts',{})
        staffing=q.get('staffing',{})
        if not isinstance(alerts,dict) or not isinstance(staffing,dict): raise ValueError('invalid_queue_settings')
        for key, lo, hi in [('waiting_above',0,10000),('wait_seconds_above',0,86400),('min_ready',0,1000),('cooldown_seconds',60,86400)]:
            base['alerts'][key]=_bounded_int(alerts.get(key,base['alerts'][key]),lo,hi,key)
        base['alerts']['bale_enabled']=alerts.get('bale_enabled',False) is True
        base['alerts']['telegram_enabled']=alerts.get('telegram_enabled',False) is True
        for key in ('count_enabled','time_enabled'):
            if key in alerts and not isinstance(alerts[key],bool):raise ValueError('invalid_alert_switch')
            base['alerts'][key]=alerts.get(key,True)
        mode=alerts.get('match_mode','any')
        if mode not in ('any','all'):raise ValueError('invalid_alert_match_mode')
        base['alerts']['match_mode']=mode
        for key, lo, hi in [('roster_size',0,1000),('max_absent_percent',0,100),('max_absent_count',0,1000),('min_on_duty',0,1000)]:
            base['staffing'][key]=_bounded_int(staffing.get(key,base['staffing'][key]),lo,hi,key)
        base['staffing']['enabled']=staffing.get('enabled',base['staffing']['roster_size']>0) is True
        if base['staffing']['enabled'] and not base['staffing']['roster_size']:raise ValueError('staffing_roster_required')
        reasons=[r for r in q.get('pause_reasons',DEFAULT_REASONS) if isinstance(r,dict) and r.get('id')!='survey']
        if not isinstance(reasons,list) or len(reasons)>30: raise ValueError('invalid_pause_reasons')
        used=set();base['pause_reasons']=[]
        for r in reasons:
            if not isinstance(r,dict) or not REASON_ID.fullmatch(str(r.get('id',''))): raise ValueError('invalid_pause_reason_id')
            ident=r['id']; label=r.get('label','')
            if ident in used or not isinstance(label,str) or not label.strip() or len(label)>70 or any(x in label for x in '\r\n\x00'):
                raise ValueError('invalid_pause_reason_label')
            used.add(ident);base['pause_reasons'].append({'id':ident,'label':label.strip()})
        cleaned['queues'][name]=base
    for username, grant in users.items():
        if not USER_ID.fullmatch(username) or not isinstance(grant,dict):raise ValueError('invalid_supervisor')
        qids=grant.get('queues',[]); actions=grant.get('actions',['view'])
        if not isinstance(qids,list) or not isinstance(actions,list) or len(qids)>100 or len(actions)>11:
            raise ValueError('invalid_supervisor_scope')
        if any(q not in cleaned['queues'] for q in qids) or any(a not in ALLOWED_GRANTS for a in actions):
            raise ValueError('invalid_supervisor_scope')
        cleaned['supervisors'][username]={'queues':list(dict.fromkeys(qids)),'actions':list(dict.fromkeys(actions))}
    return cleaned

class QueuePolicyStore:
    def __init__(self,path):
        self.path=Path(path)
        self.lock=RLock()
        self.reservation_backend=None
        self.state=deepcopy(DEFAULT_CONFIG)
        self._departure_reservations={}  # (queue, agent) -> monotonic expiry
        self._alert_previous=set()
        self._alert_sent={}
        self._notification_stats={'sent':0,'failed':0,'last_error':''}
        if self.path.exists():
            self.state=validate_config(json.loads(self.path.read_text(encoding='utf-8')))

    def export(self):
        with self.lock:return deepcopy(self.state)

    def remove_subject(self,username):
        """Remove a deleted identity without clearing live staffing reservations."""
        with self.lock:
            if username not in self.state['supervisors']:return
            clean=deepcopy(self.state);clean['supervisors'].pop(username)
            self.path.parent.mkdir(parents=True,exist_ok=True)
            temporary=self.path.with_suffix('.tmp')
            with temporary.open('w',encoding='utf-8') as stream:
                json.dump(clean,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,self.path);self.state=clean

    def replace(self,payload, *, visible_queues=None):
        clean=validate_config(payload)
        if visible_queues is not None and any(k not in visible_queues for k in clean['queues']):
            raise ValueError('queue_not_visible')
        with self.lock:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            tmp=self.path.with_suffix('.tmp')
            # No credentials in this file. Restrict file permissions where possible.
            with open(tmp,'w',encoding='utf-8') as stream:
                json.dump(clean,stream,ensure_ascii=False,indent=2)
                stream.flush();os.fsync(stream.fileno())
            os.replace(tmp,self.path)
            self.state=clean
            self._departure_reservations.clear()
            self._alert_previous.clear()
            self._alert_sent.clear()
        return self.export()

    def queue(self,queue):
        with self.lock:return deepcopy(self.state['queues'].get(queue,DEFAULT_QUEUE))

    def access(self,username,role,queue,action='view'):
        from sanequeue.security.permissions import ROLE_ACTIONS
        if action not in ROLE_ACTIONS.get(role,()):return False
        if role=='admin': return True
        if role not in ('supervisor','agent','viewer'): return False
        with self.lock:
            grant=self.state['supervisors'].get(username)
            return bool(grant and queue in grant['queues'] and action in grant['actions'])

    def visible(self,username,role,queues):
        return {q:v for q,v in queues.items() if self.access(username,role,q)}

    def reasons(self,queue):return self.queue(queue)['pause_reasons']

    def validate_reason(self,queue,reason):
        if reason and reason not in {r['id'] for r in self.reasons(queue)}:
            raise ValueError('unknown_pause_reason')
        return reason

    @staticmethod
    def on_duty(member):
        return str(member.get('Paused', '0')).lower() in ('0','false') and str(member.get('Status','0')) not in ('-1','0','4','5')

    def can_leave(self,queue,queue_data,agent):
        """Check live on-duty staffing against a configured *fixed roster*.

        Busy agents count as on-duty, unlike a simple Ready-only limit.
        For removal the configured roster_size persists after member removal;
        without an explicit roster, membership shrink could circumvent quotas.
        """
        members=queue_data.get('members',{})
        if not any(agent in (key,m.get('Location')) for key,m in members.items()):return False,'agent_not_in_queue'
        if not self.queue(queue)['staffing']['enabled']:return True,''
        if self.reservation_backend is not None:
            return self.reservation_backend.reserve(queue,agent,members,self.queue(queue)['staffing'],dry=True)
        matched=[m for key,m in members.items() if agent in (key,m.get('Location'))]
        if not matched: return False,'agent_not_in_queue'
        config=self.queue(queue)['staffing']
        roster=config['roster_size']
        if not roster:
            return False,'configure_roster_size_before_leaving'
        current=sum(self.on_duty(m) for m in members.values())
        now=time.monotonic()
        # Asterisk can acknowledge QueuePause before QueueStatus reflects it.
        # Reserve pending departures for one local process to block a second
        # supervisor using a stale snapshot at the exact capacity boundary.
        with self.lock:
            for key,expire in list(self._departure_reservations.items()):
                if expire<=now:
                    self._departure_reservations.pop(key,None)
            pending=0
            for (q,who),deadline in list(self._departure_reservations.items()):
                if q!=queue:continue
                member=next((m for key,m in members.items() if who in (key,m.get('Location'))),None)
                if member is None or not self.on_duty(member):
                    self._departure_reservations.pop((q,who),None)
                elif who!=agent:
                    pending+=1
                else:
                    return False,'departure_already_in_progress'
            after=current-pending-(1 if self.on_duty(matched[0]) else 0)
            allowed_absences=min(config['max_absent_count'],math.floor(roster*config['max_absent_percent']/100))
            minimum=max(config['min_on_duty'],roster-allowed_absences)
            return (after>=minimum, 'ok' if after>=minimum else 'queue_exit_limit_reached')

    def reserve_leave(self,queue,queue_data,agent):
        if not self.queue(queue)['staffing']['enabled']:
            return self.can_leave(queue,queue_data,agent)
        if self.reservation_backend is not None:
            return self.reservation_backend.reserve(queue,agent,queue_data.get('members',{}),self.queue(queue)['staffing'])
        with self.lock:
            permitted,reason=self.can_leave(queue,queue_data,agent)
            if permitted:self._departure_reservations[(queue,agent)]=time.monotonic()+60
            return permitted,reason

    def release_leave(self,queue,agent):
        if self.reservation_backend is not None:
            return self.reservation_backend.release(queue,agent)
        with self.lock:self._departure_reservations.pop((queue,agent),None)

    def summary(self,name,queue):
        members=list((queue.get('members') or {}).values());entries=list((queue.get('entries') or {}).values())
        on_duty=sum(self.on_duty(m) for m in members)
        status_counts={'ready':0,'busy':0,'paused':0,'offline':0}
        for m in members:
            if str(m.get('Paused','0')).lower() in ('1','true'): status_counts['paused']+=1
            elif str(m.get('Status','0'))=='1' and m.get('Ready',True) is not False:status_counts['ready']+=1
            elif str(m.get('Status','0')) in ('2','3','6','7','8','9','10'):status_counts['busy']+=1
            else:status_counts['offline']+=1
        def val(k):
            try:return int(float(queue.get(k,0)))
            except (ValueError,TypeError):return 0
        sl=queue.get('ServicelevelPerf',None)
        try:sl=float(sl) if sl not in (None,'') else None
        except (TypeError,ValueError):sl=None
        return {'queue':name,'label':self.queue(name)['label'] or name,'waiting':val('Calls'),
                'longest_wait':max([int(float(e.get('Wait',0))) for e in entries]+[0]),
                'completed':val('Completed'),'abandoned':val('Abandoned'),
                'hold_seconds':val('Holdtime') if queue.get('Holdtime') is not None else None,
                'talk_seconds':val('TalkTime') if queue.get('TalkTime') is not None else None,
                'service_level_pct':sl,'strategy':queue.get('Strategy') or '—','members':len(members),
                'on_duty':on_duty,'status_counts':status_counts,
                'policy':self.queue(name)}

    def evaluate(self,queues,now=None):
        """Return active alert objects and new notification transitions. No phone numbers."""
        now=time.monotonic() if now is None else now
        current=set();active=[];send=[]
        with self.lock:
            for name,data in queues.items():
                rules=self.queue(name)['alerts']
                summary=self.summary(name,data)
                count_fired=summary['waiting']>0 and summary['waiting']>=rules['waiting_above']
                time_fired=summary['longest_wait']>0 and summary['longest_wait']>=rules['wait_seconds_above']
                selected=[condition for key,condition in (('count_enabled',count_fired),('time_enabled',time_fired)) if rules[key]]
                matched=bool(selected) and (all(selected) if rules['match_mode']=='all' else any(selected))
                tests=(('waiting_count',matched and rules['count_enabled'] and count_fired, summary['waiting'], rules['waiting_above']),
                       ('waiting_time',matched and rules['time_enabled'] and time_fired,summary['longest_wait'],rules['wait_seconds_above']),
                       ('ready_below',summary['members']>0 and summary['status_counts']['ready']<rules['min_ready'],summary['status_counts']['ready'],rules['min_ready']))
                for typ,fired,value,limit in tests:
                    if not fired:continue
                    ident=(name,typ);current.add(ident)
                    alert={'queue':name,'type':typ,'value':value,'threshold':limit,'label':self.queue(name)['label'] or name}
                    active.append(alert)
                    last=self._alert_sent.get(ident,-float('inf'))
                    if ident not in self._alert_previous and now-last>=rules['cooldown_seconds']:
                        self._alert_sent[ident]=now
                        if rules['bale_enabled']:send.append(alert)
            self._alert_previous=current
            return {'alerts':active,'notify':send,'notification_status':dict(self._notification_stats)}

    def note_delivery(self,success,error=''):
        with self.lock:
            self._notification_stats['sent' if success else 'failed']+=1
            if not success:self._notification_stats['last_error']=str(error)[:100]


def send_bale_alert(alert, token, chat_id, *, timeout=5):
    """Only supported outbound host. Token never logged or returned in an API."""
    if not token or not chat_id or not re.fullmatch(r'[0-9A-Za-z:_-]{15,150}',token):
        raise ValueError('missing_bale_configuration')
    url='https://tapi.bale.ai/bot'+token+'/sendMessage'
    text=f"SaneQueue | هشدار صف {alert['label']} ({alert['queue']})\n{alert['type']}: {alert['value']} (آستانه {alert['threshold']})"
    body=json.dumps({'chat_id':str(chat_id),'text':text},ensure_ascii=False).encode('utf-8')
    req=urllib.request.Request(url,body,headers={'Content-Type':'application/json'},method='POST')
    with urllib.request.urlopen(req,timeout=timeout) as response:
        status=response.status
        parsed=json.loads(response.read(1024*128))
    return status==200 and bool(parsed.get('ok'))
