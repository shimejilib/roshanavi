"""FastAPI application: REST + WebSocket API over a running :class:`Lab`.

Blocking handlers are plain ``def`` (FastAPI runs them in its threadpool); the
WebSocket loops only read cached snapshots. Errors use the envelope
``{"error": {"code": ..., "message": ...}}``.
"""

import asyncio
import functools
import logging
import os
import time
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Literal, Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import (data_kinds, msgutil, security, server_functions, server_launch_import,
               server_launcher, server_media, server_nodes, server_resources, server_scenarios,
               server_takeover, server_tracing, server_transforms)
from .api_errors import ApiError, parse_window
from .asyncutil import run_cleanup
from .echo import MAX_SAMPLE_BYTES, EchoError
from .files import FileAccessError, list_files
from .jobs import InjectError, InjectSpec
from .lab import Lab
from .launcher.errors import LauncherError
from .media.errors import MediaError
from .media.options import MediaOptions
from .pydantic_compat import Field, StrictModel, confloat, conint, constr, validation_errors

LOG = logging.getLogger(__name__)

LIVE_PERIOD_SEC = 1.0
ECHO_PERIOD_SEC = 0.1  # echo is throttled to <= 10 Hz


class QosModel(StrictModel):
    reliability: Literal['reliable', 'best_effort'] = 'reliable'
    durability: Literal['volatile', 'transient_local'] = 'volatile'
    depth: conint(ge=1, le=1000) = 10


class InjectRequest(StrictModel):
    mode: Literal['once', 'periodic', 'stream', 'bag', 'media']
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
    media: Optional[MediaOptions] = None

    def to_spec(self) -> InjectSpec:
        return InjectSpec(mode=self.mode, topic=self.topic, type=self.type, payload=self.payload,
                          rate_hz=self.rate_hz, count=self.count, source=self.source,
                          loop=self.loop, qos=self.qos.model_dump(), bag_rate=self.bag_rate,
                          bag_topics=tuple(self.topics),
                          media=self.media.model_dump() if self.media else None)


class MonitorRequest(StrictModel):
    enabled: bool


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
                     LauncherError, MediaError, ApiError):
        app.add_exception_handler(exc_type, _domain_error)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_req: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = 'not_found' if exc.status_code == 404 else 'http_error'
        return _error(exc.status_code, code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_req: Request, exc: RequestValidationError) -> JSONResponse:
        parts = ['.'.join(str(p) for p in e['loc']) + ': ' + e['msg']
                 for e in validation_errors(exc)]
        return _error(422, 'validation_error', '; '.join(parts))


@functools.lru_cache(maxsize=1)
def _cached_types() -> List[str]:
    return msgutil.list_types()


@functools.lru_cache(maxsize=1)
def _cached_kinds() -> Dict[str, Any]:
    return data_kinds.catalog()


def _register_rest(app: FastAPI, lab: Lab) -> None:
    @app.get('/api/health')
    def get_health() -> Dict[str, Any]:
        return {'status': 'ok'}

    @app.get('/api/graph')
    def get_graph() -> Dict[str, Any]:
        snapshot, digest = lab.graph.snapshot()
        return {**snapshot, 'hash': digest}

    @app.get('/api/traffic')
    def get_traffic(window: Optional[str] = None) -> Dict[str, Any]:
        return {'topics': lab.traffic_view(parse_window(window)),
                'measurement': lab.traffic.status()}

    @app.put('/api/traffic/{topic:path}/monitor')
    def put_monitor(topic: str, req: MonitorRequest) -> Dict[str, Any]:
        topic = '/' + topic.strip('/')
        lab.set_topic_monitoring(topic, req.enabled)
        return {'topic': topic, 'enabled': req.enabled}

    @app.get('/api/types')
    def get_types() -> Dict[str, Any]:
        # groups: 詳細設定モード order (common -> workspace -> by package), never A-Z only.
        packages = [p['name'] for p in lab.launcher.workspace.to_dict()['packages']
                    if p['origin'] == 'workspace']
        types = _cached_types()
        return {'types': types, 'groups': data_kinds.type_groups(types, packages)}

    @app.get('/api/data-kinds')
    def get_data_kinds() -> Dict[str, Any]:
        return _cached_kinds()

    @app.get('/api/types/{pkg}/msg/{name}/template')
    def get_template(pkg: str, name: str) -> Dict[str, Any]:
        type_name = f'{pkg}/msg/{name}'
        return {'type': type_name, 'template': msgutil.template(type_name)}

    @app.post('/api/inject', status_code=201)
    def post_inject(req: InjectRequest) -> Dict[str, Any]:
        job = lab.injector.start(req.to_spec())
        # Record mode: the operation becomes a scenario step (docs/design/scenarios.md).
        lab.scenarios.recorder.note_op({'kind': 'inject', 'job_id': job['id'],
                                        'request': req.model_dump(exclude_none=True)})
        return job

    @app.get('/api/inject')
    def list_inject() -> Dict[str, Any]:
        return {'jobs': lab.injector.list()}

    @app.get('/api/inject/{job_id}')
    def get_inject(job_id: str) -> Dict[str, Any]:
        return lab.injector.get(job_id)

    @app.delete('/api/inject/{job_id}')
    def delete_inject(job_id: str) -> Dict[str, Any]:
        job = lab.injector.stop(job_id)
        lab.scenarios.recorder.note_op({'kind': 'inject_stop', 'job_id': job_id})
        return job

    @app.post('/api/inject/{job_id}/pause')
    def pause_inject(job_id: str) -> Dict[str, Any]:
        return lab.injector.set_paused(job_id, True)

    @app.post('/api/inject/{job_id}/resume')
    def resume_inject(job_id: str) -> Dict[str, Any]:
        return lab.injector.set_paused(job_id, False)

    @app.get('/api/files')
    def get_files() -> Dict[str, Any]:
        return {'data_dir': lab.data_dir, 'files': list_files(lab.data_dir)}

    @app.get('/api/echo/{topic:path}/sample')
    def echo_sample(topic: str) -> Dict[str, Any]:
        """Latest message of a topic that is being echoed, untruncated up to a size cap.

        For the transform preview, whose expressions must see whole arrays, not the 32-item
        display copy. ``msg`` is null when the topic is not echoed (yet) or nothing arrived.
        """
        topic = '/' + topic.strip('/')
        seq, msg, capped, size = lab.echo.latest_sample(topic)
        return {'topic': topic, 'seq': seq, 'msg': msg, 'capped': capped, 'size_bytes': size,
                'max_bytes': MAX_SAMPLE_BYTES}


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
        try:
            window = parse_window(ws.query_params.get('window'))
        except ApiError as exc:
            await ws.send_json({'error': {'code': exc.code, 'message': str(exc)}})
            await ws.close(code=1008)
            return
        state = {'hash': None}

        async def push() -> None:
            snapshot, digest = lab.graph.snapshot()
            traffic = lab.traffic_view(window)
            payload: Dict[str, Any] = {'traffic': traffic,
                                       'measurement': lab.traffic.status(),
                                       'tracing': lab.tracing_status(traffic),
                                       'server_time': time.time(),
                                       'jobs': lab.injector.list(),
                                       'targets': lab.launcher.targets(),
                                       'build': lab.launcher.builder.status(),
                                       'recording': lab.recorder.status()['active'],
                                       'resources': lab.resources.live()}
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
            await run_cleanup(lab.echo.release, topic)


def create_app(lab: Lab, static_dir: Optional[str] = None,
               live_period: float = LIVE_PERIOD_SEC, allowed_hosts: Iterable[str] = (),
               allowed_origins: Iterable[str] = ()) -> FastAPI:
    app = FastAPI(title='roshanavi', version='0.1.0')
    security.install(app, allowed_hosts, allowed_origins)
    _install_error_handlers(app)
    _register_rest(app, lab)
    server_launcher.register(app, lab)
    server_media.register(app, lab)
    server_nodes.register(app, lab)
    server_launch_import.register(app, lab)
    server_tracing.register(app, lab)
    server_transforms.register(app, lab)
    server_functions.register(app, lab)
    server_scenarios.register(app, lab)
    server_resources.register(app, lab)
    server_takeover.register(app, lab)
    _register_ws(app, lab, live_period)
    if static_dir and os.path.isfile(os.path.join(static_dir, 'index.html')):
        app.mount('/', StaticFiles(directory=static_dir, html=True), name='static')
    else:
        if static_dir:
            LOG.info('static dir %s has no index.html; serving API only', static_dir)

        @app.get('/')
        def index() -> Dict[str, Any]:
            return {'name': 'roshanavi', 'ui': None,
                    'api': ['/api/health', '/api/graph', '/api/traffic', '/api/types',
                            '/api/data-kinds', '/api/inject',
                            '/api/files', '/api/tracing', '/api/targets', '/api/workspace', '/api/build',
                            '/api/project', '/api/echo/{topic}/sample', '/api/dummies',
                            '/api/functions', '/api/media/types',
                            '/api/scenarios', '/api/scenario-runs', '/api/scenario-record',
                            '/api/recordings', '/api/nodes/{node}/parameters',
                            '/api/resources', '/api/resources/history', '/ws/resources',
                            '/api/interfaces/{pkg}/{kind}/{name}', '/ws/live', '/ws/echo/{topic}',
                            '/ws/logs/{log_id}', '/ws/capture', '/ws/view/{topic}',
                            '/ws/scenarios']}
    return app
