"""Pure-ASGI guard against DNS rebinding and cross-site requests to the local API.

* Host header must be in the allowlist (HTTP and WebSocket) -> 403 / close 1008.
* WebSocket ``Origin``, when present, must be an http(s) origin on an allowed host.
* Mutating REST methods with a body must be ``application/json`` -> 415, which
  blocks ``text/plain`` / form CSRF posts.
"""

import logging
from typing import Any, Dict, Iterable, Optional, Set
from urllib.parse import urlsplit

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

LOG = logging.getLogger(__name__)

LOOPBACK_HOSTS = ('localhost', '127.0.0.1', '[::1]')
MUTATING_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})
WS_POLICY_VIOLATION = 1008


def hostname(value: str) -> str:
    """Lower-cased host without port; IPv6 keeps its brackets."""
    value = value.strip().lower()
    if value.startswith('['):
        return value[:value.find(']') + 1] if ']' in value else value
    return value.rsplit(':', 1)[0] if ':' in value else value


def origin_host(origin: str) -> Optional[str]:
    """Host of an http(s) origin, or None if it is not one (e.g. ``null``, ``file://``)."""
    try:
        parts = urlsplit(origin)
        host = parts.hostname
    except ValueError:
        return None
    if parts.scheme not in ('http', 'https') or not host:
        return None
    return f'[{host}]' if ':' in host else host.lower()


class SecurityMiddleware:
    def __init__(self, app: ASGIApp, allowed_hosts: Iterable[str] = (),
                 allowed_origins: Iterable[str] = ()):
        self.app = app
        self.hosts: Set[str] = {hostname(h) for h in (*LOOPBACK_HOSTS, *allowed_hosts)}
        self.origins: Set[str] = {o.strip().lower().rstrip('/') for o in allowed_origins}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] not in ('http', 'websocket'):
            await self.app(scope, receive, send)
            return
        headers = {k.decode('latin-1').lower(): v.decode('latin-1')
                   for k, v in scope['headers']}
        rejection = self._check(scope, headers)
        if rejection is None:
            await self.app(scope, receive, send)
            return
        status, code, message = rejection
        LOG.warning('rejected %s %s: %s', scope['type'], scope.get('path'), message)
        if scope['type'] == 'websocket':
            await send({'type': 'websocket.close', 'code': WS_POLICY_VIOLATION})
            return
        body = {'error': {'code': code, 'message': message}}
        await JSONResponse(status_code=status, content=body)(scope, receive, send)

    def _check(self, scope: Scope, headers: Dict[str, str]) -> Optional[tuple]:
        if hostname(headers.get('host', '')) not in self.hosts:
            return 403, 'forbidden_host', 'Host header not allowed (see --allowed-host)'
        if scope['type'] == 'websocket':
            return self._check_origin(headers.get('origin'))
        return self._check_content_type(scope['method'], headers)

    def _check_origin(self, origin: Optional[str]) -> Optional[tuple]:
        if origin is None:
            return None  # non-browser client
        host = origin_host(origin)
        if origin.strip().lower().rstrip('/') in self.origins:
            return None
        if host is None or host not in self.hosts:
            return 403, 'forbidden_origin', 'Origin not allowed (see --allowed-origin)'
        return None

    @staticmethod
    def _check_content_type(method: str, headers: Dict[str, str]) -> Optional[tuple]:
        if method not in MUTATING_METHODS:
            return None
        has_body = headers.get('content-length', '0').strip() not in ('', '0') \
            or 'transfer-encoding' in headers
        media_type = headers.get('content-type', '').split(';')[0].strip().lower()
        if has_body and media_type != 'application/json':
            return 415, 'unsupported_media_type', 'Content-Type must be application/json'
        return None


def install(app: Any, allowed_hosts: Iterable[str] = (),
            allowed_origins: Iterable[str] = ()) -> None:
    app.add_middleware(SecurityMiddleware, allowed_hosts=tuple(allowed_hosts),
                       allowed_origins=tuple(allowed_origins))
