"""Media routes: type detection, browser capture / viewer WebSockets, recordings.

Same conventions as :mod:`server`: pydantic bodies with ``extra=forbid``, the
``{error: {code, message}}`` envelope (MediaError is registered there), and
blocking work off the event loop. WebSockets pass the security middleware
(Host / Origin) like every other route.
"""

import asyncio
import logging
import threading
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, ValidationError, constr

from .jobs import InjectError, InjectSpec, validate_topic
from .lab import Lab
from .media import adapters
from .media.capture import CaptureJob, CaptureStart
from .media.errors import MediaError
from .media.factory import choose_type, type_info
from .media.viewer import VIEW_MAX_FPS

LOG = logging.getLogger(__name__)

START_TIMEOUT_SEC = 10.0
STATS_PERIOD_SEC = 1.0
AUDIO_VIEW_PERIOD_SEC = 0.1
WS_ERROR_CLOSE = 4400  # application close code: the error was sent as JSON first
_capture_lock = threading.Lock()  # "one capture per topic" check + registration


class RecordRequest(BaseModel):
    topics: List[constr(min_length=1, max_length=256)] = Field(..., min_items=1, max_items=100)
    name: constr(max_length=40) = ''

    class Config:
        extra = 'forbid'


def _error_body(exc: Exception) -> Dict[str, Any]:
    return {'error': {'code': getattr(exc, 'code', 'error'), 'message': str(exc)}}


def _register_rest(app: FastAPI, lab: Lab) -> None:
    @app.get('/api/media/types')
    def media_types(topic: Optional[str] = Query(None, max_length=256)) -> Dict[str, Any]:
        return type_info(lab.runtime, topic)

    @app.get('/api/recordings')
    def list_recordings() -> Dict[str, Any]:
        return {'recordings': lab.recorder.list(), **lab.recorder.status()}

    @app.post('/api/recordings', status_code=201)
    def start_recording(req: RecordRequest) -> Dict[str, Any]:
        return lab.recorder.start(req.topics, req.name)

    @app.post('/api/recordings/stop')
    def stop_recording() -> Dict[str, Any]:
        return lab.recorder.stop()

    @app.delete('/api/recordings/{name}')
    def delete_recording(name: str) -> Dict[str, Any]:
        return lab.recorder.delete(name)


def start_capture(lab: Lab, start: CaptureStart) -> CaptureJob:
    """Validate, pick the type (topic endpoints first) and register the capture job."""
    topic = validate_topic(start.topic)
    adapter = adapters.get(choose_type(lab.runtime, topic, start.type))
    period = start.chunk_samples / start.sample_rate if start.kind == 'audio' else 1 / start.fps
    spec = InjectSpec(mode='capture', topic=topic, type=adapter.type_name,
                      rate_hz=round(1.0 / period, 3),
                      qos={'reliability': start.reliability, 'durability': 'volatile',
                           'depth': 10})
    job = CaptureJob(spec, lab.runtime, adapter, start)
    with _capture_lock:
        if any(j.spec.mode == 'capture' and j.spec.topic == topic
               for j in lab.injector.active_jobs()):
            raise MediaError('capture_busy', f'{topic} is already being captured', 409)
        lab.injector.register(job, check_capacity=True)
    LOG.info('capture %s started: %s -> %s (%s)', job.id, start.kind, topic, adapter.type_name)
    return job


async def _fail(ws: WebSocket, exc: Exception) -> None:
    try:
        await ws.send_json(_error_body(exc))
        await ws.close(code=WS_ERROR_CLOSE)
    except (WebSocketDisconnect, RuntimeError) as send_exc:
        LOG.debug('could not report websocket error: %s', send_exc)


async def _receive_start(ws: WebSocket) -> CaptureStart:
    raw = await asyncio.wait_for(ws.receive_json(), timeout=START_TIMEOUT_SEC)
    try:
        return CaptureStart.parse_obj(raw)
    except ValidationError as exc:
        parts = ['.'.join(str(p) for p in e['loc']) + ': ' + e['msg'] for e in exc.errors()]
        raise MediaError('invalid_request', '; '.join(parts)) from exc


async def _capture_loop(ws: WebSocket, job: CaptureJob) -> None:
    last_stats = time.monotonic()
    while job.active:
        message = await ws.receive()
        if message.get('type') == 'websocket.disconnect':
            return
        data = message.get('bytes')
        if data is not None:
            await run_in_threadpool(job.feed, data)
        elif message.get('text') and '"stop"' in message['text']:
            return
        if time.monotonic() - last_stats >= STATS_PERIOD_SEC:
            last_stats = time.monotonic()
            info = job.to_dict()
            await ws.send_json({'event': 'stats', 'sent': info['sent'],
                                'dropped': info['dropped']})
    await ws.send_json({'event': 'stopped'})


def _register_capture(app: FastAPI, lab: Lab) -> None:
    @app.websocket('/ws/capture')
    async def ws_capture(ws: WebSocket) -> None:
        await ws.accept()
        job: Optional[CaptureJob] = None
        try:
            start = await _receive_start(ws)
            job = await run_in_threadpool(start_capture, lab, start)
            await ws.send_json({'event': 'ready', 'job_id': job.id, 'topic': job.spec.topic,
                                'type': job.spec.type, 'companions': job.companion_topics()})
            await _capture_loop(ws, job)
        except (MediaError, InjectError) as exc:
            LOG.info('capture rejected: %s', exc)
            await _fail(ws, exc)
        except asyncio.TimeoutError:
            await _fail(ws, MediaError('invalid_request', 'no start message received'))
        except WebSocketDisconnect:
            LOG.debug('capture websocket disconnected')
        except Exception as exc:  # keep the reason visible, always stop the job
            LOG.exception('capture failed')
            await _fail(ws, MediaError('capture_failed', f'{type(exc).__name__}: {exc}'))
        finally:
            if job is not None and job.finish('stopped'):
                LOG.info('capture %s stopped (%d sent)', job.id, job.sent)


async def _view_loop(ws: WebSocket, step: Callable[[], Awaitable[None]], period: float) -> None:
    """Run ``step`` every ``period`` until the client goes away."""
    async def drain() -> None:
        while (await ws.receive()).get('type') != 'websocket.disconnect':
            pass
    watcher = asyncio.ensure_future(drain())
    try:
        while not watcher.done():
            await step()
            await asyncio.sleep(period)
    except (WebSocketDisconnect, RuntimeError) as exc:
        LOG.debug('viewer closed: %s', exc)
    finally:
        watcher.cancel()


def _image_step(ws: WebSocket, lab: Lab, topic: str) -> Callable[[], Awaitable[None]]:
    state = {'seq': 0}

    async def step() -> None:
        seq, frame = await run_in_threadpool(lab.viewer.latest_image, topic, state['seq'])
        state['seq'] = seq
        if frame is not None:
            await ws.send_json({'event': 'image', 'seq': seq, 'width': frame.width,
                                'height': frame.height})
            await ws.send_bytes(frame.data)
    return step


def _audio_step(ws: WebSocket, lab: Lab, topic: str) -> Callable[[], Awaitable[None]]:
    state = {'seq': 0}

    async def step() -> None:
        seq, chunk = await run_in_threadpool(lab.viewer.audio_since, topic, state['seq'])
        state['seq'] = seq
        if chunk is not None:
            await ws.send_json({'event': 'audio', 'seq': seq, 'sample_rate': chunk.sample_rate,
                                'samples': len(chunk.data) // 2})
            await ws.send_bytes(chunk.data)
    return step


def _register_viewer(app: FastAPI, lab: Lab) -> None:
    @app.websocket('/ws/view/{topic:path}')
    async def ws_view(ws: WebSocket, topic: str,
                      sample_rate: int = Query(16000, ge=8000, le=192000),
                      channels: int = Query(1, ge=1, le=8)) -> None:
        topic = '/' + topic.strip('/')
        await ws.accept()
        try:
            info = await run_in_threadpool(lab.viewer.acquire, topic, sample_rate, channels)
        except MediaError as exc:
            await _fail(ws, exc)
            return
        try:
            await ws.send_json({'event': 'ready', 'topic': topic, **info})
            if info['kind'] == 'image':
                await _view_loop(ws, _image_step(ws, lab, topic), 1.0 / VIEW_MAX_FPS)
            else:
                await _view_loop(ws, _audio_step(ws, lab, topic), AUDIO_VIEW_PERIOD_SEC)
        except MediaError as exc:
            await _fail(ws, exc)
        finally:
            await run_in_threadpool(lab.viewer.release, topic)


def register(app: FastAPI, lab: Lab) -> None:
    _register_rest(app, lab)
    _register_capture(app, lab)
    _register_viewer(app, lab)
