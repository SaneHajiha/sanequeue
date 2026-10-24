"""Redis-only reads. A cache miss or stale collector never contacts AMI."""
import copy
import json
import re
import threading
import time
from sanequeue.realtime.state import agent_state


class StateUnavailable(RuntimeError):
    pass


class StateReader:
    def __init__(self, redis, pbx_id, *, clock=time.monotonic, cache_seconds=.5):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,48}', pbx_id):
            raise ValueError('invalid_pbx_id')
        prefix = 'sanequeue:{' + pbx_id + '}:'
        self.redis, self.keys = redis, [prefix+'state', prefix+'health']
        self.clock, self.cache_seconds = clock, cache_seconds
        self.lock = threading.RLock()
        self.cached, self.until = None, 0
        self.reads = 0

    def read(self, *, fresh=False):
        with self.lock:
            if fresh or self.clock() >= self.until or self.cached is None:
                try:
                    state, health = self.redis.mget(self.keys)
                    body, meta = json.loads(state) if state else None, json.loads(health) if health else {}
                    if not (isinstance(body, dict) and meta.get('connected') and meta.get('complete') and
                            body.get('generation') == meta.get('generation')):
                        raise StateUnavailable('collector_stale')
                    self.cached = (body, meta)
                    self.reads += 1
                    self.until = self.clock() + self.cache_seconds
                except Exception as exc:
                    self.cached, self.until = None, 0
                    raise StateUnavailable('collector_unavailable') from None
            return copy.deepcopy(self.cached)


def duration_seconds(value):
    try:
        parts = str(value or '').split(':')
        return max(0, sum(int(float(v)) * (60 ** i) for i, v in enumerate(reversed(parts))))
    except (ValueError, TypeError, OverflowError):
        return 0


def legacy_queues(state, *, now=None):
    """Explicit allowlist of fields consumed by the existing operations UI."""
    now = time.time() if now is None else now
    result = {}
    fields = {'strategy':'Strategy', 'holdtime':'Holdtime', 'talktime':'TalkTime',
              'completed':'Completed', 'abandoned':'Abandoned', 'servicelevelperf':'ServicelevelPerf',
              'servicelevel':'ServiceLevelSeconds', 'servicelevelperf2':'ServicelevelPerf2'}
    members = {'name':'Name', 'stateinterface':'StateInterface', 'membership':'Membership',
               'status':'Status', 'paused':'Paused', 'pausedreason':'PausedReason', 'incall':'InCall',
               'callstaken':'CallsTaken', 'penalty':'Penalty', 'lastcall':'LastCall', 'lastpause':'LastPause',
               'wrapuptime':'Wrapuptime', 'state_observed_since':'StateSince'}
    for name, q in state.get('queues', {}).items():
        value = {target:q.get('params', {}).get(source, '') for source,target in fields.items()}
        value.update(members={}, entries={}, CountersObservedAt=q.get('counters_as_of'))
        for interface, member in q.get('members', {}).items():
            m = {target:member[source] for source,target in members.items() if source in member}
            derived = agent_state(member, now)
            m.update(Location=interface, Activity=derived.get('activity', 'unknown'),
                     Ready=derived.get('ready', False), WrapUpRemaining=derived.get('wrap_up_remaining'))
            if str(m.get('InCall')) == '1' and str(m.get('Status')) not in ('6','7','8'):
                m['Status'] = '10'
            for source,target in [('LastCall','LastCallAgo'),('LastPause','LastPauseAgo')]:
                seconds = duration_seconds(m.get(source))
                m[target] = str(max(0, int(now-seconds)))+' sec ago' if seconds else '—'
            value['members'][interface] = m
        for key, entry in q.get('entries', {}).items():
            e = {target:entry.get(source, '') for source,target in {
                'channel':'Channel','uniqueid':'Uniqueid','calleridnum':'CallerIDNum',
                'calleridname':'CallerIDName','position':'Position','priority':'Priority',
                'sourcetrunk':'SourceTrunk'}.items()}
            e['Wait'] = str(max(0, int(now-entry.get('waiting_since', now))))
            value['entries'][e['Channel'] or key] = e
        value['Calls'] = str(len(value['entries']))
        result[name] = value
    return result


def scoped_channels(state, allowed_queues):
    allowed = set(allowed_queues)
    return {uid:c for uid,c in state.get('channels', {}).items()
            if c.get('queues') and set(c['queues']).issubset(allowed)}


def journey_projection(state, allowed_queues, numbers=False):
    feed = state.get('journeys', {})
    allowed, records = set(allowed_queues), []
    for record in feed.get('records', []):
        touched = set(record.get('queues', []))
        if not touched or not touched.issubset(allowed):
            continue
        item = copy.deepcopy(record)
        if not numbers:
            for field in ('caller', 'ingress_hint', 'destination'):
                item[field] = ''
            for event in item.get('timeline', []):
                event['detail'] = ''
        records.append(item)
    return dict(connected=bool(feed.get('connected')), observed_at=feed.get('observed_at'),
                since=feed.get('since'), complete_history=False, records=records[:60])
