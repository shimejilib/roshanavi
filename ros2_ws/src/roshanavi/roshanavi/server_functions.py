"""Function node (関数ノード) routes (docs/design/nodes.md).

- ``GET /api/functions/modules``: Python modules of the workspace packages.
- ``GET /api/functions/module?name=pkg.mod``: its top-level functions and signatures,
  read with :mod:`ast` (user code is never imported in the server).
- ``POST /api/functions`` (``?start=true``) / ``PUT /api/functions/{id}``: register or change
  a function node. Start / stop / delete / logs use ``/api/targets/{id}``; the node's
  live status (calls, errors with file:line, reloads) is ``function_status`` of the target.
- ``POST /api/functions/{id}/export-code {directory}``: write the function as a standalone
  rclpy node into a directory inside the workspace.
"""

from typing import Any, Dict

from fastapi import FastAPI
from pydantic import BaseModel, constr

from .function import codegen, modules
from .lab import Lab
from .launcher import validate
from .launcher.errors import LauncherError
from .launcher.schema import FunctionSpec, MODULE_PATTERN


class _Strict(BaseModel):
    class Config:
        extra = 'forbid'


class ExportCodeRequest(_Strict):
    directory: constr(min_length=1, max_length=1024)


def register(app: FastAPI, lab: Lab) -> None:
    launcher = lab.launcher

    @app.get('/api/functions/modules')
    def list_modules() -> Dict[str, Any]:
        return {'workspace': launcher.workspace.root,
                'modules': modules.list_modules(launcher.workspace.root)}

    @app.get('/api/functions/module')
    def describe_module(name: constr(regex=MODULE_PATTERN, max_length=256)) -> Dict[str, Any]:
        return modules.describe_module(launcher.workspace.root, name)

    @app.post('/api/functions', status_code=201)
    def add_function(spec: FunctionSpec, start: bool = False) -> Dict[str, Any]:
        return launcher.add(spec, start=start)

    @app.put('/api/functions/{function_id}')
    def put_function(function_id: str, spec: FunctionSpec) -> Dict[str, Any]:
        return launcher.update(function_id, spec)

    @app.post('/api/functions/{function_id}/export-code')
    def export_code(function_id: str, req: ExportCodeRequest) -> Dict[str, Any]:
        spec = launcher.manager.target(function_id).spec
        if not isinstance(spec, FunctionSpec):
            raise LauncherError('not_found', f'{function_id} is not a function node', 404)
        directory = validate.contained_dir(req.directory, launcher.workspace.root)
        return codegen.export_code(spec, launcher.workspace.root, directory)
