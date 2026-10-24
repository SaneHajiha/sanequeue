"""Opt-in integration tests against a dedicated real Redis database, never PBX."""
import asyncio
import os
import unittest
import uuid

from redis.asyncio import Redis
from sanequeue.realtime.store import RedisStateStore


@unittest.skipUnless(os.getenv('SANEQUEUE_TEST_REDIS_URL'), 'Dedicated test Redis not configured')
class RedisFencingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.redis = Redis.from_url(os.environ['SANEQUEUE_TEST_REDIS_URL'], decode_responses=True)
        name = 'test_' + uuid.uuid4().hex
        self.old = RedisStateStore(self.redis, name, lease_ms=120)
        self.new = RedisStateStore(self.redis, name, lease_ms=120)

    async def asyncTearDown(self):
        await self.redis.delete(*self.old.keys[:3])
        await self.redis.close()

    async def test_expired_owner_cannot_publish_renew_or_release_new_owner(self):
        self.assertTrue(await self.old.acquire())
        self.assertFalse(await self.new.acquire())
        await asyncio.sleep(.2)
        self.assertTrue(await self.new.acquire())
        health = dict(generation='new', revision=1, connected=True, complete=True)
        self.assertFalse(await self.old.publish({'generation': 'old'}, health))
        self.assertFalse(await self.old.renew())
        self.assertFalse(await self.old.release())
        self.assertTrue(await self.new.publish({'generation': 'new'}, health))
        self.assertFalse((await self.new.read())['stale'])

    async def test_generation_mismatch_and_missing_health_fail_closed(self):
        self.assertTrue(await self.old.acquire())
        health = dict(generation='new', revision=1, connected=True, complete=True)
        await self.old.publish({'generation': 'old'}, health)
        self.assertTrue((await self.old.read())['stale'])
        await self.old.publish({'generation': 'new'}, health)
        await self.redis.delete(self.old.keys[2])
        self.assertTrue((await self.old.read())['stale'])
