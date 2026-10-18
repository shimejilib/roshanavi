"""Child-process side: walk a LaunchDescription without starting any process.

The walker evaluates conditions and visits only an allow-list of actions that
merely change the ``LaunchContext`` (arguments, launch configurations,
namespaces, remaps, global parameters, environment, groups, includes). Every
``Node`` is extracted instead of executed. Everything else -- ExecuteProcess,
composable containers, event handlers, timers, unknown actions -- is reported
with a reason and left alone, so nothing is ever spawned by roshanavi.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from launch import LaunchDescription
from launch import actions as la
from launch_ros import actions as lra

from .extract import container_nodes, current_file, describe, extract_node

MAX_DEPTH = 40
MAX_ENTITIES = 5000

CONTEXT_ACTIONS: Tuple[type, ...] = (
    LaunchDescription, la.DeclareLaunchArgument, la.SetLaunchConfiguration,
    la.UnsetLaunchConfiguration, la.GroupAction, la.IncludeLaunchDescription,
    la.PushLaunchConfigurations, la.PopLaunchConfigurations, la.ResetLaunchConfigurations,
    la.PushEnvironment, la.PopEnvironment, la.ResetEnvironment, la.SetEnvironmentVariable,
    la.UnsetEnvironmentVariable, la.AppendEnvironmentVariable, la.OpaqueFunction,
    lra.PushROSNamespace, lra.SetRemap, lra.SetParameter, lra.SetParametersFromFile,
    lra.SetUseSimTime, lra.SetROSLogDir)
ENV_ACTIONS: Tuple[type, ...] = (la.SetEnvironmentVariable, la.UnsetEnvironmentVariable,
                                 la.AppendEnvironmentVariable, la.ResetEnvironment)
IGNORED_ACTIONS: Tuple[type, ...] = (la.LogInfo,)
# Checked in order: containers are Nodes and Nodes are ExecuteProcesses.
BLOCKED_ACTIONS: Tuple[Tuple[type, str], ...] = (
    (lra.ComposableNodeContainer, 'composable_container'),
    (lra.LoadComposableNodes, 'load_composable_nodes'),
    (lra.LifecycleTransition, 'lifecycle_transition'),
    (la.ExecuteLocal, 'execute_process'),
    (la.RegisterEventHandler, 'event_handler'),
    (la.UnregisterEventHandler, 'event_handler'),
    (la.TimerAction, 'timer'),
    (lra.RosTimer, 'timer'),
    (la.EmitEvent, 'emit_event'),
    (la.OpaqueCoroutine, 'opaque_coroutine'),
)


@dataclass
class WalkResult:
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    blocked: List[Dict[str, Any]] = field(default_factory=list)
    skipped: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    files: List[str] = field(default_factory=list)  # every launch file read (main + includes)
    visited: int = 0

    def warn(self, code: str, detail: str = '') -> None:
        if not any(w['code'] == code for w in self.warnings):
            self.warnings.append({'code': code, 'detail': detail})

    def to_dict(self) -> Dict[str, Any]:
        return {'nodes': self.nodes, 'blocked': self.blocked, 'skipped': self.skipped,
                'warnings': self.warnings, 'files': self.files}

    def add_file(self, path: Optional[str]) -> None:
        if path and path not in self.files:
            self.files.append(path)


def classify(entity: Any) -> str:
    """'node' | 'context' | 'ignored' | blocked reason code."""
    for cls, code in BLOCKED_ACTIONS[:3]:
        if isinstance(entity, cls):
            return code
    if isinstance(entity, lra.Node):
        return 'node'
    for cls, code in BLOCKED_ACTIONS[3:]:
        if isinstance(entity, cls):
            return code
    if isinstance(entity, CONTEXT_ACTIONS):
        return 'context'
    if isinstance(entity, IGNORED_ACTIONS):
        return 'ignored'
    return 'unknown_action'


def _report(result: WalkResult, bucket: str, entity: Any, context: Any, code: str,
            message: str = '') -> None:
    item = {'kind': type(entity).__name__, 'code': code, 'detail': describe(entity, context),
            'file': current_file(context)}
    if message:
        item['message'] = message[:500]
    if code in ('composable_container', 'load_composable_nodes'):
        item['composable_nodes'] = container_nodes(entity, context)
    getattr(result, bucket).append(item)


def _condition_holds(entity: Any, context: Any, result: WalkResult) -> Optional[bool]:
    condition = getattr(entity, 'condition', None)
    if condition is None:
        return True
    result.warn('conditions_evaluated')  # decided now, with the arguments of this evaluation
    try:
        return bool(condition.evaluate(context))
    except Exception as exc:  # unresolved substitution in the condition
        _report(result, 'blocked', entity, context, 'condition_failed', f'{exc}')
        return None


def walk(entity: Any, context: Any, result: WalkResult, depth: int = 0) -> None:
    result.visited += 1
    if depth > MAX_DEPTH or result.visited > MAX_ENTITIES:
        _report(result, 'blocked', entity, context, 'too_deep')
        return
    holds = _condition_holds(entity, context, result)
    if holds is None:
        return
    if not holds:
        _report(result, 'skipped', entity, context, 'condition_false')
        return
    kind = classify(entity)
    if kind == 'node':
        _extract(entity, context, result)
    elif kind == 'context':
        _visit(entity, context, result, depth)
    elif kind != 'ignored':
        _report(result, 'blocked', entity, context, kind)


def _extract(entity: Any, context: Any, result: WalkResult) -> None:
    try:
        result.nodes.append(extract_node(entity, context, isinstance(entity, lra.LifecycleNode)))
    except Exception as exc:  # e.g. a LaunchConfiguration that was never set
        _report(result, 'blocked', entity, context, 'node_failed', f'{exc}')


def _visit(entity: Any, context: Any, result: WalkResult, depth: int) -> None:
    if isinstance(entity, la.OpaqueFunction):
        result.warn('opaque_function_ran', describe(entity, context))
    if isinstance(entity, ENV_ACTIONS):
        result.warn('env_actions')  # carried over to each node (plan: env)
    try:
        children = entity.visit(context) or []
    except Exception as exc:  # broken include, missing argument, bad substitution ...
        code = 'include_failed' if isinstance(entity, la.IncludeLaunchDescription) \
            else 'evaluation_failed'
        _report(result, 'blocked', entity, context, code, f'{type(exc).__name__}: {exc}')
        return
    if isinstance(entity, la.IncludeLaunchDescription):
        result.add_file(current_file(context))  # the include just set it in these locals
    for child in children:
        context._push_locals()  # same scoping as LaunchService
        try:
            walk(child, context, result, depth + 1)
        finally:
            context._pop_locals()
