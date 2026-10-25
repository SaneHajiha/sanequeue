"""Bounded asyncio AMI transport with one reader and correlated requests."""
import asyncio
import re
import uuid

MAX_FRAME = 262144
READ_ACTIONS = frozenset({'Login', 'Logoff', 'Ping', 'QueueStatus', 'CoreShowChannels',
    'ListCommands','PJSIPShowEndpoints','PJSIPShowContacts','PJSIPShowRegistrationsOutbound',
    'SIPpeers','SIPshowregistry','ParkedCalls'})


async def bounded(awaitable, timeout):
    """A deadline that preserves external cancellation during completion races.

    Older supported Python versions can lose cancellation in wait_for when the
    inner operation completes concurrently. Never suppress a daemon shutdown.
    """
    future = asyncio.ensure_future(awaitable)
    try:
        done, _ = await asyncio.wait({future}, timeout=timeout)
        if not done:
            raise asyncio.TimeoutError()
        return future.result()
    finally:
        if not future.done():
            future.cancel()
        await asyncio.gather(future, return_exceptions=True)


class AMIRejected(RuntimeError):
    """An action was rejected; raw server messages are intentionally not logged."""


def encode(fields):
    if fields.get('Action') not in READ_ACTIONS:
        raise ValueError('collector_action_not_allowed')
    for key, value in fields.items():
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9]*', key):
            raise ValueError('invalid_ami_key')
        if any(c in str(value) for c in ('\r', '\n', '\x00')):
            raise ValueError('invalid_ami_value')
    return (''.join(f'{k}: {v}\r\n' for k, v in fields.items()) + '\r\n').encode()


def decode(raw):
    result = {}
    for line in raw.decode('utf-8', 'replace').split('\r\n'):
        key, sep, value = line.partition(':')
        if sep:
            result[key.strip().lower()] = value.lstrip()[:2048]
    return result


class AsyncAMI:
    def __init__(self, reader, writer, on_event):
        self.reader, self.writer, self.on_event = reader, writer, on_event
        self.pending = {}
        self.closed = asyncio.Event()
        self.task = None
        self.sequence = 0

    @classmethod
    async def connect(cls, host, port, on_event, *, tls=None, server_name=None, timeout=8):
        opening = asyncio.ensure_future(asyncio.open_connection(
            host, port, ssl=tls, server_hostname=server_name if tls else None,
            limit=MAX_FRAME))
        try:
            reader, writer = await bounded(opening, timeout)
        except BaseException:
            # Cancellation can coincide with the socket becoming ready.
            if opening.done() and not opening.cancelled() and opening.exception() is None:
                _, writer = opening.result()
                writer.close()
                try:
                    await bounded(writer.wait_closed(), 2)
                except (OSError, asyncio.TimeoutError):
                    pass
            raise
        try:
            greeting = await bounded(reader.readuntil(b'\r\n'), timeout)
            if not greeting.startswith(b'Asterisk Call Manager/'):
                raise ConnectionError('not_an_ami_endpoint')
            obj = cls(reader, writer, on_event)
            obj.task = asyncio.create_task(obj._read_loop())
            return obj
        except BaseException:
            writer.close()
            try:
                await bounded(writer.wait_closed(), 2)
            except (OSError, asyncio.TimeoutError):
                pass
            raise

    async def _read_loop(self):
        try:
            while True:
                raw = await self.reader.readuntil(b'\r\n\r\n')
                self.sequence += 1
                packet = decode(raw)
                packet['_sequence'] = self.sequence
                pending = self.pending.get(packet.get('actionid'))
                if pending:
                    future, complete, packets = pending
                    if future.done():
                        continue
                    if packet.get('response') == 'Error':
                        future.set_exception(AMIRejected('ami_action_rejected'))
                    else:
                        if len(packets) >= 50000:
                            raise BufferError('snapshot_event_limit')
                        packets.append(packet)
                        if (complete and packet.get('event', '').lower() == complete.lower()) or (
                                not complete and 'response' in packet):
                            future.set_result(packets)
                elif packet.get('event') and (packet['event'].lower()=='originateresponse' or not packet.get('actionid', '').startswith('sq-')):
                    # Late replies to our expired/cancelled snapshots are not live events.
                    # Preserve events tagged by other AMI clients (supervisor actions).
                    self.on_event(packet)
                if self.sequence % 100 == 0:
                    await asyncio.sleep(0)
        except (Exception, asyncio.CancelledError):
            # Parser/budget failures also force a clean reconnect and resync.
            pass
        finally:
            self.closed.set()
            for future, _, _ in self.pending.values():
                if not future.done():
                    future.set_exception(ConnectionError('ami_disconnected'))
            self.writer.close()

    async def request(self, action, *, complete=None, timeout=10, **fields):
        if self.closed.is_set():
            raise ConnectionError('ami_disconnected')
        if len(self.pending) >= 8:
            raise BufferError('too_many_pending_actions')
        ident = 'sq-' + uuid.uuid4().hex
        payload = encode(dict(Action=action, ActionID=ident, **fields))
        future = asyncio.get_running_loop().create_future()
        self.pending[ident] = (future, complete, [])
        try:
            self.writer.write(payload)
            await bounded(self.writer.drain(), timeout)
            return await bounded(future, timeout)
        finally:
            self.pending.pop(ident, None)
            if not future.done():
                future.cancel()

    async def close(self):
        self.writer.close()
        if self.task and self.task is not asyncio.current_task():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        try:
            await bounded(self.writer.wait_closed(), 2)
        except (OSError, asyncio.TimeoutError):
            pass
