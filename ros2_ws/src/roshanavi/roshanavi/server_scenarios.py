"""Scenario routes (docs/design/scenarios.md, docs/design/api.md).

- ``GET /api/scenarios``: project + example scenario files (by id ``project:<file>`` /
  ``example:<file>``); ``GET/PUT/DELETE /api/scenarios/{id}``, ``POST /api/scenarios``
  (save a form spec or raw YAML; validated with line numbers), ``POST /api/scenarios/validate``.
- ``POST /api/scenarios/{id}/run`` (one at a time, async), ``GET /api/scenario-runs``
  (history + current), ``GET /api/scenario-runs/{run_id}``,
  ``POST /api/scenario-runs/{run_id}/cancel``.
- Record mode: ``POST/DELETE/GET /api/scenario-record``, ``POST /api/scenario-record/measure``.
- ``/ws/scenarios``: the running scenario's progress and the recording timeline.

Every route sits behind the Host / Origin / Content-Type middleware (security.py).
"""

import asyncio
import logging
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool

from .lab import Lab
from .pydantic_compat import Field, StrictModel, confloat, constr
from .scenario.recorder import RecordError
from .scenario.schema import ScenarioSchemaError, to_raw
from .scenario.store import StoreError

LOG = logging.getLogger(__name__)

WS_PERIOD_SEC = 0.25
MAX_YAML = 512 * 1024


class _Strict(StrictModel):
    pass


class SaveRequest(_Strict):
    spec: Optional[Dict[str, Any]] = None
    yaml: Optional[constr(max_length=MAX_YAML)] = None
    file: Optional[constr(regex=r'^[A-Za-z0-9_][A-Za-z0-9_.-]{0,100}\.ya?ml$')] = None
    overwrite: bool = False


class EditRequest(_Strict):
    spec: Optional[Dict[str, Any]] = None
    yaml: Optional[constr(max_length=MAX_YAML)] = None


class RecordRequest(_Strict):
    watch: List[constr(min_length=1, max_length=256)] = Field(..., max_items=8)


class MeasureRequest(_Strict):
    kind: Literal['rate', 'throughput', 'latency']
    start: confloat(ge=0)
    end: confloat(gt=0)
    topic: Optional[constr(max_length=256)] = None
    input: Optional[constr(max_length=256)] = None
    output: Optional[constr(max_length=256)] = None
    match: Literal['header.stamp', 'order'] = 'header.stamp'


def schema_payload(exc: ScenarioSchemaError) -> Dict[str, Any]:
    return {'error': {'code': exc.code, 'message': str(exc), 'errors': exc.errors}}


def register(app: FastAPI, lab: Lab) -> None:  # noqa: C901 - one function per route group
    service = lab.scenarios
    store, recorder = service.store, service.recorder

    from fastapi.responses import JSONResponse

    @app.exception_handler(ScenarioSchemaError)
    async def _schema_error(_req: Any, exc: ScenarioSchemaError) -> JSONResponse:
        return JSONResponse(status_code=422, content=schema_payload(exc))

    for exc_type in (StoreError, RecordError):
        async def _domain(_req: Any, exc: Exception) -> JSONResponse:
            return JSONResponse(status_code=getattr(exc, 'status', 400), content={
                'error': {'code': getattr(exc, 'code', 'error'), 'message': str(exc)}})
        app.add_exception_handler(exc_type, _domain)

    @app.get('/api/scenarios')
    def list_scenarios() -> Dict[str, Any]:
        history = service.history()
        last: Dict[str, Any] = {}
        for item in history:
            last.setdefault(item.get('scenario_id'), item)
        items = [{**s, 'last_result': last.get(s['id'])} for s in store.list()]
        return {'project_dir': store.project_dir(), 'items': items, 'running': service.running}

    @app.post('/api/scenarios/validate')
    def validate_scenario(req: EditRequest) -> Dict[str, Any]:
        try:
            scenario, text = store.render(req.spec, req.yaml)
        except ScenarioSchemaError as exc:
            return {'ok': False, 'errors': exc.errors, 'message': str(exc)}
        return {'ok': True, 'errors': [], 'spec': to_raw(scenario), 'yaml': text}

    @app.post('/api/scenarios', status_code=201)
    def create_scenario(req: SaveRequest) -> Dict[str, Any]:
        return store.save(None, req.spec, req.yaml, req.file, req.overwrite)

    @app.get('/api/scenarios/{scenario_id}')
    def get_scenario(scenario_id: str) -> Dict[str, Any]:
        return store.get(scenario_id)

    @app.put('/api/scenarios/{scenario_id}')
    def put_scenario(scenario_id: str, req: EditRequest) -> Dict[str, Any]:
        return store.save(scenario_id, req.spec, req.yaml, overwrite=True)

    @app.delete('/api/scenarios/{scenario_id}')
    def delete_scenario(scenario_id: str) -> Dict[str, Any]:
        return store.delete(scenario_id)

    @app.post('/api/scenarios/{scenario_id}/run', status_code=202)
    def run_scenario(scenario_id: str) -> Dict[str, Any]:
        return service.run(scenario_id)

    @app.get('/api/scenario-runs')
    def list_runs() -> Dict[str, Any]:
        return {'runs': service.history(), 'current': service.current(),
                'running': service.running}

    @app.get('/api/scenario-runs/{run_id}')
    def get_run(run_id: str) -> Dict[str, Any]:
        current = service.current()
        if current is not None and current.get('run_id') == run_id:
            return current
        return service.results.get(run_id)

    @app.post('/api/scenario-runs/{run_id}/cancel')
    def cancel_run(run_id: str) -> Dict[str, Any]:
        return service.cancel(run_id)

    @app.post('/api/scenario-record', status_code=201)
    def start_record(req: RecordRequest) -> Dict[str, Any]:
        return recorder.start(req.watch)

    @app.delete('/api/scenario-record')
    def stop_record(discard: bool = False) -> Dict[str, Any]:
        return recorder.discard() if discard else recorder.stop()

    @app.get('/api/scenario-record')
    def get_record(since: int = Query(0, ge=0)) -> Dict[str, Any]:
        return {**recorder.status(), 'events': recorder.events(since)}

    @app.post('/api/scenario-record/measure')
    def measure(req: MeasureRequest) -> Dict[str, Any]:
        return recorder.measure(req.kind, req.start, req.end, req.topic, req.input, req.output,
                                req.match)

    @app.websocket('/ws/scenarios')
    async def ws_scenarios(ws: WebSocket) -> None:
        await ws.accept()
        state = {'seq': 0, 'session': None, 'run': None}
        try:
            while True:
                status = recorder.status()
                session = status['session']
                session_id = session['id'] if session else None
                if session_id != state['session']:
                    state['session'], state['seq'] = session_id, 0
                events = await run_in_threadpool(recorder.events, state['seq'])
                if events:
                    state['seq'] = events[-1]['seq']
                current = service.current()
                payload: Dict[str, Any] = {'record': {**status, 'events': events},
                                           'running': service.running}
                if current is not None and (service.running or current != state['run']):
                    payload['run'] = current
                    state['run'] = current
                await ws.send_json(payload)
                try:
                    message = await asyncio.wait_for(ws.receive(), timeout=WS_PERIOD_SEC)
                    if message.get('type') == 'websocket.disconnect':
                        return
                except asyncio.TimeoutError:
                    pass
        except WebSocketDisconnect:
            LOG.debug('scenario websocket disconnected')
        except Exception as exc:  # e.g. send on a socket that just closed
            LOG.info('scenario websocket ended: %s: %s', type(exc).__name__, exc)
