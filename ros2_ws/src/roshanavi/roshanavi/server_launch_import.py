"""Launch decomposition import routes (docs/design/launcher.md).

``preview`` evaluates the launch file in a time-limited subprocess and returns
the proposed targets (cached server-side under ``preview_id``); ``commit``
registers the chosen ones (autosaved like every launcher change).
"""

from typing import Any, Dict, List, Literal

from fastapi import FastAPI
from pydantic import BaseModel, Field, conint, constr

from .lab import Lab
from .launch_import.importer import Source


class _Strict(BaseModel):
    class Config:
        extra = 'forbid'


class PreviewRequest(_Strict):
    source: Source
    args: Dict[constr(max_length=100), constr(max_length=4096)] = Field(default_factory=dict)


class CommitRequest(_Strict):
    preview_id: constr(regex=r'^[0-9a-f]{32}$')
    mode: Literal['nodes', 'whole'] = 'nodes'
    indices: List[conint(ge=0, le=10_000)] = Field(default_factory=list, max_items=500)
    role: Literal['mine', 'dependency'] = 'dependency'
    autostart: bool = False


def register(app: FastAPI, lab: Lab) -> None:
    @app.post('/api/launch-import/preview')
    def preview(req: PreviewRequest) -> Dict[str, Any]:
        return lab.importer.preview(req.source, dict(req.args))

    @app.post('/api/launch-import/commit', status_code=201)
    def commit(req: CommitRequest) -> Dict[str, Any]:
        return lab.importer.commit(req.preview_id, req.mode, req.indices, req.role,
                                   req.autostart)
