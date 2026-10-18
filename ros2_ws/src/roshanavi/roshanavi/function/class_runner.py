"""A class node's ROS side: subscriptions, publishers, timers, action topics and parameters."""

import array
import logging
import threading
from typing import Any, Dict, List, Tuple

from rcl_interfaces.msg import ParameterDescriptor, SetParametersResult
from rclpy.parameter import Parameter
from std_msgs.msg import Empty

from .. import msgutil
from ..launcher.schema import ClassSpec
from ..ros_runtime import RosRuntime, make_qos
from . import class_params
from .class_core import ClassCore
from .loader import Problem
from .class_loader import ClassLoader
from .class_params import UNSET, InitParam
from .runner import INPUT_QOS, periodic_loop

LOG = logging.getLogger('roshanavi.function')

PARAM_TYPES = {'string': Parameter.Type.STRING, 'float': Parameter.Type.DOUBLE,
               'int': Parameter.Type.INTEGER, 'bool': Parameter.Type.BOOL,
               'numbers': Parameter.Type.DOUBLE_ARRAY, 'json': Parameter.Type.STRING}
# An action topic ``~/<method>`` (/<node>/<method>): reliable so that ``ros2 topic pub`` and the
# roshanavi button / scenario step (reliable too) are both heard.
ACTION_QOS = {'reliability': 'reliable', 'durability': 'volatile', 'depth': 10}


def ros_value(value: Any) -> Any:
    """A ROS parameter value as a plain Python value (arrays become lists)."""
    return value.tolist() if isinstance(value, array.array) else value


class ClassRunner:
    def __init__(self, spec: ClassSpec, runtime: RosRuntime, loader: ClassLoader):
        self.spec = spec
        self._runtime = runtime
        self._publishers: List[List[Any]] = []
        self._subscriptions: List[Any] = []
        self._threads: List[threading.Thread] = []
        self._stop = threading.Event()
        self._declared: Dict[str, str] = {}
        self._declaring = True
        self.core = ClassCore(spec, loader, self._send)
        self._start()

    # ---- wiring ---------------------------------------------------------------------------
    def _start(self) -> None:
        core, runtime = self.core, self._runtime
        self.core.on_signature = self._resync_params
        self._declare_all()
        runtime.node.add_on_set_parameters_callback(self._on_set)
        self._declaring = False
        for binding in core.bindings:
            # An empty topic is a port that is not wired yet (map wiring): no publisher.
            self._publishers.append([
                runtime.create_publisher(msgutil.resolve_type(port.type), port.topic,
                                         make_qos(**out.qos.model_dump())) if port.topic else None
                for port, out in zip(binding.outputs, binding.spec.outputs)])
        qos = make_qos(**INPUT_QOS)
        for b, binding in enumerate(core.bindings):
            for i, port in enumerate(binding.inputs):
                if not port.topic:
                    continue
                def callback(msg: Any, b: int = b, i: int = i) -> None:
                    core.on_message(b, i, msg)
                self._subscriptions.append(runtime.create_subscription(
                    msgutil.resolve_type(port.type), port.topic, callback, qos))
        for method in self.spec.actions:
            def action(_msg: Any, method: str = method) -> None:
                core.call_action(method)
            self._subscriptions.append(runtime.create_subscription(
                Empty, f'~/{method}', action, make_qos(**ACTION_QOS)))
        for b, binding in enumerate(core.bindings):
            if binding.spec.call == 'periodic':
                thread = threading.Thread(
                    target=periodic_loop, name=f'class-periodic-{binding.spec.method}',
                    args=(self._stop, float(binding.spec.rate_hz or 1.0),
                          lambda b=b: core.tick(b)), daemon=True)
                thread.start()
                self._threads.append(thread)
        core.start()

    def _send(self, binding: int, output: int, msg: Any) -> None:
        self._publishers[binding][output].publish(msg)

    # ---- parameters -----------------------------------------------------------------------
    def _declare_all(self) -> None:
        values: Dict[str, Any] = {}
        for param, value in self.core.declarations():
            declared = self._declare(param, value)
            if declared is not UNSET:
                values[param.name] = declared
        self.core.adopt_declared(values)

    def _declare(self, param: InitParam, value: Any) -> Any:
        """Declare one parameter; returns the Python value it ended up with (UNSET: not set)."""
        node, kind = self._runtime.node, param.kind
        description = f'__init__ argument {param.describe()}'
        descriptor = ParameterDescriptor(description=description)
        try:
            if value is UNSET:
                node.declare_parameter(param.name, PARAM_TYPES[kind], descriptor)
            else:
                node.declare_parameter(param.name, class_params.to_ros(kind, value), descriptor)
            self._declared[param.name] = kind
            actual = ros_value(node.get_parameter(param.name).value)
            return UNSET if actual is None else class_params.to_python(kind, actual, param.name)
        except Exception as exc:  # a bad override (--ros-args -p) or an unusable value
            self.core.report(Problem('param', f'設定値 (パラメータ) {param.name} を使えません: {exc}', None))
            return value

    def _resync_params(self, declarations: List[Tuple[InitParam, Any]]) -> None:
        """After a hot reload changed the ``__init__`` arguments (on the worker thread)."""
        node = self._runtime.node
        wanted = {p.name: p.kind for p, _ in declarations}
        for name, kind in list(self._declared.items()):
            if wanted.get(name) != kind:
                try:
                    node.undeclare_parameter(name)
                except Exception as exc:
                    LOG.warning('cannot remove parameter %s: %s', name, exc)
                del self._declared[name]
        for param, value in declarations:
            if param.name not in self._declared:
                self._declare(param, value)

    def _on_set(self, params: List[Parameter]) -> SetParametersResult:
        # Declaring (start-up, or a reload on the worker) is not a change to apply.
        if self._declaring or self.core.in_worker():
            return SetParametersResult(successful=True)
        changes: Dict[str, Any] = {}
        for param in params:
            kind = self._declared.get(param.name)
            if kind is None:
                continue
            try:
                changes[param.name] = class_params.to_python(kind, ros_value(param.value),
                                                             param.name)
            except ValueError as exc:
                return SetParametersResult(successful=False, reason=str(exc))
        if not changes:
            return SetParametersResult(successful=True)
        ok, reason = self.core.apply_params(changes)
        return SetParametersResult(successful=ok, reason=reason)

    # ---- stop ------------------------------------------------------------------------------
    def close(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=2.0)
        for sub in self._subscriptions:
            self._runtime.destroy_subscription(sub)
        self._subscriptions = []
        self.core.close()     # the instance's close() / shutdown(), on the worker, bounded
        for publishers in self._publishers:
            for pub in publishers:
                if pub is not None:
                    self._runtime.destroy_publisher(pub)
        self._publishers = []
