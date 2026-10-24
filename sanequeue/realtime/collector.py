"""Single-leader AMI collector, independent of viewer count and web workers."""
import asyncio
import logging
import random
import time
import uuid

from .protocol import AsyncAMI, AMIRejected
from .state import QueueState
from .journeys import JourneyEngine
from .inventory import _ACTIONS, _CAPABILITIES, parse_health

log = logging.getLogger('sanequeue.collector')


class Collector:
    def __init__(self, settings, store):
        self.settings, self.store = settings, store
        self.state = QueueState()
        self.journeys = JourneyEngine()
        self.journey_seeded = False
        self.client = None
        self.generation = uuid.uuid4().hex
        self.connected = self.complete = False
        self.syncing = False
        self.journal = []
        self.resync_requested = False
        self.last_heartbeat = None
        self.metrics = {'connections': 0, 'reconnects': 0, 'resyncs': 0, 'events': 0}
        self.reason = 'starting'

    def event(self, packet):
        self.metrics['events'] += 1
        self.journeys.ingest(packet)
        if packet.get('event', '').lower() in ('reload', 'fullybooted'):
            self.complete = False
            self.resync_requested = True
        if self.syncing:
            if len(self.journal) >= 50000:
                raise BufferError('resync_journal_limit')
            self.journal.append((dict(packet), time.time()))
        else:
            self.state.ingest(packet)

    async def synchronize(self):
        self.syncing, self.complete, self.journal = True, False, []
        try:
            queues = await self.client.request('QueueStatus', complete='QueueStatusComplete')
            try:
                channels = await self.client.request('CoreShowChannels', complete='CoreShowChannelsComplete')
                channels_complete = True
            except AMIRejected:
                channels, channels_complete = [], False
            staged = QueueState()
            queue_barriers = {}
            for packet in queues:
                if packet.get('event', '').lower() == 'queueparams':
                    queue_barriers[packet.get('queue')] = packet['_sequence']
                staged.ingest(packet)
            for packet in channels:
                staged.ingest(packet)
            for uid, value in staged.channels.items():
                previous = self.state.channels.get(uid, {})
                for key in ('queues', 'created_at', 'held_since', 'hold_seconds', 'answered_at','bridge_entered_at','rtcp','rtcp_received','rtcp_sent','last_relationship_event'):
                    if key in previous:
                        value[key] = previous[key]
                if 'bridgeid' not in value and previous.get('bridge'):
                    value['bridge']=previous['bridge']
                    if value['bridge'] not in staged.bridges:staged._put(staged.bridges,value['bridge'],set())
                    staged.bridges[value['bridge']].add(uid)
            for key,value in self.state.parked.items():
                if value.get('parkeeuniqueid') in staged.channels:
                    staged._put(staged.parked,key,dict(value))
            staged.action_events=dict(self.state.action_events)
            staged.inventory=dict(self.state.inventory)
            for packet, observed in self.journal:
                # Aggregate counters must not replay events preceding QueueParams.
                kind = packet.get('event', '').lower()
                if kind in ('agentcomplete', 'queuecallerabandon') and packet['_sequence'] <= queue_barriers.get(packet.get('queue'), 0):
                    packet = dict(packet, _skip_counter='1')
                staged.clock = lambda observed=observed: observed
                staged.ingest(packet)
            staged.clock = time.time
            # Seed only associations actually present in the initial waiting list.
            for name, queue in staged.queues.items():
                for key, entry in queue['entries'].items():
                    uid = entry.get('uniqueid') or staged.by_channel.get(entry.get('channel'))
                    if uid in staged.channels:
                        staged.channels[uid]['queues'] = sorted(set(staged.channels[uid]['queues']) | {name})
            staged.last_sync_at = time.time()
            visited=set()
            for uid in staged.channels:
                if uid not in visited:visited.update(staged.propagate_scopes(uid))
            staged.channels_complete = channels_complete
            staged.version = self.state.version + 1
            self.state = staged
            if not self.journey_seeded:
                for uid, channel in staged.channels.items():
                    self.journeys.ingest(dict(channel, Event='Newchannel', Uniqueid=uid))
                for queue, value in staged.queues.items():
                    for entry in value['entries'].values():
                        self.journeys.ingest(dict(entry, Event='QueueCallerJoin', Queue=queue))
                self.journey_seeded = True
            self.complete = True
            self.resync_requested = False
            self.metrics['resyncs'] += 1
        finally:
            self.syncing = False
            self.journal = []

    def health(self):
        return {'generation': self.generation, 'revision': self.state.version,
                'connected': self.connected, 'complete': self.complete,
                'reason': self.reason, 'last_heartbeat_at': self.last_heartbeat,
                'last_event_at': self.state.last_event_at,
                'last_sync_at': self.state.last_sync_at, 'published_at': time.time(),
                'metrics': dict(self.metrics)}

    async def publisher(self):
        previous = None
        while True:
            self.state.expire_timers()
            marker = (self.generation, self.state.version, self.connected, self.complete, self.reason)
            changed = marker != previous
            body = self.snapshot() if changed else None
            if not await self.store.publish(body, self.health(), changed=changed):
                raise ConnectionError('collector_lease_lost')
            previous = marker
            await asyncio.sleep(self.settings.publish_seconds)

    def snapshot(self):
        return dict(self.state.snapshot(), generation=self.generation,
                    journeys=self.journeys.snapshot(self.state.queues, numbers=True))

    async def renewer(self):
        while True:
            await asyncio.sleep(self.store.lease_ms / 3000)
            if not await self.store.renew():
                raise ConnectionError('collector_lease_lost')

    async def heartbeat(self):
        while True:
            await self.client.request('Ping', timeout=5)
            self.last_heartbeat = time.time()
            await asyncio.sleep(self.settings.heartbeat_seconds)

    async def inventory_loop(self):
        while True:
            try:
                packets=await self.client.request('ListCommands',timeout=3)
                commands=packets[-1]
                self.state.inventory['permissions']=dict(kind='permissions',supported=True,
                    actions={a:a.lower() in commands for a in _CAPABILITIES},observed_at=time.time(),
                    note='Collector read identity permissions; control identity is separate.')
                self.state.version+=1
                for kind in ('extensions','sip_extensions','contacts','registrations','sip_registrations','parking'):
                    action,event,complete=_ACTIONS[kind]
                    result=dict(kind=kind,action=action,observed_at=time.time(),supported=False,reason='action_permission_or_module_unavailable')
                    if action.lower() in commands:
                        try:
                            events=await self.client.request(action,complete=complete,timeout=4)
                            result.update(supported=True,reason='',data=parse_health(kind,[p for p in events if p.get('event','').lower()==event.lower()]))
                        except (AMIRejected,asyncio.TimeoutError):pass
                    self.state.inventory[kind]=result
                    self.state.version+=1
            except (AMIRejected,asyncio.TimeoutError):
                self.state.inventory['permissions']=dict(kind='permissions',supported=False,reason='capability_probe_unavailable',observed_at=time.time())
                self.state.version+=1
            await asyncio.sleep(120)

    async def reconciler(self):
        last = time.monotonic()
        while True:
            await asyncio.sleep(1)
            elapsed = time.monotonic() - last
            if elapsed >= self.settings.reconcile_seconds or (self.resync_requested and elapsed >= 5):
                await self.synchronize()
                last = time.monotonic()

    async def worker(self):
        tasks = []
        try:
            from sanequeue.security.organization import disabled
            if disabled():raise ConnectionError('module_disabled')
            self.client = await AsyncAMI.connect(self.settings.host, self.settings.port, self.event,
                                                tls=self.settings.tls, server_name=self.settings.server_name)
            await self.client.request('Login', Username=self.settings.user,
                                      Secret=self.settings.password, Events='call,agent,system,reporting')
            self.connected = True
            self.journeys.mark_connection(True)
            self.metrics['connections'] += 1
            self.metrics['reconnects'] = max(0, self.metrics['connections'] - 1)
            await self.synchronize()
            self.reason = 'ready'
            tasks = [asyncio.create_task(self.heartbeat()), asyncio.create_task(self.reconciler()),asyncio.create_task(self.inventory_loop()),
                     asyncio.create_task(self.client.closed.wait()),asyncio.create_task(self.watch_enabled())]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
            raise ConnectionError('ami_disconnected')
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if self.client:
                await self.client.close()

    async def watch_enabled(self):
        from sanequeue.security.organization import disabled
        while True:
            if disabled():raise ConnectionError('module_disabled')
            await asyncio.sleep(.5)

    async def session(self):
        self.generation = uuid.uuid4().hex
        self.state = QueueState()
        self.journeys = JourneyEngine()
        self.journey_seeded = False
        self.connected, self.complete, self.reason = False, False, 'synchronizing'
        tasks = [asyncio.create_task(self.renewer()), asyncio.create_task(self.publisher()),
                 asyncio.create_task(self.worker())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
            raise ConnectionError('collector_session_ended')
        finally:
            self.connected = self.complete = False
            self.journeys.mark_connection(False)
            self.reason = 'disconnected'
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                await self.store.publish(self.snapshot(), self.health())
            except Exception:
                # Redis TTL remains the fail-closed boundary when Redis is unavailable.
                pass

    async def run(self):
        delay = 1
        while True:
            from sanequeue.security.organization import disabled
            if disabled():
                await asyncio.sleep(1)
                continue
            acquired = False
            started = time.monotonic()
            try:
                acquired = await self.store.acquire()
                if acquired:
                    await self.session()
                else:
                    await asyncio.sleep(2 + random.random())
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning('collector_retry error_type=%s', type(exc).__name__)
            finally:
                if acquired:
                    try:
                        await self.store.release()
                    except Exception:
                        pass
            if time.monotonic() - started > 60:
                delay = 1
            await asyncio.sleep(random.uniform(delay * .75, delay * 1.25))
            delay = min(30, delay * 2)
