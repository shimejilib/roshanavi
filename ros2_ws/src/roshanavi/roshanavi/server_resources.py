"""Resource monitoring routes (docs/design/resources.md). Read-only: GET + one WebSocket.

Handlers only copy the sampler's latest snapshot (built on its own thread), so nothing
here blocks the event loop. The Host / Origin middleware covers every route.
"""

import asyncio
import logging
from typing import Any, Dict, Optional

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect

from .api_errors import ApiError
from .lab import Lab

LOG = logging.getLogger(__name__)

WS_PERIOD_SEC = 1.0


def _check_node(node: str) -> str:
    stripped = (node or '').strip('/')
    if not stripped or len(stripped) > 255:
        raise ApiError('invalid_request', 'node must be a ROS node id such as /talker')
    return '/' + stripped


def register(app: FastAPI, lab: Lab) -> None:
    service = lab.resources

    @app.get('/api/resources')
    def get_resources() -> Dict[str, Any]:
        return service.snapshot()

    @app.get('/api/resources/history')
    def get_history(node: Optional[str] = Query(None, max_length=256),
                    scope: Optional[str] = Query(None, pattern='^(self|host)$')) -> Dict[str, Any]:
        """Last 5 minutes (1 Hz) of one node, of roshanavi itself (default) or of the PC."""
        if scope == 'host':
            return {'scope': 'host', 'history': service.host_history()}
        if node is not None:
            node = _check_node(node)
            snap = service.snapshot()
            return {'node': node, 'history': service.history(node),
                    'current': (snap.get('nodes') or {}).get(node),
                    'connections': [c for c in snap.get('connections') or ()
                                    if node in (c.get('nodes') or ())]}
        return {'scope': 'self', 'history': service.history(None)}

    @app.websocket('/ws/resources')
    async def ws_resources(ws: WebSocket) -> None:
        await ws.accept()
        last = None
        try:
            while True:
                snap = service.snapshot()
                if snap is not last:
                    last = snap
                    await ws.send_json(snap)
                try:
                    message = await asyncio.wait_for(ws.receive(), timeout=WS_PERIOD_SEC)
                    if message.get('type') == 'websocket.disconnect':
                        return
                except asyncio.TimeoutError:
                    pass
        except WebSocketDisconnect:
            LOG.debug('resources websocket disconnected')
        except Exception as exc:  # e.g. send on a socket that just closed
            LOG.info('resources websocket ended: %s: %s', type(exc).__name__, exc)
