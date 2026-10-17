"""FastAPI application: REST + WebSocket API over a running :class:`Lab`.

Blocking handlers are plain ``def`` (FastAPI runs them in its threadpool); the
WebSocket loops only read cached snapshots. Errors use the envelope
``{"error": {"code": ..., "message": ...}}``.
"""

import asyncio
import functools
import logging
import os
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Literal, Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, confloat, conint, constr
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import msgutil, security, server_launcher
from .echo import EchoError
from .files import FileAccessError, list_files
from .jobs import InjectError, InjectSpec
from .lab import Lab
from .launcher.errors import LauncherError

LOG = logging.getLogger(__name__)

LIVE_PERIOD_SEC = 1.0
ECHO_PERIOD_SEC = 0.1  # echo is throttled to <= 10 Hz


class QosModel(BaseModel):
    reliability: Literal['reliable', 'best_effort'] = 'reliable'
    durability: Literal['volatile', 'transient_local'] = 'volatile'
    depth: conint(ge=1, le=1000) = 10

    class Config:
        extra = 'forbid'


class InjectRequest(BaseModel):
    mode: Literal['once', 'periodic', 'stream', 'bag']
    topic: Optional[constr(max_length=256)] = None
    type: Optional[constr(max_length=256)] = None
    payload: Optional[Dict[str, Any]] = None
    rate_hz: Optional[confloat(gt=0, le=1000)] = None
    count: Optional[conint(ge=1, le=10_000_000)] = None
    source: Optional[constr(max_length=1024)] = None
    loop: bool = False
    qos: QosModel = Field(default_factory=QosModel)
    bag_rate: confloat(gt=0, le=100) = 1.0
    topics: List[constr(max_length=256)] = Field(default_factory=list, max_items=100)

    class Config:
        extra = 'forbid'

    def to_spec(self) -> InjectSpec:
        return InjectSpec(mode=self.mode, topic=self.topic, type=self.type, payload=self.payload,
                          rate_hz=self.rate_hz, count=self.count, source=self.source,
                          loop=self.loop, qos=self.qos.dict(), bag_rate=self.bag_rate,
                          bag_topics=tuple(self.topics))


class MonitorRequest(BaseModel):
    enabled: bool

    class Config:
        extra = 'forbid'


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={'error': {'code': code, 'message': message}})


def _status_for(exc: Exception) -> int:
    status = getattr(exc, 'status', None)
    if status:
        return status
    return 404 if getattr(exc, 'code', '') in ('not_found', 'unknown_type') else 400


def _install_error_handlers(app: FastAPI) -> None:
    async def _domain_error(_req: Request, exc: Exception) -> JSONResponse:
        status = _status_for(exc)
        (LOG.error if status >= 500 else LOG.info)('request failed: %s', exc)
        return _error(status, getattr(exc, 'code', 'error'), str(exc))

    for exc_type in (InjectError, EchoError, msgutil.MsgUtilError, FileAccessError,
                     LauncherError):
        app.add_exception_handler(exc_type, _domain_error)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_req: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = 'not_found' if exc.status_code == 404 else 'http_error'
        return _error(exc.status_code, code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_req: Request, exc: RequestValidationError) -> JSONResponse:
        parts = ['.'.join(str(p) for p in e['loc']) + ': ' + e['msg'] for e in exc.errors()]
        return _error(422, 'validation_error', '; '.join(parts))


@functools.lru_cache(maxsize=1)
def _cached_types() -> List[str]:
    return msgutil.list_types()


def _register_rest(app: FastAPI, lab: Lab) -> None:
    @app.get('/api/graph')
    def get_graph() -> Dict[str, Any]:
        snapshot, digest = lab.graph.snapshot()
        return {**snapshot, 'hash': digest}

    @app.get('/api/traffic')
    def get_traffic() -> Dict[str, Any]:
        return {'topics': lab.traffic_view()}

    @app.put('/api/traffic/{topic:path}/monitor')
    def put_monitor(topic: str, req: MonitorRequest) -> Dict[str, Any]:
        topic = '/' + topic.strip('/')
        lab.traffic.set_monitored(topic, req.enabled)
        return {'topic': topic, 'enabled': req.enabled}

    @app.get('/api/types')
    def get_types() -> Dict[str, Any]:
        return {'types': _cached_types()}

    @app.get('/api/types/{pkg}/msg/{name}/template')
    def get_template(pkg: str, name: str) -> Dict[str, Any]:
        type_name = f'{pkg}/msg/{name}'
        return {'type': type_name, 'template': msgutil.template(type_name)}

    @app.post('/api/inject', status_code=201)
    def post_inject(req: InjectRequest) -> Dict[str, Any]:
        return lab.injector.start(req.to_spec())

    @app.get('/api/inject')
    def list_inject() -> Dict[str, Any]:
        return {'jobs': lab.injector.list()}

    @app.get('/api/inject/{job_id}')
    def get_inject(job_id: str) -> Dict[str, Any]:
        return lab.injector.get(job_id)

    @app.delete('/api/inject/{job_id}')
    def delete_inject(job_id: str) -> Dict[str, Any]:
        return lab.injector.stop(job_id)

    @app.get('/api/files')
    def get_files() -> Dict[str, Any]:
        return {'data_dir': lab.data_dir, 'files': list_files(lab.data_dir)}


async def _drain(ws: WebSocket) -> None:
    """Consume client frames until the client disconnects (detects closed sockets)."""
    while True:
        message = await ws.receive()
        if message.get('type') == 'websocket.disconnect':
            return


async def _run_until_disconnect(ws: WebSocket, loop_body: Callable[[], Awaitable[None]],
                                period: float) -> None:
    watcher = asyncio.ensure_future(_drain(ws))
    try:
        while not watcher.done():
            await loop_body()
            await asyncio.sleep(period)
    except WebSocketDisconnect:
        LOG.debug('websocket disconnected')
    except Exception as exc:  # e.g. send on a socket that just closed
        LOG.info('websocket loop ended: %s: %s', type(exc).__name__, exc)
    finally:
        watcher.cancel()


def _register_ws(app: FastAPI, lab: Lab, live_period: float) -> None:
    @app.websocket('/ws/live')
    async def ws_live(ws: WebSocket) -> None:
        await ws.accept()
        state = {'hash': None}

        async def push() -> None:
            snapshot, digest = lab.graph.snapshot()
            payload: Dict[str, Any] = {'traffic': lab.traffic_view(),
                                       'jobs': lab.injector.list(),
                                       'targets': lab.launcher.targets(),
                                       'build': lab.launcher.builder.status()}
            if digest != state['hash']:
                payload['graph'] = {**snapshot, 'hash': digest}
                state['hash'] = digest
            await ws.send_json(payload)
        await _run_until_disconnect(ws, push, live_period)

    @app.websocket('/ws/echo/{topic:path}')
    async def ws_echo(ws: WebSocket, topic: str) -> None:
        topic = '/' + topic.strip('/')
        await ws.accept()
        try:
            type_name = await run_in_threadpool(lab.echo.acquire, topic)
        except EchoError as exc:
            await ws.send_json({'error': {'code': exc.code, 'message': str(exc)}})
            await ws.close(code=1008)
            return
        state = {'seq': 0}

        async def push() -> None:
            seq, msg = lab.echo.latest(topic)
            if msg is not None and seq != state['seq']:
                state['seq'] = seq
                await ws.send_json({'topic': topic, 'type': type_name, 'seq': seq, 'msg': msg})
        try:
            await _run_until_disconnect(ws, push, ECHO_PERIOD_SEC)
        finally:
            await run_in_threadpool(lab.echo.release, topic)


def create_app(lab: Lab, static_dir: Optional[str] = None,
               live_period: float = LIVE_PERIOD_SEC, allowed_hosts: Iterable[str] = (),
               allowed_origins: Iterable[str] = ()) -> FastAPI:
    app = FastAPI(title='roshanavi', version='0.1.0')
    security.install(app, allowed_hosts, allowed_origins)
    _install_error_handlers(app)
    _register_rest(app, lab)
    server_launcher.register(app, lab)
    _register_ws(app, lab, live_period)
    if static_dir and os.path.isfile(os.path.join(static_dir, 'index.html')):
        app.mount('/', StaticFiles(directory=static_dir, html=True), name='static')
    else:
        if static_dir:
            LOG.info('static dir %s has no index.html; serving API only', static_dir)

        @app.get('/')
        def index() -> Dict[str, Any]:
            return {'name': 'roshanavi', 'ui': None,
                    'api': ['/api/graph', '/api/traffic', '/api/types', '/api/inject',
                            '/api/files', '/api/targets', '/api/workspace', '/api/build',
                            '/api/project', '/api/dummies', '/ws/live', '/ws/echo/{topic}',
                            '/ws/logs/{log_id}']}
    return app
