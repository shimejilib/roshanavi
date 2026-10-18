"""Node parameter, lifecycle, node-list and interface-definition routes (docs/design/launcher.md).

Parameters are read and changed through the node's own parameter services
(:mod:`params`). Nodes roshanavi did not start (role ``other``) are read-only
unless the request says ``allow_external`` (the UI asks for confirmation
first); roshanavi's own node is never changed. Only nodes currently on the
graph are contacted.
"""

import logging
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI

from . import interfaces
from .api_errors import ApiError
from .function import class_modules
from .lab import Lab
from .launcher.schema import ClassSpec
from .lifecycle import ALLOWED_TRANSITIONS, GOALS
from .node_list import build_node_list, lifecycle_node_ids
from .params import SETTABLE_TYPES, check_node_name
from .pydantic_compat import StrictModel, constr
from .ros_runtime import is_self_node

LOG = logging.getLogger(__name__)

ParamType = Literal[SETTABLE_TYPES]  # type: ignore[valid-type]


class ParamSetRequest(StrictModel):
    name: constr(min_length=1, max_length=256)
    type: ParamType
    value: Any = None
    allow_external: bool = False


class LifecycleRequest(StrictModel):
    transition: Optional[Literal[ALLOWED_TRANSITIONS]] = None  # type: ignore[valid-type]
    goal: Optional[Literal[GOALS]] = None  # type: ignore[valid-type]
    allow_external: bool = False


def graph_node(lab: Lab, node: str) -> Dict[str, Any]:
    """The node's entry on the current graph; ApiError 404 when it is not there."""
    snapshot, _ = lab.graph.snapshot()
    for entry in snapshot['nodes']:
        if entry['id'] == node and not entry.get('job_id'):
            return entry
    raise ApiError('node_not_found', f'node {node} is not running (not on the graph)', 404)


def node_role(lab: Lab, node: str) -> str:
    """Role of a node on the current graph; ApiError 404 when it is not there."""
    return graph_node(lab, node).get('role', 'other')


def class_param_order(lab: Lab, entry: Dict[str, Any]) -> Optional[List[str]]:
    """``__init__`` argument names of a class node's class, in signature order (else None).

    The parameter dialog lists a class node's settings in this order; a class that cannot be read
    right now (broken module) just falls back to the plain order.
    """
    try:
        manager = lab.launcher.manager
        spec = manager.target(entry.get('target_id') or '').spec
        if not isinstance(spec, ClassSpec):
            return None
        info = class_modules.describe_module(manager.locations(), spec.module)
        for cls in info.get('classes', []):
            if cls['name'] == spec.class_name:
                return [p['name'] for p in cls['init_params']]
    except Exception as exc:  # unknown target, unreadable module: order is cosmetic
        LOG.debug('no __init__ order for %s: %s', entry.get('id'), exc)
    return None


def lifecycle_node(lab: Lab, node: str) -> Dict[str, Any]:
    entry = graph_node(lab, node)
    if not entry.get('lifecycle'):
        raise ApiError('not_lifecycle', f'{node} is not a lifecycle (managed) node', 400)
    return entry


def node_list(lab: Lab) -> Dict[str, Any]:
    snapshot, _ = lab.graph.snapshot()
    nodes = snapshot['nodes']
    states = lab.lifecycle.states(lifecycle_node_ids(nodes))
    return build_node_list(nodes, lab.launcher.targets(), states)


def _node_id(path: str) -> str:
    return check_node_name('/' + path.strip('/'))


def register(app: FastAPI, lab: Lab) -> None:
    @app.get('/api/nodes/{node:path}/parameters')
    def get_parameters(node: str) -> Dict[str, Any]:
        node = _node_id(node)
        entry = graph_node(lab, node)
        role = entry.get('role', 'other')
        return {'node': node, 'role': role, 'external': role == 'other',
                'parameters': lab.params.list(node), 'init_order': class_param_order(lab, entry)}

    @app.put('/api/nodes/{node:path}/parameters')
    def put_parameter(node: str, req: ParamSetRequest) -> Dict[str, Any]:
        node = _node_id(node)
        if is_self_node(node):
            raise ApiError('self_node', 'the parameters of roshanavi itself cannot be changed',
                           403)
        role = node_role(lab, node)
        if role == 'other' and not req.allow_external:
            raise ApiError('external_node_readonly', f'{node} was not started by roshanavi; '
                           'confirm to change its parameters', 403)
        return {'node': node, 'role': role,
                'parameter': lab.params.set(node, req.name, req.type, req.value)}

    _register_lifecycle(app, lab)

    @app.get('/api/node-list')
    def get_node_list() -> Dict[str, Any]:
        return node_list(lab)

    @app.get('/api/interfaces/{pkg}/{kind}/{name}')
    def get_interface(pkg: str, kind: str, name: str) -> Dict[str, Any]:
        return interfaces.show(f'{pkg}/{kind}/{name}')


def _register_lifecycle(app: FastAPI, lab: Lab) -> None:
    @app.get('/api/nodes/{node:path}/lifecycle')
    def get_lifecycle(node: str) -> Dict[str, Any]:
        node = _node_id(node)
        entry = lifecycle_node(lab, node)
        return {**lab.lifecycle.info(node), 'role': entry.get('role', 'other')}

    @app.post('/api/nodes/{node:path}/lifecycle')
    def post_lifecycle(node: str, req: LifecycleRequest) -> Dict[str, Any]:
        node = _node_id(node)
        if is_self_node(node):
            raise ApiError('self_node', 'roshanavi itself cannot be changed', 403)
        if (req.transition is None) == (req.goal is None):
            raise ApiError('invalid_request', 'give exactly one of "transition" or "goal"')
        role = lifecycle_node(lab, node).get('role', 'other')
        if role == 'other' and not req.allow_external:
            raise ApiError('external_node_readonly', f'{node} was not started by roshanavi; '
                           'confirm to change its lifecycle state', 403)
        if req.transition is not None:
            return {**lab.lifecycle.change(node, req.transition), 'role': role}
        return {**lab.lifecycle.reach(node, req.goal), 'role': role}
