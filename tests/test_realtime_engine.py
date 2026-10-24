"""Collector protocol, reconnect, synchronization and state boundary tests."""
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sanequeue.realtime.protocol import AsyncAMI, AMIRejected, bounded, encode, decode
from sanequeue.realtime.state import QueueState, StateOverflow, agent_state
from sanequeue.realtime.config import Settings
from sanequeue.realtime.collector import Collector


def packet(**fields):
    return (''.join(f'{k}: {v}\r\n' for k, v in fields.items()) + '\r\n').encode()


class StateTests(unittest.TestCase):
    def event(self, kind, **fields):
        self.state.ingest(dict(Event=kind, **fields))

    def setUp(self):
        self.now = 1000
        self.state = QueueState(clock=lambda: self.now)

    def test_case_insensitive_snapshot_and_member_name(self):
        self.state.ingest({'EVENT': 'QueueParams', 'QUEUE': 'sales', 'ServiceLevelPerf': '0', 'ServiceLevel': '20'})
        self.event('QueueMember', Queue='sales', Location='SIP/101', MemberName='Agent', Status='1')
        q = self.state.snapshot()['queues']['sales']
        self.assertEqual(q['params']['servicelevelperf'], '0')
        self.assertEqual(q['members']['SIP/101']['name'], 'Agent')
        self.assertTrue(q['members']['SIP/101']['derived']['ready'])

    def test_leave_does_not_hang_up_channel(self):
        self.event('Newchannel', Uniqueid='u1', Linkedid='call', Channel='PJSIP/101-1')
        self.event('QueueCallerJoin', Queue='sales', Uniqueid='u1', Channel='PJSIP/101-1')
        self.event('QueueCallerJoin', Queue='sales', Uniqueid='u1', Channel='PJSIP/101-1')
        self.assertEqual(len(self.state.queues['sales']['entries']), 1)
        self.event('QueueCallerLeave', Queue='sales', Uniqueid='u1')
        self.assertFalse(self.state.queues['sales']['entries'])
        self.assertIn('u1', self.state.channels)

    def test_abandon_is_deduplicated_and_ring_no_answer_is_not_abandon(self):
        self.event('QueueParams', Queue='sales', Abandoned='2', Completed='4')
        for _ in range(2):
            self.event('QueueCallerAbandon', Queue='sales', Uniqueid='u1')
        self.event('AgentRingNoAnswer', Queue='sales', Uniqueid='u2')
        self.assertEqual(self.state.queues['sales']['params']['abandoned'], '3')
        self.event('AgentComplete', Queue='sales', Uniqueid='u3', _skip_counter='1')
        self.assertEqual(self.state.queues['sales']['params']['completed'], '4')

    def test_bridge_and_transfer_preserve_other_active_legs(self):
        for uid, channel in [('caller', 'PJSIP/trunk-1'), ('local', 'Local/101@from-queue-1;1'), ('agent', 'PJSIP/101-2')]:
            self.event('Newchannel', Uniqueid=uid, Linkedid='root', Channel=channel)
        self.event('QueueCallerJoin', Queue='sales', Uniqueid='caller')
        self.event('DialBegin', Uniqueid='caller', DestUniqueid='local')
        for uid in ('local', 'agent'):
            self.event('BridgeEnter', Uniqueid=uid, BridgeUniqueid='bridge')
        self.assertEqual(self.state.channels['agent']['queues'], ['sales'])
        self.event('BlindTransfer', TransfererUniqueid='local', TransfereeUniqueid='agent')
        self.event('Hangup', Uniqueid='local', Channel='Local/101@from-queue-1;1')
        self.assertIn('agent', self.state.channels)
        self.assertEqual(self.state.channels['agent']['last_relationship_event'], 'blindtransfer')
        self.event('Hangup', Uniqueid='agent', Channel='PJSIP/101-2')
        self.assertFalse(self.state.bridges)

    def test_pause_ringing_and_wrap_up_are_distinct(self):
        for status, expected in [('1', 'available'), ('2', 'busy'), ('6', 'ringing'), ('8', 'hold'), ('4', 'offline')]:
            with self.subTest(status=status):
                m = agent_state({'status': status, 'paused': '1'}, self.now)
                self.assertEqual(m['activity'], expected)
                self.assertFalse(m['ready'])
        self.event('QueueMember', Queue='sales', Interface='PJSIP/1', Status='1', LastCall='995', Wrapuptime='10')
        m = self.state.snapshot()['queues']['sales']['members']['PJSIP/1']
        self.assertEqual(m['derived']['activity'], 'wrap_up')
        revision = self.state.version
        self.now += 6
        self.state.expire_timers()
        self.assertGreater(self.state.version, revision)
        self.assertTrue(self.state.snapshot()['queues']['sales']['members']['PJSIP/1']['derived']['ready'])

    def test_bounded_state_and_snapshot_copy(self):
        s = QueueState(max_records=1)
        s.ingest({'event': 'Newchannel', 'uniqueid': '1'})
        with self.assertRaises(StateOverflow):
            s.ingest({'event': 'Newchannel', 'uniqueid': '2'})
        snap = s.snapshot()
        snap['channels'].clear()
        self.assertIn('1', s.channels)

    def test_hangup_cleans_old_channel_only_entries(self):
        self.event('QueueEntry', Queue='sales', Channel='SIP/101-1')
        self.event('Hangup', Uniqueid='u1', Channel='SIP/101-1')
        self.assertFalse(self.state.queues['sales']['entries'])

    def test_bridge_switch_and_late_leave_do_not_detach_current_bridge(self):
        self.event('BridgeEnter', Uniqueid='u', Channel='PJSIP/1-1', BridgeUniqueid='old')
        self.event('BridgeEnter', Uniqueid='u', BridgeUniqueid='new')
        self.event('BridgeLeave', Uniqueid='u', BridgeUniqueid='old')
        self.assertNotIn('old', self.state.bridges)
        self.assertEqual(self.state.channels['u']['bridge'], 'new')
        self.event('Hangup', Uniqueid='u')
        self.assertFalse(self.state.bridges)
        self.assertEqual(self.state.records, 0)

    def test_hold_takes_priority_over_in_call_and_agent_called_keeps_state_timer(self):
        self.assertEqual(agent_state({'status': '8', 'incall': '1'}, self.now)['activity'], 'hold')
        self.event('QueueMember', Queue='q', Interface='SIP/1', Status='6')
        since = self.state.queues['q']['members']['SIP/1']['state_observed_since']
        self.now += 10
        self.event('AgentCalled', Queue='q', Interface='SIP/1')
        self.assertEqual(self.state.queues['q']['members']['SIP/1']['state_observed_since'], since)

    def test_rename_replaces_channel_index_and_reentry_has_new_counter_episode(self):
        self.event('Newchannel', Uniqueid='u', Channel='Local/1;1')
        self.event('Rename', Uniqueid='u', Channel='Local/1;1', Newname='PJSIP/1-2')
        self.assertNotIn('Local/1;1', self.state.by_channel)
        self.assertEqual(self.state.by_channel['PJSIP/1-2'], 'u')
        self.event('QueueParams', Queue='q', Completed='0')
        for _ in range(2):
            self.event('QueueCallerJoin', Queue='q', Uniqueid='u')
            self.event('AgentConnect', Queue='q', Uniqueid='u')
            self.event('AgentComplete', Queue='q', Uniqueid='u')
            self.event('AgentComplete', Queue='q', Uniqueid='u')
        self.assertEqual(self.state.queues['q']['params']['completed'], '2')


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.actions = []
        self.connections = 0
        self.writers = set()
        self.drop_pings = False
        self.server = await asyncio.start_server(self.serve, '127.0.0.1', 0)
        self.port = self.server.sockets[0].getsockname()[1]
        self.client = None

    async def serve(self, reader, writer):
        self.connections += 1
        self.writers.add(writer)
        writer.write(b'Asterisk Call Manager/9.0\r\n')
        try:
            while True:
                req = decode(await reader.readuntil(b'\r\n\r\n'))
                action, ident = req['action'], req['actionid']
                self.actions.append(action)
                if action == 'Login':
                    writer.write(packet(Response='Success', ActionID=ident))
                elif action == 'QueueStatus':
                    writer.write(packet(Response='Success', ActionID=ident, EventList='start'))
                    writer.write(packet(Event='QueueParams', Queue='sales', Completed='4', Abandoned='0', ActionID=ident))
                    writer.write(packet(Event='QueueMember', Queue='sales', Interface='SIP/101', Status='1', ActionID=ident))
                    writer.write(packet(Event='QueueStatusComplete', ActionID=ident))
                elif action == 'CoreShowChannels':
                    writer.write(packet(Response='Success', ActionID=ident))
                    writer.write(packet(Event='CoreShowChannelsComplete', ActionID=ident))
                elif action == 'Ping' and not self.drop_pings:
                    writer.write(packet(Response='Success', Ping='Pong', ActionID=ident))
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            self.writers.discard(writer)
            writer.close()

    async def asyncTearDown(self):
        if self.client:
            await self.client.close()
        for writer in list(self.writers):
            writer.close()
        self.server.close()
        await self.server.wait_closed()
        await asyncio.sleep(0)

    async def test_one_connection_handles_multiple_actions_and_events(self):
        events = []
        self.client = await AsyncAMI.connect('127.0.0.1', self.port, events.append)
        await self.client.request('Login', Username='readonly', Secret='test')
        data = await self.client.request('QueueStatus', complete='QueueStatusComplete')
        writer = next(iter(self.writers))
        writer.write(packet(Event='QueueMemberPause', Queue='sales', Interface='SIP/101', Paused='1'))
        await writer.drain()
        await self.client.request('Ping')
        self.assertEqual(self.connections, 1)
        self.assertTrue(any(p.get('event') == 'QueueParams' for p in data))
        self.assertEqual(events[0]['paused'], '1')
        self.assertFalse(self.client.pending)

    async def test_timeout_cleans_pending_requests(self):
        self.drop_pings = True
        self.client = await AsyncAMI.connect('127.0.0.1', self.port, lambda e: None)
        with self.assertRaises(asyncio.TimeoutError):
            await self.client.request('Ping', timeout=.03)
        self.assertFalse(self.client.pending)

    async def test_connection_loss_completes_waiters(self):
        self.drop_pings = True
        self.client = await AsyncAMI.connect('127.0.0.1', self.port, lambda e: None)
        task = asyncio.create_task(self.client.request('Ping', timeout=1))
        await asyncio.sleep(.01)
        next(iter(self.writers)).close()
        with self.assertRaises(ConnectionError):
            await task

    async def test_collector_sync_and_many_store_readers_do_not_poll_ami(self):
        store = MemoryStore()
        settings = Settings('127.0.0.1', self.port, 'readonly', 'secret', 'unused', publish_seconds=.02)
        collector = Collector(settings, store)
        task = asyncio.create_task(collector.session())
        try:
            for _ in range(100):
                if store.health.get('complete'):
                    break
                await asyncio.sleep(.01)
            self.assertTrue(store.health['complete'])
            reads = await asyncio.gather(*(store.read() for _ in range(100)))
            self.assertEqual(self.actions.count('QueueStatus'), 1)
            self.assertEqual(self.connections, 1)
            self.assertEqual(len(reads), 100)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.assertFalse(store.health['connected'])

    async def test_lease_loss_interrupts_slow_initial_connection(self):
        store = MemoryStore()
        store.lease_ms = 30
        store.valid = False
        cancelled = asyncio.Event()
        async def connect(*args, **kwargs):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        collector = Collector(Settings('x', 1, 'u', 'p', 'unused'), store)
        with patch('sanequeue.realtime.collector.AsyncAMI.connect', side_effect=connect):
            with self.assertRaises(ConnectionError):
                await asyncio.wait_for(collector.session(), .5)
        self.assertTrue(cancelled.is_set())

    async def test_resync_journal_counter_barrier_and_late_hangup(self):
        collector = Collector(Settings('x', 1, 'u', 'p', 'unused'), MemoryStore())
        class SnapshotClient:
            async def request(self, action, **kwargs):
                if action == 'QueueStatus':
                    collector.event({'event': 'AgentComplete', 'queue': 'q', 'uniqueid': 'before', '_sequence': 1})
                    collector.event({'event': 'AgentComplete', 'queue': 'q', 'uniqueid': 'after', '_sequence': 4})
                    return [{'event': 'QueueParams', 'queue': 'q', 'completed': '5', '_sequence': 2}]
                collector.event({'event': 'Hangup', 'uniqueid': 'gone', '_sequence': 6})
                return [{'event': 'CoreShowChannel', 'uniqueid': 'gone', 'channel': 'SIP/1-1', '_sequence': 5}]
        collector.client = SnapshotClient()
        await collector.synchronize()
        self.assertEqual(collector.state.queues['q']['params']['completed'], '6')
        self.assertNotIn('gone', collector.state.channels)
        self.assertTrue(collector.complete)

    async def test_cancellation_racing_with_completion_is_not_swallowed(self):
        for _ in range(100):
            future = asyncio.get_running_loop().create_future()
            task = asyncio.create_task(bounded(future, 1))
            await asyncio.sleep(0)
            future.set_result('done')
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

    async def test_repeated_shutdown_during_initial_ping_does_not_hang(self):
        for _ in range(30):
            collector = Collector(Settings('127.0.0.1', self.port, 'u', 'p', 'unused', publish_seconds=.001), MemoryStore())
            task = asyncio.create_task(collector.session())
            for attempt in range(100):
                if collector.complete:
                    break
                await asyncio.sleep(.001)
            self.assertTrue(collector.complete)
            task.cancel()
            await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 1)
            self.assertTrue(collector.client.closed.is_set())

    async def test_cancel_at_socket_open_completion_closes_new_transport(self):
        class Writer:
            closed = False
            def close(self):
                self.closed = True
            async def wait_closed(self):
                pass
        writer = Writer()
        async def opening(*args, **kwargs):
            return object(), writer
        first = True
        async def cancel_after_completion(awaitable, timeout):
            nonlocal first
            result = await bounded(awaitable, timeout)
            if first:
                first = False
                raise asyncio.CancelledError()
            return result
        with patch('sanequeue.realtime.protocol.asyncio.open_connection', side_effect=opening), patch(
                'sanequeue.realtime.protocol.bounded', side_effect=cancel_after_completion):
            with self.assertRaises(asyncio.CancelledError):
                await AsyncAMI.connect('unused', 1, lambda event: None)
        self.assertTrue(writer.closed)


class MemoryStore:
    lease_ms = 15000
    def __init__(self):
        self.valid, self.state, self.health = True, {}, {}
    async def acquire(self):
        return self.valid
    async def renew(self):
        return self.valid
    async def release(self):
        return True
    async def publish(self, state, health, **kwargs):
        if state is not None:
            self.state = state
        self.health = health
        return self.valid
    async def read(self):
        return {'state': self.state, 'health': self.health}


class BoundaryTests(unittest.TestCase):
    def test_injection_and_write_actions_are_rejected(self):
        for values in [dict(Action='Originate'), dict(Action='Command'),
                       dict(Action='Login', Username='x\r\nAction: Hangup'),
                       {'Action': 'Login', 'Bad\nKey': 'x'}]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                encode(values)

    def test_secret_settings_are_not_in_repr(self):
        settings = Settings('pbx', 5038, 'user', 'private-password', 'redis://:private-token@redis')
        self.assertNotIn('private-password', repr(settings))
        self.assertNotIn('private-token', repr(settings))
