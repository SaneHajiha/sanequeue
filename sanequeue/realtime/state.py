"""Private materialized state; consumers must apply queue scope and redaction."""
import copy
import time


def integer(value, default=0):
    try:
        return max(0, int(float(value)))
    except (ValueError, TypeError, OverflowError):
        return default


def agent_state(member, now):
    status = integer(member.get('status'), -1)
    paused = str(member.get('paused', '0')).lower() in ('1', 'true')
    on_call = str(member.get('incall', '0')).lower() in ('1', 'true')
    wrap = member.get('wrapuptime')
    remaining = None
    if wrap is not None and integer(member.get('lastcall')):
        remaining = max(0, integer(wrap) - max(0, int(now - integer(member['lastcall']))))
    activity = ('ringing' if status in (6, 7) else 'hold' if status == 8 else
                'on_call' if on_call else 'busy' if status in (2, 3) else
                'offline' if status in (4, 5) else 'unknown' if status != 1 else
                'wrap_up' if remaining else 'available')
    return {'activity': activity, 'paused': paused,
            'on_duty': not paused and status not in (-1, 0, 4, 5),
            'ready': activity == 'available' and not paused,
            'wrap_up_remaining': remaining}


class StateOverflow(RuntimeError):
    pass


class QueueState:
    def __init__(self, *, max_records=50000, clock=time.time):
        self.queues, self.channels, self.by_channel, self.bridges = {}, {}, {}, {}
        self.version = 0
        self.records = 0
        self.max_records = max_records
        self.clock = clock
        self.last_event_at = None
        self.last_sync_at = None
        self.channels_complete = False
        self._counter_events = {}
        self.wrap_deadlines = {}

    def _put(self, table, key, value):
        if key not in table:
            if self.records >= self.max_records:
                raise StateOverflow('state_record_limit')
            self.records += 1
        table[key] = value

    def _drop(self, table, key):
        if key in table:
            del table[key]
            self.records -= 1

    def _queue(self, name):
        if name not in self.queues:
            if len(self.queues) >= 1024:
                raise StateOverflow('queue_limit')
            self._put(self.queues, name, {'members': {}, 'entries': {}, 'params': {},
                                        'counters_as_of': None})
        return self.queues[name]

    def _channel(self, event):
        uid = event.get('uniqueid')
        if not uid:
            return None
        old = self.channels.get(uid, {})
        channel = dict(old)
        channel.update({k: event[k] for k in ('channel', 'linkedid', 'channelstate',
                       'channelstatedesc', 'calleridnum', 'calleridname', 'exten',
                       'context', 'application', 'duration') if k in event})
        channel.setdefault('created_at', self.clock())
        channel.setdefault('queues', [])
        self._put(self.channels, uid, channel)
        if old.get('channel') and old.get('channel') != channel.get('channel'):
            self.by_channel.pop(old['channel'], None)
        if channel.get('channel'):
            self.by_channel[channel['channel']] = uid
        return uid

    def ingest(self, event):
        e = {str(k).lower(): str(v)[:2048] for k, v in event.items()}
        kind, queue, now = e.get('event', '').lower(), e.get('queue'), self.clock()
        handled = False
        if queue and kind in {'queueparams', 'queueentry', 'queuemember',
                'queuememberadded', 'queuememberremoved', 'queuememberstatus',
                'queuememberpause', 'queuememberpenalty', 'queuememberringinuse',
                'queuecallerjoin', 'queuecallerleave', 'queuecallerabandon',
                'agentcalled', 'agentconnect', 'agentcomplete', 'agentringnoanswer'}:
            q = self._queue(queue)
            handled = True
            member = e.get('interface') or e.get('location')
            if kind == 'queueparams':
                q['params'] = {k: v for k, v in e.items() if k not in ('event', 'actionid')}
                q['counters_as_of'] = now
            elif kind in ('queuemember', 'queuememberadded', 'queuememberstatus',
                          'queuememberpause', 'queuememberpenalty', 'queuememberringinuse') and member:
                value = dict(q['members'].get(member, {}))
                previous = (value.get('status'), value.get('paused'), value.get('incall'))
                value.update({k: v for k, v in e.items() if k not in ('event', 'actionid')})
                value['name'] = e.get('membername') or e.get('name') or value.get('name', member)
                if previous != (value.get('status'), value.get('paused'), value.get('incall')):
                    value['state_observed_since'] = now
                self._put(q['members'], member, value)
            elif kind == 'queuememberremoved' and member:
                self._drop(q['members'], member)
            elif kind in ('queueentry', 'queuecallerjoin'):
                key = e.get('uniqueid') or e.get('channel')
                if key:
                    if kind == 'queuecallerjoin' and key not in q['entries']:
                        # A transferred caller may re-enter the same queue with the same UID.
                        for counter_kind in ('agentcomplete', 'queuecallerabandon'):
                            self._counter_events.pop((queue, counter_kind, key), None)
                    value = dict(q['entries'].get(key, {}))
                    value.update({k: v for k, v in e.items() if k not in ('event', 'actionid')})
                    value.setdefault('waiting_since', now - integer(e.get('wait')))
                    self._put(q['entries'], key, value)
            elif kind in ('queuecallerleave', 'queuecallerabandon', 'agentconnect'):
                key = e.get('uniqueid') or e.get('channel')
                self._drop(q['entries'], key)
                # Older snapshots may identify callers by channel only.
                for other, entry in list(q['entries'].items()):
                    if e.get('channel') and entry.get('channel') == e['channel']:
                        self._drop(q['entries'], other)
            if kind in ('agentcomplete', 'queuecallerabandon') and e.get('_skip_counter') != '1':
                ident = e.get('uniqueid')
                marker = (queue, kind, ident)
                if ident and marker not in self._counter_events:
                    if len(self._counter_events) >= 10000:
                        raise StateOverflow('counter_dedup_limit')
                    self._counter_events[marker] = now
                    counter = 'completed' if kind == 'agentcomplete' else 'abandoned'
                    if counter in q['params']:
                        q['params'][counter] = str(integer(q['params'][counter]) + 1)
            if kind in ('agentcalled', 'agentconnect', 'agentcomplete') and member in q['members']:
                m = q['members'][member]
                if kind != 'agentcalled':
                    m['incall'] = '1' if kind == 'agentconnect' else '0'
                if kind == 'agentcomplete':
                    m['lastcall'] = str(int(now))
                # Status/device events remain authoritative for ready/ringing.
                if kind != 'agentcalled':
                    m['state_observed_since'] = now
            if member:
                m = q['members'].get(member, {})
                deadline = integer(m.get('lastcall')) + integer(m.get('wrapuptime'))
                if m.get('wrapuptime') is not None and deadline > now:
                    self.wrap_deadlines[(queue, member)] = deadline
                else:
                    self.wrap_deadlines.pop((queue, member), None)
            q['waiting_count'] = len(q['entries'])

        if kind in ('newchannel', 'newstate', 'coreshowchannel', 'newcallerid', 'rename'):
            if kind == 'rename' and e.get('newname'):
                e = dict(e, channel=e['newname'])
            self._channel(e)
            handled = True
        uid = e.get('uniqueid') or self.by_channel.get(e.get('channel'))
        if queue and uid in self.channels:
            scopes = set(self.channels[uid]['queues'])
            scopes.add(queue)
            self.channels[uid]['queues'] = sorted(scopes)
        if kind in ('bridgeenter', 'bridgeleave') and uid:
            if uid not in self.channels and kind == 'bridgeenter':
                self._channel(dict(e, uniqueid=uid))
            bridge = e.get('bridgeuniqueid')
            if bridge:
                if kind == 'bridgeenter':
                    old_bridge = self.channels.get(uid, {}).get('bridge')
                    if old_bridge and old_bridge != bridge:
                        self.bridges.get(old_bridge, set()).discard(uid)
                        if not self.bridges.get(old_bridge):
                            self._drop(self.bridges, old_bridge)
                    if bridge not in self.bridges:
                        self._put(self.bridges, bridge, set())
                    self.bridges[bridge].add(uid)
                    scopes = set().union(*(set(self.channels.get(k, {}).get('queues', []))
                                          for k in self.bridges[bridge]))
                    for k in self.bridges[bridge]:
                        if k in self.channels:
                            self.channels[k]['queues'] = sorted(scopes)
                            self.channels[k]['bridge'] = bridge
                else:
                    self.bridges.get(bridge, set()).discard(uid)
                    if not self.bridges.get(bridge):
                        self._drop(self.bridges, bridge)
                    if uid in self.channels and self.channels[uid].get('bridge') == bridge:
                        self.channels[uid].pop('bridge', None)
            handled = True
        if kind in ('dialbegin', 'dialend', 'blindtransfer', 'attendedtransfer'):
            related = set()
            for prefix in ('', 'dest', 'transferer', 'transferee', 'origtransferer',
                           'secondtransferer', 'secondtransferee'):
                key = e.get(prefix + 'uniqueid') or self.by_channel.get(e.get(prefix + 'channel'))
                if key in self.channels:
                    related.add(key)
            scopes = set().union(*(set(self.channels[k]['queues']) for k in related))
            for key in related:
                self.channels[key]['queues'] = sorted(scopes)
                self.channels[key]['last_relationship_event'] = kind
            handled = True
        if kind in ('hold', 'unhold') and uid in self.channels:
            self.channels[uid]['held_since'] = now if kind == 'hold' else None
            handled = True
        if kind == 'hangup':
            old = self.channels.get(uid, {})
            self.by_channel.pop(old.get('channel'), None)
            bridge = old.get('bridge')
            self.bridges.get(bridge, set()).discard(uid)
            if bridge and not self.bridges.get(bridge):
                self._drop(self.bridges, bridge)
            self._drop(self.channels, uid)
            for q in self.queues.values():
                self._drop(q['entries'], uid)
                self._drop(q['entries'], e.get('channel'))
                q['waiting_count'] = len(q['entries'])
            handled = True
        if handled:
            self.version += 1
            self.last_event_at = now
        return handled

    def expire_timers(self):
        now = self.clock()
        expired = [key for key, deadline in self.wrap_deadlines.items() if deadline <= now]
        for key in expired:
            del self.wrap_deadlines[key]
        if expired:
            self.version += 1

    def snapshot(self):
        now = self.clock()
        queues = copy.deepcopy(self.queues)
        for q in queues.values():
            for member in q['members'].values():
                member['derived'] = agent_state(member, now)
        return {'schema': 1, 'queues': queues, 'channels': copy.deepcopy(self.channels),
                'revision': self.version, 'last_event_at': self.last_event_at,
                'last_sync_at': self.last_sync_at, 'channels_complete': self.channels_complete,
                'history_complete': False, 'initial_call_scope_complete': False,
                'snapshot_atomic': False}
