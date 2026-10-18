"""Launch takeover, leftover processes (#12) and registry delete / undo routes.

* ``/api/takeover``: the launch file taken over with ``--launch`` (or ``start``), the
  report of what per-node running keeps / loses, and a pending re-import after the launch
  file changed (``apply`` / ``dismiss``). Only package launch files are accepted, like the
  whole-launch import.
* ``/api/leftovers``: processes a force-killed previous server left running; ``stop`` signals
  only recorded processes that still match their fingerprint (launcher/proc_record.py).
* ``/api/registry/delete`` + ``undo``: delete roshanavi's own registrations (never source
  code or packages) and restore them for a short while.
"""

from typing import Any, Dict, List, Literal

from fastapi import FastAPI

from .lab import Lab
from .pydantic_compat import Field, StrictModel, constr

ID = constr(regex=r'^[a-z0-9][a-z0-9_\-]{0,63}$')
HEX = constr(regex=r'^[0-9a-f]{32}$')


class TakeoverStart(StrictModel):
    package: constr(min_length=1, max_length=100)
    launch_file: constr(min_length=1, max_length=128)
    args: Dict[constr(max_length=100), constr(max_length=4096)] = Field(default_factory=dict)
    mode: Literal['node', 'whole'] = 'node'
    mine: List[constr(min_length=1, max_length=256)] = Field(default_factory=list, max_items=64)


class PreviewRef(StrictModel):
    preview_id: HEX


class DeleteRequest(StrictModel):
    ids: List[ID] = Field(min_items=1, max_items=200)


class UndoRequest(StrictModel):
    undo_id: HEX


def register(app: FastAPI, lab: Lab) -> None:
    @app.get('/api/takeover')
    def takeover_status() -> Dict[str, Any]:
        return lab.takeover.status()

    @app.post('/api/takeover/start', status_code=202)
    def takeover_start(req: TakeoverStart) -> Dict[str, Any]:
        lab.takeover.configure(req.package, req.launch_file, dict(req.args), req.mode,
                               list(req.mine))
        return lab.takeover.status()

    @app.post('/api/takeover/check')
    def takeover_check() -> Dict[str, Any]:
        return lab.takeover.check()

    @app.post('/api/takeover/apply')
    def takeover_apply(req: PreviewRef) -> Dict[str, Any]:
        return lab.takeover.apply(req.preview_id)

    @app.post('/api/takeover/dismiss')
    def takeover_dismiss(req: PreviewRef) -> Dict[str, Any]:
        return lab.takeover.dismiss(req.preview_id)

    @app.get('/api/leftovers')
    def leftovers() -> Dict[str, Any]:
        return lab.launcher.leftover_state()

    @app.post('/api/leftovers/stop')
    def stop_leftovers() -> Dict[str, Any]:
        return lab.launcher.stop_leftovers()

    @app.post('/api/registry/delete')
    def delete(req: DeleteRequest) -> Dict[str, Any]:
        return lab.trash.delete(list(req.ids))

    @app.post('/api/registry/undo')
    def undo(req: UndoRequest) -> Dict[str, Any]:
        return lab.trash.undo(req.undo_id)
