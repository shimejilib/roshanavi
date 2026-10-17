"""Launcher / project / build / dummy REST + log WebSocket routes (docs/design/launcher.md).

Kept apart from :mod:`server` to keep files small. Same conventions: pydantic
bodies with ``extra=forbid``, the ``{error: {code, message}}`` envelope via
:class:`LauncherError`, blocking work in plain ``def`` handlers (threadpool).
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, constr

from .lab import Lab
from .launcher.build import BUILD_LOG_ID
from .launcher.errors import LauncherError
from .launcher.logbuf import LogBuffer
from .launcher.schema import DummySpec, ProjectSpec, TargetSpec

LOG = logging.getLogger(__name__)

LOG_WS_PERIOD_SEC = 0.2
LOG_WS_BATCH = 1000


class _Strict(BaseModel):
    class Config:
        extra = 'forbid'


class BuildRequest(_Strict):
    package: constr(min_length=1, max_length=100)
    restart_running: bool = True


class PersistRequest(_Strict):
    name: constr(min_length=1, max_length=256)
    namespace: Optional[constr(max_length=256)] = None
    id: Optional[constr(max_length=64)] = None
    autostart: bool = False
    stop_job: bool = True


class ExportRequest(_Strict):
    directory: constr(min_length=1, max_length=1024)
    ids: List[constr(max_length=64)] = Field(default_factory=list, max_items=100)


def log_buffer(lab: Lab, log_id: str) -> LogBuffer:
    if log_id == BUILD_LOG_ID:
        return lab.launcher.builder.log
    return lab.launcher.manager.logs(log_id)


def _register_targets(app: FastAPI, lab: Lab) -> None:
    launcher = lab.launcher
    manager = launcher.manager

    @app.get('/api/targets')
    def list_targets() -> Dict[str, Any]:
        return {'targets': launcher.targets()}

    @app.post('/api/targets', status_code=201)
    def add_target(spec: TargetSpec, start: bool = False) -> Dict[str, Any]:
        return launcher.add(spec, start=start)

    @app.get('/api/targets/{target_id}')
    def get_target(target_id: str) -> Dict[str, Any]:
        return manager.get(target_id)

    @app.put('/api/targets/{target_id}')
    def put_target(target_id: str, spec: TargetSpec) -> Dict[str, Any]:
        return launcher.update(target_id, spec)

    @app.delete('/api/targets/{target_id}')
    def delete_target(target_id: str) -> Dict[str, Any]:
        return launcher.remove(target_id)

    @app.post('/api/targets/{target_id}/{action}')
    def target_action(target_id: str, action: str) -> Dict[str, Any]:
        handlers = {'start': manager.start, 'stop': manager.stop, 'restart': manager.restart}
        if action not in handlers:
            raise LauncherError('not_found', f'unknown action {action!r}', 404)
        return handlers[action](target_id)

    @app.get('/api/targets/{target_id}/logs')
    def get_logs(target_id: str, since: int = Query(0, ge=0),
                 limit: int = Query(LOG_WS_BATCH, ge=1, le=5000)) -> Dict[str, Any]:
        lines, cursor = log_buffer(lab, target_id).since(since, limit)
        return {'lines': lines, 'cursor': cursor}

    @app.delete('/api/targets/{target_id}/logs')
    def clear_logs(target_id: str) -> Dict[str, Any]:
        log_buffer(lab, target_id).clear()
        return {'cleared': target_id}


def _register_dummies(app: FastAPI, lab: Lab) -> None:
    launcher = lab.launcher

    @app.post('/api/dummies', status_code=201)
    def add_dummy(spec: DummySpec, start: bool = False) -> Dict[str, Any]:
        """Register a persistent dummy (input node); ``?start=true`` also starts it."""
        return launcher.add(spec, start=start)

    @app.put('/api/dummies/{dummy_id}')
    def put_dummy(dummy_id: str, spec: DummySpec) -> Dict[str, Any]:
        return launcher.update(dummy_id, spec)

    @app.post('/api/inject/{job_id}/persist', status_code=201)
    def persist_job(job_id: str, req: PersistRequest) -> Dict[str, Any]:
        spec = lab.injector.spec(job_id)
        target = launcher.persist_job(spec, req.name, req.namespace, req.id, req.autostart)
        if req.stop_job:
            lab.injector.stop(job_id)
        return target

    @app.post('/api/dummies/export')
    def export_dummies(req: ExportRequest) -> Dict[str, Any]:
        return launcher.export_dummies(req.directory, req.ids)


def _register_workspace(app: FastAPI, lab: Lab) -> None:
    launcher = lab.launcher

    @app.get('/api/workspace')
    def get_workspace() -> Dict[str, Any]:
        return launcher.workspace.to_dict()

    @app.post('/api/workspace/refresh')
    def refresh_workspace() -> Dict[str, Any]:
        return launcher.workspace.refresh()

    @app.get('/api/build')
    def get_build() -> Dict[str, Any]:
        return launcher.builder.status()

    @app.post('/api/build', status_code=202)
    def post_build(req: BuildRequest) -> Dict[str, Any]:
        return launcher.builder.start(req.package, req.restart_running)

    @app.delete('/api/build')
    def cancel_build() -> Dict[str, Any]:
        return launcher.builder.cancel()

    @app.get('/api/project')
    def get_project() -> Dict[str, Any]:
        return launcher.project_state()

    @app.put('/api/project')
    def put_project(spec: ProjectSpec) -> Dict[str, Any]:
        return launcher.put_project(spec)

    @app.post('/api/project/save')
    def save_project() -> Dict[str, Any]:
        return launcher.save_project()

    @app.post('/api/project/reload')
    def reload_project() -> Dict[str, Any]:
        return launcher.reload_project()


def _register_log_ws(app: FastAPI, lab: Lab) -> None:
    @app.websocket('/ws/logs/{log_id}')
    async def ws_logs(ws: WebSocket, log_id: str) -> None:
        await ws.accept()
        try:
            buffer = log_buffer(lab, log_id)
        except LauncherError as exc:
            await ws.send_json({'error': {'code': exc.code, 'message': str(exc)}})
            await ws.close(code=1008)
            return
        watcher = asyncio.ensure_future(_drain(ws))
        cursor = 0
        try:
            while not watcher.done():
                lines, next_cursor = buffer.since(cursor, LOG_WS_BATCH)
                if lines:
                    await ws.send_json({'log_id': log_id, 'lines': lines})
                cursor = next_cursor
                await asyncio.sleep(LOG_WS_PERIOD_SEC)
        except WebSocketDisconnect:
            LOG.debug('log websocket %s disconnected', log_id)
        except Exception as exc:  # send on a closing socket etc.
            LOG.info('log websocket %s ended: %s: %s', log_id, type(exc).__name__, exc)
        finally:
            watcher.cancel()


async def _drain(ws: WebSocket) -> None:
    while True:
        message = await ws.receive()
        if message.get('type') == 'websocket.disconnect':
            return


def register(app: FastAPI, lab: Lab) -> None:
    _register_targets(app, lab)
    _register_dummies(app, lab)
    _register_workspace(app, lab)
    _register_log_ws(app, lab)
