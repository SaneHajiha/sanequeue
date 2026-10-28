"""Privacy, stale state, bounded Redis reads and live WS authorization tests."""
import concurrent.futures
import json
import unittest
from unittest.mock import Mock

from flask import Flask, jsonify, session
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from qpanel.privacy import public_queue_snapshot
from sanequeue.api.state import StateReader, StateUnavailable, legacy_queues, scoped_channels, journey_projection
from sanequeue.gateway.app import create_app


def fixture():
    return {'generation':'g', 'queues':{
        'a':{'params':{'completed':'2','servicelevelperf':'0'}, 'members':{},
             'entries':{'private-uid':{'channel':'PJSIP/private-123','calleridnum':'09123456789','uniqueid':'private-uid','waiting_since':90}}},
        'b':{'params':{}, 'members':{}, 'entries':{}}},
        'channels':{'x':{'queues':['a','b'],'channel':'PJSIP/secret-b'}},
        'journeys':{'connected':True,'records':[
            {'id':'opaque-a','queues':['a'],'caller':'09123456789','destination':'09129999999','timeline':[{'state':'transfer','detail':'09129999999'}]},
            {'id':'opaque-cross','queues':['a','b'],'caller':'private-b','timeline':[]}]}}


class StateAPITests(unittest.TestCase):
    def test_many_concurrent_readers_coalesce_redis_and_return_independent_values(self):
        redis = Mock()
        redis.mget.return_value = [json.dumps(fixture()),json.dumps({'generation':'g','connected':True,'complete':True})]
        # Thread scheduling can exceed the cache TTL on a busy test host.
        # Freeze time to test coalescing independently from wall-clock load.
        reader = StateReader(redis,'test',clock=lambda:100)
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
            values = list(pool.map(lambda _:reader.read(),range(100)))
        self.assertEqual(redis.mget.call_count,1)
        values[0][0]['queues'].clear()
        self.assertEqual(len(values[1][0]['queues']),2)
        redis.mget.side_effect = OSError('redis unavailable')
        with self.assertRaises(StateUnavailable):reader.read(fresh=True)
        with self.assertRaises(StateUnavailable):reader.read()

    def test_scope_keys_and_free_form_journey_details_do_not_leak(self):
        state = fixture()
        queues = {'a':legacy_queues(state,now=100)['a']}
        public = public_queue_snapshot(queues)
        journeys = journey_projection(state,['a'],False)
        body = json.dumps(dict(queues=public,journeys=journeys))
        for secret in ('private-uid','PJSIP/private-123','09123456789','09129999999','opaque-cross','private-b'):
            self.assertNotIn(secret,body)
        self.assertEqual(public['a']['ServicelevelPerf'],'0')
        self.assertEqual(next(iter(public['a']['entries'].values()))['Wait'],'10')
        self.assertFalse(scoped_channels(state,['a']))
        self.assertIn('x',scoped_channels(state,['a','b']))

    def test_missing_health_and_new_generation_are_stale(self):
        redis=Mock()
        for health in (None, {'generation':'other','connected':True,'complete':True},
                       {'generation':'g','connected':True,'complete':False}):
            redis.mget.return_value=[json.dumps(fixture()), json.dumps(health) if health else None]
            with self.subTest(health=health),self.assertRaises(StateUnavailable):StateReader(redis,'test').read()


class WebSocketTests(unittest.TestCase):
    def setUp(self):
        self.flask=Flask('ws-test');self.flask.secret_key='synthetic-test-secret'
        self.enabled=True
        self.scope=['a']
        @self.flask.get('/api/operations')
        def data():
            if session.get('user')!='viewer' or not self.enabled:return jsonify(error='login_required'),401
            state=fixture()
            return jsonify(queues=public_queue_snapshot({q:v for q,v in legacy_queues(state).items() if q in self.scope}),
                           call_journeys=journey_projection(state,self.scope),data_source='ami-live')
        with self.flask.test_client() as client:
            with client.session_transaction() as s:s['user']='viewer'
            self.cookie=client.get_cookie('session').value
        self.asgi=create_app(self.flask,['http://testserver'],interval=.01,max_connections=2)

    def headers(self,**changes):
        return dict({'origin':'http://testserver','cookie':'session='+self.cookie},**changes)

    def test_authenticated_push_masks_data_and_rechecks_revoked_session(self):
        with TestClient(self.asgi) as client:
            with client.websocket_connect('/ws/operations',headers=self.headers()) as ws:
                message=ws.receive_json()
                self.assertEqual(message['type'],'snapshot')
                self.assertEqual(list(message['data']['queues']),['a'])
                self.assertNotIn('09123456789',json.dumps(message))
                self.enabled=False
                with self.assertRaises(WebSocketDisconnect) as error:
                    for _ in range(3):ws.receive_json()
                self.assertEqual(error.exception.code,4401)
        self.assertFalse(self.asgi.state.websocket_connections)

    def test_wrong_origin_and_forged_cookie_are_rejected(self):
        with TestClient(self.asgi) as client:
            for headers,code in [(self.headers(origin='https://evil.example'),4403),
                                 (self.headers(cookie='session=forged'),4401)]:
                with self.subTest(code=code),self.assertRaises(WebSocketDisconnect) as error:
                    with client.websocket_connect('/ws/operations',headers=headers):pass
                self.assertEqual(error.exception.code,code)

    def test_scope_revocation_and_client_action_frames(self):
        with TestClient(self.asgi) as client:
            with client.websocket_connect('/ws/operations',headers=self.headers()) as ws:
                ws.receive_json();self.scope=[]
                for _ in range(3):
                    result=ws.receive_json()
                    if not result['data']['queues']:break
                self.assertFalse(result['data']['queues'])
                ws.send_json({'action':'Hangup','queue':'b'})
                with self.assertRaises(WebSocketDisconnect) as error:
                    for _ in range(3):ws.receive_json()
                self.assertEqual(error.exception.code,1008)
