"""ASGI adapter: existing Flask authorization runs before every pushed snapshot."""
import asyncio
import json
from urllib.parse import urlsplit

from starlette.applications import Starlette
from a2wsgi import WSGIMiddleware
from starlette.routing import Mount, WebSocketRoute
from starlette.websockets import WebSocketDisconnect
from sanequeue.realtime.protocol import bounded


def create_app(flask_app, origins, *, interval=2, max_connections=100):
    allowed = frozenset(o.rstrip('/') for o in origins if o)
    for origin in allowed:
        url = urlsplit(origin)
        if url.scheme not in ('http', 'https') or not url.netloc or url.path or url.query or url.fragment or url.username:
            raise ValueError('invalid_public_origin')
    active = set()
    limiter = asyncio.Semaphore(10)

    def snapshot(cookie, origin, address):
        # Reuse the actual login/session/version/queue-scope boundary. Do not
        # trust a role, queue, username or token supplied in a WS message.
        with flask_app.test_client(use_cookies=False) as client:
            response = client.get('/api/operations', base_url=origin,
                                  headers={'Cookie': cookie}, environ_overrides={'REMOTE_ADDR':address})
            if response.status_code in (301,302,401,403):
                return None
            if response.status_code != 200:
                return {'type':'stale', 'error':'collector_unavailable'}
            return {'type':'snapshot', 'data':response.get_json()}

    async def websocket(ws):
        origin = ws.headers.get('origin', '').rstrip('/')
        if origin not in allowed:
            await ws.close(code=4403)
            return
        if len(active) >= max_connections or len(ws.headers.get('cookie', '')) > 8192:
            await ws.close(code=1013)
            return
        token = object()
        active.add(token)
        async def get_payload():
            async with limiter:
                return await asyncio.to_thread(snapshot, ws.headers.get('cookie',''), origin,
                                               ws.client.host if ws.client else 'unknown')
        receiver = None
        try:
            payload = await get_payload()
            if payload is None:
                await ws.close(code=4401)
                return
            await ws.accept()
            # No client-side subscription/action protocol. Any data frame is
            # rejected; controls must use scoped CSRF-protected HTTP endpoints.
            receiver = asyncio.create_task(ws.receive())
            while True:
                if receiver.done():
                    message = receiver.result()
                    await ws.close(code=1000 if message['type']=='websocket.disconnect' else 1008)
                    return
                body = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
                if len(body.encode()) > 512*1024:
                    await ws.close(code=1009)
                    return
                await bounded(ws.send_text(body), 3)
                done, _ = await asyncio.wait({receiver}, timeout=interval)
                if not done:
                    payload = await get_payload()
                    if payload is None:
                        await ws.close(code=4401)
                        return
        except (WebSocketDisconnect, OSError, asyncio.TimeoutError):
            pass
        finally:
            active.discard(token)
            if receiver:
                receiver.cancel()
                await asyncio.gather(receiver, return_exceptions=True)

    app = Starlette(routes=[WebSocketRoute('/ws/operations', websocket),
                            Mount('/', WSGIMiddleware(flask_app))])
    app.state.websocket_connections = active
    return app
