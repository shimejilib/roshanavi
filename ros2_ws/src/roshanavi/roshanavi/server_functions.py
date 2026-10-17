"""Function node (関数ノード) routes (docs/design/nodes.md).

- ``GET /api/functions/modules``: Python modules of the workspace packages.
- ``GET /api/functions/module?name=pkg.mod``: its top-level functions and signatures,
  read with :mod:`ast` (user code is never imported in the server).
- ``POST /api/functions`` (``?start=true``) / ``PUT /api/functions/{id}``: register or change
  a function node. Start / stop / delete / logs use ``/api/targets/{id}``; the node's
  live status (calls, errors with file:line, reloads) is ``function_status`` of the target.
- ``POST /api/functions/{id}/export-code {directory}``: write the function as a standalone
  rclpy node into a directory inside the workspace.

Class nodes (docs/design/nodes.md) share ``/api/functions/modules`` and ``/module`` (the module
description also lists its ``classes``) and add:

- ``POST /api/classes`` (``?start=true``) / ``PUT /api/classes/{id}``: register or change one.
- ``POST /api/classes/{id}/call {method}``: call an action method (publishes ``std_msgs/Empty``
  on ``/<node>/<method>``) and wait for the node to report the call.
- ``POST /api/classes/{id}/export-code {directory, lifecycle?}``: the class as a plain rclpy node
  (or a LifecycleNode).
"""

from typing import Any, Dict

from fastapi import FastAPI

from .function import class_call, class_codegen, class_modules, codegen, modules
from .injector import Injector
from .lab import Lab
from .launcher import validate
from .launcher.errors import LauncherError
from .launcher.schema import ClassSpec, FunctionSpec, METHOD_PATTERN, MODULE_PATTERN
from .pydantic_compat import StrictModel, constr


class _Strict(StrictModel):
    pass


class ExportCodeRequest(_Strict):
    directory: constr(min_length=1, max_length=1024)


class ClassExportRequest(ExportCodeRequest):
    lifecycle: bool = False


class CallRequest(_Strict):
    method: constr(regex=METHOD_PATTERN)


def register(app: FastAPI, lab: Lab) -> None:
    launcher = lab.launcher

    @app.get('/api/functions/modules')
    def list_modules() -> Dict[str, Any]:
        return {'workspace': launcher.workspace.root,
                'modules': modules.list_modules(launcher.workspace.root)}

    @app.get('/api/functions/module')
    def describe_module(name: constr(regex=MODULE_PATTERN, max_length=256)) -> Dict[str, Any]:
        return class_modules.describe_module(launcher.workspace.root, name)

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

    # ---- class nodes --------------------------------------------------------------------
    calls = Injector(lab.runtime, lab.data_dir)   # its own: the one-shot calls are not inject jobs

    def class_spec(class_id: str) -> ClassSpec:
        spec = launcher.manager.target(class_id).spec
        if not isinstance(spec, ClassSpec):
            raise LauncherError('not_found', f'{class_id} is not a class node', 404)
        return spec

    @app.post('/api/classes', status_code=201)
    def add_class(spec: ClassSpec, start: bool = False) -> Dict[str, Any]:
        return launcher.add(spec, start=start)

    @app.put('/api/classes/{class_id}')
    def put_class(class_id: str, spec: ClassSpec) -> Dict[str, Any]:
        return launcher.update(class_id, spec)

    @app.post('/api/classes/{class_id}/call')
    def call_method(class_id: str, req: CallRequest) -> Dict[str, Any]:
        spec = class_spec(class_id)
        if req.method not in spec.actions:
            raise LauncherError('unknown_action', f'{req.method} is not an action method of '
                                f'{spec.name} (marked: {", ".join(spec.actions) or "none"})', 404)
        if not launcher.manager.target(class_id).alive():
            raise LauncherError('not_running', f'{spec.name} is not running; start it first', 409)
        node = class_call.full_node_name(spec.name, spec.namespace)
        topic = f'{node}/{req.method}'
        try:
            record = class_call.call_action(
                calls, lambda t: bool(lab.runtime.subscriptions_info(t)), topic,
                lambda: launcher.manager.action_record(node, req.method))
        except class_call.ActionCallError as exc:
            raise LauncherError('call_failed', str(exc), 504) from exc
        # Record mode: pressing the button becomes a ``call`` step.
        lab.scenarios.recorder.note_op({'kind': 'class_call', 'node': node,
                                        'method': req.method})
        return {'method': req.method, 'topic': topic, 'record': record}

    @app.post('/api/classes/{class_id}/export-code')
    def export_class_code(class_id: str, req: ClassExportRequest) -> Dict[str, Any]:
        spec = class_spec(class_id)
        directory = validate.contained_dir(req.directory, launcher.workspace.root)
        return class_codegen.export_code(spec, launcher.workspace.root, directory, req.lifecycle)
