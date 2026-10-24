"""Fenced Redis lease and expiring private state; no public HTTP endpoint."""
import json
import re
import uuid

RENEW = "if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('PEXPIRE',KEYS[1],ARGV[2]) else return 0 end"
RELEASE = "if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('DEL',KEYS[1]) else return 0 end"
PUBLISH = """
if redis.call('GET',KEYS[1])~=ARGV[1] then return 0 end
if ARGV[2]~='' then redis.call('SET',KEYS[2],ARGV[2],'EX',30)
else redis.call('EXPIRE',KEYS[2],30) end
redis.call('SET',KEYS[3],ARGV[3],'EX',15)
if ARGV[4]~='' then redis.call('PUBLISH',KEYS[4],ARGV[4]) end
return 1
"""


class RedisStateStore:
    def __init__(self, redis, pbx_id, *, lease_ms=15000):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,48}', pbx_id):
            raise ValueError('invalid_pbx_id')
        self.redis, self.lease_ms = redis, lease_ms
        self.owner = uuid.uuid4().hex
        prefix = 'sanequeue:{' + pbx_id + '}:'
        self.keys = [prefix + x for x in ('lease', 'state', 'health', 'changed')]

    async def acquire(self):
        return bool(await self.redis.set(self.keys[0], self.owner, nx=True, px=self.lease_ms))

    async def renew(self):
        return bool(await self.redis.eval(RENEW, 1, self.keys[0], self.owner, self.lease_ms))

    async def release(self):
        return await self.redis.eval(RELEASE, 1, self.keys[0], self.owner)

    async def publish(self, state, health, *, changed=True):
        body = json.dumps(state, separators=(',', ':'), ensure_ascii=False) if state is not None else ''
        if len(body.encode()) > 16 * 1024 * 1024:
            raise BufferError('redis_state_payload_limit')
        metadata = json.dumps(health, separators=(',', ':'))
        notice = json.dumps({'generation': health['generation'], 'revision': health['revision']}) if changed else ''
        return bool(await self.redis.eval(PUBLISH, 4, *self.keys, self.owner, body, metadata, notice))

    async def read(self):
        """Private consumers must still authorize and redact every field."""
        state, health = await self.redis.mget(self.keys[1:3])
        body = json.loads(state) if state else None
        meta = json.loads(health) if health else {}
        live = bool(body and meta.get('connected') and meta.get('complete') and
                    body.get('generation') == meta.get('generation'))
        return {'state': body, 'health': meta, 'stale': not live}
