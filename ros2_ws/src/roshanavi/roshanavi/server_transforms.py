"""Transform node (変換ノード) and project-switch routes (docs/design/nodes.md, docs/design/launcher.md).

- ``POST /api/transforms`` (``?start=true``) / ``PUT /api/transforms/{id}``: register or
  change a transform node. Start / stop / delete / logs use the generic
  ``/api/targets/{id}`` routes (transforms live in the same registry).
- ``POST /api/transforms/preview``: dry run with the node's evaluator on sample
  messages; always 200 with ``{ok, passed, output, errors[]}`` so the editor can
  show problems at their fields.
- ``GET /api/projects`` / ``POST /api/projects/open``: the example and data
  project files, and switching to one by its listed id.
"""

from typing import Any, Dict

from fastapi import FastAPI
from pydantic import BaseModel, Field, constr, validator

from .lab import Lab
from .launcher.schema import TransformSpec
from .transform.preview import preview

MAX_SAMPLES = 8


class _Strict(BaseModel):
    class Config:
        extra = 'forbid'


class PreviewRequest(_Strict):
    spec: Dict[str, Any]
    samples: Dict[constr(max_length=32), Dict[str, Any]] = Field(default_factory=dict)

    @validator('samples')
    def _few_samples(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        if len(value) > MAX_SAMPLES:
            raise ValueError(f'at most {MAX_SAMPLES} samples')
        return value


class OpenProjectRequest(_Strict):
    id: constr(min_length=1, max_length=512)


def register(app: FastAPI, lab: Lab) -> None:
    launcher = lab.launcher
    catalog = lab.catalog

    @app.post('/api/transforms', status_code=201)
    def add_transform(spec: TransformSpec, start: bool = False) -> Dict[str, Any]:
        return launcher.add(spec, start=start)

    @app.put('/api/transforms/{transform_id}')
    def put_transform(transform_id: str, spec: TransformSpec) -> Dict[str, Any]:
        return launcher.update(transform_id, spec)

    @app.post('/api/transforms/preview')
    def preview_transform(req: PreviewRequest) -> Dict[str, Any]:
        return preview(req.spec, req.samples)

    @app.get('/api/projects')
    def list_projects() -> Dict[str, Any]:
        return catalog.list(launcher.project.path)

    @app.post('/api/projects/open')
    def open_project(req: OpenProjectRequest) -> Dict[str, Any]:
        state = launcher.open_project(catalog.resolve(req.id))
        if state['error'] is None:  # a project that failed to load is not what to start with next time
            catalog.remember(req.id)
        return state
