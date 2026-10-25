"""Read-only, bounded AMI call journey state machine.

Queue -> answer -> blind/attended transfer -> destination dialing/bridge -> final
hangup. It never sends AMI call-changing commands. It deliberately does not
claim historical completeness or identify a trunk without an explicit trusted
mapping or tagged ingress source.
"""
from collections import OrderedDict
from threading import RLock
import hashlib
import hmac
import re
import secrets
import time


def field(event, name, default=''):
    return next((str(value) for key, value in event.items()
                 if str(key).lower() == name.lower() and value is not None), default)


def clean(value, limit=128):
    return ''.join(ch for ch in str(value or '') if ch.isprintable() and ch not in '<>')[:limit]


def endpoint(channel):
    """A channel endpoint is not automatically a verified trunk."""
    match = re.match(r'^(?:PJSIP|SIP|IAX2|DAHDI|Local)/([A-Za-z0-9_.+@-]+)', channel or '')
    if not match:return ''
    raw=match.group(1).split('@', 1)[0]
    return re.sub(r'-[0-9a-fA-F]{4,}$', '', raw)


class JourneyEngine:
    """In-memory single-process lifecycle; call correlation is best-effort."""
    INTERESTING = frozenset({
        'Newchannel', 'Newstate', 'DialBegin', 'DialEnd', 'BridgeEnter',
        'BridgeLeave', 'QueueCallerJoin', 'QueueCallerLeave',
        'QueueCallerAbandon', 'AgentCalled', 'AgentConnect', 'AgentComplete',
        'BlindTransfer', 'AttendedTransfer', 'Hangup', 'Rename', 'NewExten',
    })
    def __init__(self, trunk_map=None, *, max_calls=700, completed_ttl=900, clock=None):
        self.trunk_map = {str(k): clean(v, 70) for k, v in (trunk_map or {}).items() if k and v}
        self.max_calls = max_calls
        self.completed_ttl = completed_ttl
        self.clock = clock or time.time
        self.lock = RLock()
        self.key = secrets.token_bytes(32)
        self.traces = OrderedDict()
        self.channel_root = {}
        self.uid_root = {}
        self.connected = False
        self.last_event = None
        self.last_connected = None
        self.generation = 0

    def _root(self, e):
        # Asterisk transfers may expose multiple linked IDs. Reuse an observed
        # owner rather than assuming the transferer's channel is the caller.
        ids = [field(e, n) for n in ('TransfereeLinkedid','Linkedid',
            'DestLinkedid','OrigTransfererLinkedid','SecondTransfererLinkedid',
            'TransfererLinkedid','Uniqueid','DestUniqueid')]
        channels = [field(e, n) for n in ('TransfereeChannel','Channel',
            'DestChannel','OrigTransfererChannel','SecondTransfererChannel',
            'TransfererChannel')]
        for value in channels:
            if value in self.channel_root:
                root = self.channel_root[value]
                if root in self.traces and self.traces[root]['queues']:
                    return root
        for value in ids:
            if value in self.uid_root and self.uid_root[value] in self.traces:
                return self.uid_root[value]
            if value in self.traces:
                return value
        return next((v for v in ids if v), '')

    def _trace(self, root, now):
        if root not in self.traces:
            self.traces[root] = {
                'first': now, 'updated': now, 'queues': set(), 'caller': '',
                'trunk': '', 'trunk_verified': False, 'ingress_hint': '',
                'status': 'observed', 'channel_active': set(),
                'channels_seen': set(), 'connected_channels': set(), 'destination_channels': set(), 'caller_channels': set(), 'bridges': {},
                'destination': '', 'last_agent': '', 'transfer_type': '',
                'transfers': 0, 'ended': None, 'timeline': [],
                'ivr_steps': [], 'hangup_party': 'unknown', 'hangup_evidence': '',
            }
        trace = self.traces[root]
        trace['updated'] = now
        self.traces.move_to_end(root)
        return trace

    def _emit(self, trace, state, now, detail=''):
        if trace['timeline'] and (trace['timeline'][-1]['state'],trace['timeline'][-1]['detail']) == (state,detail):
            return
        trace['timeline'].append({'time': int(now), 'state': state,
                                  'detail': clean(detail, 100)})
        trace['timeline'] = trace['timeline'][-36:]
        trace['status'] = state

    def _apply_trunk(self, trace, e, channel):
        # Explicit AMI custom tags or exact configured channel prefix only.
        explicit = field(e,'IngressTrunk') or field(e,'SourceTrunk')
        if explicit:
            trace['trunk'] = clean(explicit, 70)
            trace['trunk_verified'] = True
            return
        ctx = field(e, 'Context').lower()
        source = endpoint(channel)
        if ctx in ('from-trunk','from-pstn','from-did-direct','from-did-direct-ivr') and source:
            trace['ingress_hint'] = clean(source, 70)
        if trace['trunk_verified']:
            return
        for prefix,label in self.trunk_map.items():
            if channel.startswith(prefix) and (ctx in ('from-trunk','from-pstn','from-did-direct','from-did-direct-ivr') or field(e,'Event') == 'QueueCallerJoin'):
                trace['trunk'] = label
                trace['trunk_verified'] = True
                return

    def ingest(self, event, now=None):
        """Consume one Asterisk AMI event, no network or side effects."""
        event_name = next((name for name in self.INTERESTING if name.lower() == field(event,'Event').lower()), '')
        if event_name not in self.INTERESTING:
            return
        now = float(self.clock() if now is None else now)
        # Menu traversal only: never collect arbitrary DTMF or dialplan AppData.
        if event_name == 'NewExten' and not re.fullmatch(r'ivr-[A-Za-z0-9_-]{1,48}',field(event,'Context'),re.I):
            return
        with self.lock:
            self.last_event = now
            root = self._root(event)
            if not root:
                return
            trace = self._trace(root,now)
            channel = field(event,'Channel')
            uid = field(event,'Uniqueid')
            linked = field(event,'Linkedid')
            if uid: self.uid_root[uid] = root
            if linked: self.uid_root[linked] = root
            if channel: self.channel_root[channel] = root
            if event_name in ('Newchannel', 'QueueCallerJoin','AgentConnect','DialBegin','Newstate','BridgeEnter'):
                if channel:
                    trace['channel_active'].add(channel)
                    trace['channels_seen'].add(channel)
            if event_name == 'NewExten':
                context=clean(field(event,'Context'),52)
                extension=field(event,'Exten') or field(event,'Extension')
                if field(event,'Priority')=='1' and (extension in ('s','t','i') or re.fullmatch(r'[0-9*#]{1,8}',extension)):
                    step={'context':context,'selection':extension,'time':int(now)}
                    if not trace['ivr_steps'] or (context,extension)!=(trace['ivr_steps'][-1]['context'],trace['ivr_steps'][-1]['selection']):
                        trace['ivr_steps'].append(step)
                        trace['ivr_steps']=trace['ivr_steps'][-12:]
                        self._emit(trace,'ivr_enter' if extension=='s' else 'ivr_selection',now,context+': '+extension)
            elif event_name == 'Newchannel':
                self._apply_trunk(trace,event,channel)
                if trace['trunk'] or trace['ingress_hint']:
                    label = trace['trunk'] or (trace['ingress_hint'] + ' (unverified)')
                    self._emit(trace,'ingress',now,label)
                if not trace['caller']:
                    trace['caller'] = clean(field(event,'CallerIDNum'),60)
            if event_name in ('QueueCallerJoin','AgentConnect','AgentCalled'):
                queue = clean(field(event,'Queue'),80)
                if queue and queue.lower() != 'default':trace['queues'].add(queue)
                if field(event,'CallerIDNum'):trace['caller']=clean(field(event,'CallerIDNum'),60)
                self._apply_trunk(trace,event,channel)
                if not trace['timeline']:
                    label = trace['trunk'] or ((trace['ingress_hint'] + ' (unverified)') if trace['ingress_hint'] else 'unknown')
                    self._emit(trace,'ingress',now,label)
                if event_name == 'QueueCallerJoin':
                    if channel:trace['caller_channels'].add(channel)
                    self._emit(trace,'in_queue',now,queue)
                elif event_name == 'AgentCalled':
                    self._emit(trace,'ringing_agent',now,clean(field(event,'MemberName') or field(event,'Interface')))
                else:
                    trace['last_agent']=clean(field(event,'MemberName') or field(event,'Interface'))
                    dest=field(event,'DestChannel')
                    if dest:
                        trace['channel_active'].add(dest)
                        trace['channels_seen'].add(dest)
                        self.channel_root[dest]=root
                        if field(event,'DestUniqueid'):self.uid_root[field(event,'DestUniqueid')]=root
                    self._emit(trace,'answered',now,trace['last_agent'])
            elif event_name == 'QueueCallerAbandon':
                trace['hangup_party']='caller'
                trace['hangup_evidence']='QueueCallerAbandon'
                self._emit(trace,'abandoned',now)
            elif event_name == 'AgentComplete':
                reason=field(event,'Reason').lower()
                # Queue's explicit completion reason is authoritative for this
                # queue leg. Hangup ordering of Local/SIP legs proves nothing.
                if reason in ('caller','agent'):
                    trace['hangup_party']=reason
                    trace['hangup_evidence']='AgentComplete'
                    self._emit(trace,'caller_hangup' if reason=='caller' else 'agent_hangup',now)
                elif reason=='transfer':
                    trace['hangup_party']='unknown'
                    trace['hangup_evidence']=''
            elif event_name == 'QueueCallerLeave':
                # Normal QueueCallerLeave occurs on answer AND on exit; it is
                # not evidence the actual phone conversation has finished.
                if trace['status'] in ('in_queue','ringing_agent'):
                    self._emit(trace,'left_queue',now)
            elif event_name in ('BlindTransfer','AttendedTransfer'):
                result=field(event,'Result')
                if result.lower() != 'success':
                    self._emit(trace,'transfer_failed',now,result)
                else:
                    trace['transfers']+=1
                    trace['transfer_type']='blind' if event_name=='BlindTransfer' else 'attended'
                    destination=field(event,'Extension') if event_name=='BlindTransfer' else ''
                    if not destination:
                        destination=endpoint(field(event,'DestTransfererChannel')) or endpoint(field(event,'LocalOneChannel'))
                    trace['destination']=clean(destination,80) or trace['destination']
                    self._emit(trace,'transferred',now,trace['destination'])
                    for name in ('TransfereeChannel','OrigTransfererChannel','SecondTransfererChannel','DestTransfererChannel'):
                        ch=field(event,name)
                        if ch: self.channel_root[ch]=root
            elif event_name == 'DialBegin':
                dest = field(event,'DestChannel')
                if dest:
                    trace['channel_active'].add(dest)
                    trace['channels_seen'].add(dest)
                    self.channel_root[dest]=root
                    if trace['transfers']:trace['destination_channels'].add(dest)
                    uid2=field(event,'DestUniqueid')
                    if uid2:self.uid_root[uid2]=root
                if trace['transfers']:
                    destination=endpoint(dest) or clean(field(event,'DialString'),80)
                    if destination:trace['destination']=destination
                    self._emit(trace,'post_transfer_ringing',now,trace['destination'])
            elif event_name == 'Newstate':
                state=field(event,'ChannelStateDesc').lower()
                if trace['transfers'] and channel in trace['destination_channels'] and state in ('ring','ringing'):
                    self._emit(trace,'post_transfer_ringing',now,trace['destination'])
                elif trace['transfers'] and channel in trace['destination_channels'] and state == 'up':
                    # Up is not proof of media bridge, only channel state.
                    self._emit(trace,'post_transfer_connected',now,trace['destination'])
            elif event_name == 'BridgeEnter':
                if channel:trace['connected_channels'].add(channel)
                bridge=field(event,'BridgeUniqueid')
                if bridge and channel:
                    participants=trace['bridges'].setdefault(bridge,set())
                    participants.add(channel)
                    # An Up/Ringing channel is not enough. Mark connected only
                    # after the transferee and transfer target share a bridge.
                    if trace['transfers'] and participants.intersection(trace['destination_channels']) and participants.intersection(trace['caller_channels']):
                        self._emit(trace,'post_transfer_talking',now,trace['destination'])
            elif event_name == 'BridgeLeave':
                trace['connected_channels'].discard(channel)
                for participants in trace['bridges'].values():participants.discard(channel)
            elif event_name == 'Hangup':
                trace['channel_active'].discard(channel)
                trace['connected_channels'].discard(channel)
                for participants in trace['bridges'].values():participants.discard(channel)
                if trace['queues'] and not trace['channel_active']:
                    trace['ended']=now  # grace-period before final confirmation
                    self._emit(trace,'possible_end',now)
            elif event_name == 'Rename':
                old=field(event,'Oldname');new=field(event,'Newname')
                if old in self.channel_root:
                    self.channel_root[new]=self.channel_root.pop(old)
                    if old in trace['channel_active']:
                        trace['channel_active'].discard(old)
                        trace['channel_active'].add(new)
            if trace['ended'] is not None and trace['channel_active']:
                trace['ended']=None
            self._prune(now)

    def _prune(self, now):
        doomed=[]
        for root, trace in list(self.traces.items()):
            if (not trace['queues'] and now-trace['updated']>120) or (trace['ended'] and now-trace['ended']>self.completed_ttl):
                doomed.append(root)
        if len(self.traces)-len(doomed)>self.max_calls:
            doomed.extend(list(self.traces)[:len(self.traces)-len(doomed)-self.max_calls])
        for root in set(doomed):
            self.traces.pop(root,None)
        if doomed:
            allowed=set(self.traces)
            self.channel_root={k:v for k,v in self.channel_root.items() if v in allowed}
            self.uid_root={k:v for k,v in self.uid_root.items() if v in allowed}

    def mark_connection(self, online, now=None):
        now = float(self.clock() if now is None else now)
        with self.lock:
            if online:
                self.last_connected=now
                self.generation+=1
            self.connected=bool(online)

    def snapshot(self, allowed_queues, *, numbers=False, wallboard=False, now=None):
        now = float(self.clock() if now is None else now)
        permitted=set(str(q) for q in allowed_queues)
        records=[]
        with self.lock:
            self._prune(now)
            for root,tr in reversed(self.traces.items()):
                # Cross-queue traces can include agents and caller details from
                # both queues. Hide until the user may view ALL touched queues.
                if not tr['queues'] or not tr['queues'].issubset(permitted):
                    continue
                end=tr['ended'] is not None and not tr['channel_active'] and now-tr['ended'] >= 5
                state='ended' if end else tr['status']
                if state=='possible_end':state='ending'
                # Opaque, non-reversible browser identifier; never expose root.
                rid=hmac.new(self.key,root.encode('utf-8'),hashlib.sha256).hexdigest()[:18]
                records.append({
                    'id':rid, 'queues':sorted(tr['queues'].intersection(permitted)),
                    'caller':tr['caller'] if numbers and not wallboard else '',
                    'trunk':tr['trunk'] or '', 'trunk_verified':tr['trunk_verified'],
                    'ingress_hint': tr['ingress_hint'] if numbers and not wallboard else '',
                    'status':state,'destination':tr['destination'],
                    'last_agent':tr['last_agent'],'transfer_type':tr['transfer_type'],
                    'transfers':tr['transfers'],'started_at':int(tr['first']),
                    'ivr_steps':list(tr['ivr_steps']),
                    'hangup_party':tr['hangup_party'],'hangup_evidence':tr['hangup_evidence'],
                    'updated_at':int(tr['updated']), 'ended_at':int(tr['ended']) if end else None,
                    'timeline':list(tr['timeline'])[-24:],
                })
                if len(records)>=60:break
            return {'connected':self.connected,'observed_at':int(self.last_event) if self.last_event else None,
                    'since':int(self.last_connected) if self.last_connected else None,
                    'records':records, 'complete_history':False}
