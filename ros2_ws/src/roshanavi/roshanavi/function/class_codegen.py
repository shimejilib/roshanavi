"""「ROS ノードのコードとして書き出す」 for a class node: a plain rclpy node that wraps the class.

The generated file does what the class node does, without roshanavi: it is the way out
("graduation") and a lesson in how the class was wrapped. With ``lifecycle=True`` it is an
rclpy ``LifecycleNode`` instead, which maps the class onto the lifecycle:

    __init__            -> on_configure     (the one instance is created, publishers appear)
    subscriptions/timers-> on_activate      (removed again in on_deactivate)
    close / shutdown    -> on_cleanup       (and when the node is destroyed)

Every value embedded in the source is validated by the schema and written with ``repr()``; the
output directory is checked by the caller (workspace containment, no control characters). The
file is compiled before it is written.
"""

from typing import Any, Dict, List, Optional, Tuple

from ..launcher import command
from ..launcher.dummy_config import has_control_chars
from ..launcher.errors import LauncherError
from ..launcher.schema import ClassSpec
from . import class_params
from .class_modules import list_classes
from .class_params import UNSET
from .codegen import HELPERS_IMAGE, MARKER_PREFIX, class_names, input_expr, output_lines, \
    write_source
from .class_core import resolve_binding_ports
from .modules import resolve_module

MARKER = MARKER_PREFIX + 'class node'
STAMP_HELPER = '''

def stamp_of(msg):
    """The input's header stamp if it has one (keeps latency measurable), else None."""
    header = getattr(msg, 'header', None)
    return header.stamp if header is not None else None
'''
PARAM_TYPE_NAMES = {'string': 'STRING', 'float': 'DOUBLE', 'int': 'INTEGER', 'bool': 'BOOL',
                    'numbers': 'DOUBLE_ARRAY', 'json': 'STRING'}
# What turns a ROS parameter value back into the Python value __init__ expects.
PARAM_CONVERTERS = {'numbers': 'list', 'json': 'json.loads'}


def node_class_name(name: str, taken: str) -> str:
    parts = [p for p in name.split('_') if p]
    base = ''.join(p[:1].upper() + p[1:] for p in parts) or 'Class'
    base = base if base.endswith('Node') else base + 'Node'
    return base + 'Ros' if base == taken else base


def _class_info(spec: ClassSpec, workspace: str) -> Dict[str, Any]:
    resolved = resolve_module(workspace, spec.module)
    for info in (list_classes(resolved.file) if resolved.listable else []):
        if info['name'] == spec.class_name:
            return {**info, 'ros_package': resolved.package.ros_package or 'my_ros_package',
                    'top': resolved.package.top}
    raise LauncherError('unknown_class', f'{spec.module} has no public class '
                        f'{spec.class_name!r}', 404)


class _Gen:
    def __init__(self, spec: ClassSpec, workspace: str, lifecycle: bool):
        self.spec, self.lifecycle = spec, lifecycle
        self.info = _class_info(spec, workspace)
        self.ports = [resolve_binding_ports(m) for m in spec.methods]
        self.types = sorted({p.type for ins, outs in self.ports for p in [*ins, *outs]})
        self.kinds = {p.kind for ins, outs in self.ports for p in [*ins, *outs]}
        self.classes = class_names(self.types)
        self.node_cls = node_class_name(spec.name, spec.class_name)
        local = {local for _, local in self.classes.values()}
        self.user_cls = spec.class_name if spec.class_name not in local else 'UserClass'
        self.params = self._params()
        self.hooks: Dict[str, bool] = self.info['hooks']
        self.methods = {m['name']: m for m in self.info['methods']}

    # ---- parameters -----------------------------------------------------------------------
    def _params(self) -> List[Tuple[Dict[str, Any], Optional[Any]]]:
        """``[(static info, value to declare with or None for "not set")]`` of the arguments."""
        found = []
        for p in self.info['init_params']:
            if p['kind'] is None:
                continue
            value: Any = UNSET
            if p['name'] in self.spec.params:
                value = class_params.spec_value(p['kind'], self.spec.params[p['name']], p['name'])
            elif p['has_default'] and p['default'] is not None:
                try:
                    value = class_params.from_default(p['kind'], p['default'])
                except ValueError:
                    value = UNSET
            ros = class_params.to_ros(p['kind'], value) if value is not UNSET else None
            if ros == []:
                ros = None   # an empty array cannot be typed by value: declared by type
            found.append((p, ros))
        return found

    def declare_lines(self) -> List[str]:
        lines = []
        for p, ros in self.params:
            hint = f'{p["name"]}: {p["annotation"]}' if p['annotation'] else p['name']
            if ros is None:
                lines.append(f'        self.declare_parameter({p["name"]!r}, '
                             f'Parameter.Type.{PARAM_TYPE_NAMES[p["kind"]]})  # {hint}: not set')
            else:
                lines.append(f'        self.declare_parameter({p["name"]!r}, {ros!r})  # {hint}')
        return lines

    # ---- sections -------------------------------------------------------------------------
    def imports(self) -> str:
        std = ['import sys', 'import traceback']
        if 'json' in self.kinds or any(p['kind'] == 'json' for p, _ in self.params):
            std.insert(0, 'import json')
        if any(m.call == 'periodic' for m in self.spec.methods):
            std.append('import time')
        third = []
        if self.kinds & {'image', 'audio'}:
            third.append('import numpy as np')
        third.append('import rclpy')
        if self.lifecycle:
            third.append('from rclpy.lifecycle import LifecycleNode, TransitionCallbackReturn')
        else:
            third.append('from rclpy.node import Node')
        third.append('from rcl_interfaces.msg import SetParametersResult')
        if any(ros is None for _, ros in self.params):
            third.append('from rclpy.parameter import Parameter')
        third.append('from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy')
        if 'message' in self.kinds:
            third.append('from rosidl_runtime_py import message_to_ordereddict, '
                         'set_message_fields')
        if self.spec.actions:
            third.append('from std_msgs.msg import Empty')
        third += sorted(line for line, _ in self.classes.values())
        user = f'from {self.spec.module} import {self.spec.class_name}' + \
            (f' as {self.user_cls}' if self.user_cls != self.spec.class_name else '')
        return '\n'.join(std) + '\n\n' + '\n'.join(third) + '\n\n' + \
            '# Your class: a normal Python class that knows nothing about ROS.\n' + user + '\n'

    def header(self) -> str:
        spec, info = self.spec, self.info
        file_name = f'{spec.name}_node'
        deps = ''.join(f' <exec_depend>{pkg}</exec_depend>' for pkg in
                       sorted({t.split('/')[0] for t in self.types}))
        flow = []
        for m in spec.methods:
            ins = ', '.join(i.topic for i in m.inputs) or f'a timer ({m.rate_hz:g} Hz)'
            outs = ', '.join(o.topic for o in m.outputs) or 'nothing'
            flow.append(f'#   {ins} -> {spec.class_name}.{m.method}() -> {outs}')
        flow += [f'#   ~/{a} (std_msgs/Empty) -> {spec.class_name}.{a}()' for a in spec.actions]
        if self.lifecycle:
            what = ('It does the same as the class node, as an rclpy LifecycleNode (no roshanavi\n'
                    '# needed). The class follows the lifecycle:\n'
                    '#   __init__ arguments  -> parameters (declared when the node is created)\n'
                    f'#   configure   -> {spec.class_name}(...) is created, publishers appear\n'
                    '#   activate    -> subscriptions and timers start (deactivate removes them)\n'
                    '#   cleanup     -> close() is called and the instance is dropped\n'
                    f'# Drive it:  ros2 lifecycle set /{spec.name} configure   (then: activate)')
        else:
            what = 'It does the same as the class node, as a plain rclpy node (no roshanavi needed):'
        return f'''#!/usr/bin/env python3
{MARKER} {spec.id!r}.
# {what}
{chr(10).join(flow)}
# One instance of {spec.class_name} is created and every call runs in the single spin thread,
# so the methods are never called at the same time.
#
# How to keep it in your package ({info['ros_package']}, ament_python):
#   1. Save it as {info['ros_package']}/{info['top']}/{file_name}.py
#   2. setup.py:  entry_points={{'console_scripts': [
#          '{file_name} = {info['top']}.{file_name}:main']}}
#   3. package.xml:  <exec_depend>rclpy</exec_depend>{deps}
#   4. colcon build --packages-select {info['ros_package']} && ros2 run {info['ros_package']} {file_name}
# Or run this file directly in a sourced workspace: python3 {file_name}.py
"""{spec.name}: wraps {spec.module}.{spec.class_name} as a ROS 2 {'lifecycle ' if self.lifecycle else ''}node."""

'''

    def converters(self) -> str:
        text = ''
        if 'image' in self.kinds:
            text += HELPERS_IMAGE
        for b, (ins, outs) in enumerate(self.ports):
            for i, port in enumerate(ins):
                expr, help_text = input_expr(port)
                text += (f'\n\ndef input_{b}_{i}(msg):\n'
                         f'    """{port.topic} ({port.type}) -> {help_text}."""\n'
                         f'    return {expr}\n')
            for o, port in enumerate(outs):
                cls = self.classes[port.type][1]
                body = '\n'.join(f'    {line}' for line in output_lines(port, cls))
                text += (f'\n\ndef to_message_{b}_{o}(result, stamp):\n'
                         f'    """What the method returned -> {port.topic} ({port.type})."""\n'
                         f'{body}\n    return out\n')
        return text + STAMP_HELPER

    def parameters_block(self) -> str:
        entries = ''.join(
            f'    {p["name"]!r}: {PARAM_CONVERTERS.get(p["kind"], "None")},\n'
            for p, _ in self.params)
        return (f'\n\n# The __init__ arguments that are ROS parameters, and how a parameter value\n'
                f'# becomes the Python value (None: as it is).\nINIT_PARAMETERS = {{\n{entries}}}\n')

    # ---- the node ---------------------------------------------------------------------------
    def node_class(self) -> str:
        base = 'LifecycleNode' if self.lifecycle else 'Node'
        out = [f'\n\nclass {self.node_cls}({base}):',
               '    def __init__(self):',
               f'        super().__init__({self.spec.name!r})',
               '        # Parameters: the __init__ arguments of the class. Changing one from the',
               '        # outside (ros2 param set) goes through on_parameters() below.',
               *self.declare_lines(),
               '        self.add_on_set_parameters_callback(self.on_parameters)',
               '        self.instance = None',
               '        self.outputs = {}',
               '        self.input_subscriptions = []',
               '        self.input_timers = []']
        if not self.lifecycle:
            out += [f'        self.instance = {self.user_cls}(**self.read_kwargs())',
                    '        self.setup_outputs()', '        self.setup_inputs()']
        out += self.parameter_methods()
        out += self.output_methods()
        out += self.input_methods()
        out += self.call_methods()
        out += self.lifecycle_methods() if self.lifecycle else []
        out += self.destroy_method()
        return '\n'.join(out) + '\n'

    def parameter_methods(self) -> List[str]:
        hook = self.hooks['on_param_change']
        lines = ['',
                 '    def read_kwargs(self, overrides=None):',
                 '        """The __init__ arguments, read from the parameters."""',
                 '        values = {p.name: p.value for p in self.get_parameters(list(INIT_PARAMETERS))}',
                 '        values.update(overrides or {})',
                 '        return {name: (convert(values[name]) if convert else values[name])',
                 '                for name, convert in INIT_PARAMETERS.items()',
                 '                if values[name] is not None}',
                 '',
                 '    def on_parameters(self, params):',
                 '        """Before a parameter changes. "Successful" = the class accepted it."""',
                 '        changed = {p.name: p.value for p in params if p.name in INIT_PARAMETERS}',
                 '        if not changed or self.instance is None:',
                 '            return SetParametersResult(successful=True)',
                 '        try:']
        if hook:
            lines += ['            # The class has on_param_change(name, value): tell it, keep the state.',
                      '            for name, value in changed.items():',
                      '                convert = INIT_PARAMETERS[name]',
                      '                self.instance.on_param_change(name, convert(value) if convert else value)',
                      '        except Exception as exc:',
                      '            return SetParametersResult(successful=False, reason=f\'{type(exc).__name__}: {exc}\')']
        else:
            lines += ['            # No on_param_change(): create the class again with the new values',
                      '            # (its state starts over). If that fails the old one keeps running.',
                      f'            new_instance = {self.user_cls}(**self.read_kwargs(changed))',
                      '        except Exception as exc:',
                      '            return SetParametersResult(successful=False, reason=f\'{type(exc).__name__}: {exc}\')',
                      '        old_instance, self.instance = self.instance, new_instance',
                      '        self.close_instance(old_instance)']
        lines += ['        return SetParametersResult(successful=True)', '']
        close = 'close' if self.hooks['close'] else 'shutdown' if self.hooks['shutdown'] else None
        lines += ['    def close_instance(self, instance):',
                  f'        """Call the instance\'s {close}()' if close else
                  '        """The class has no close() / shutdown(): nothing to clean up.']
        if close:
            lines += ['        (clean-up: close files, sockets ...); an error is logged, not raised."""',
                      '        if instance is None:', '            return', '        try:',
                      f'            instance.{close}()', '        except Exception:',
                      f"            self.get_logger().error('{close}() failed:\\n' + "
                      'traceback.format_exc())']
        else:
            lines += ['        """']
        return lines

    def _qos(self, qos: Any) -> str:
        rel = 'RELIABLE' if qos.reliability == 'reliable' else 'BEST_EFFORT'
        dur = 'TRANSIENT_LOCAL' if qos.durability == 'transient_local' else 'VOLATILE'
        return (f'QoSProfile(depth={qos.depth}, reliability=ReliabilityPolicy.{rel}, '
                f'durability=DurabilityPolicy.{dur})')

    def output_methods(self) -> List[str]:
        create = 'create_lifecycle_publisher' if self.lifecycle else 'create_publisher'
        destroy = 'destroy_lifecycle_publisher' if self.lifecycle else 'destroy_publisher'
        lines = ['', '    def setup_outputs(self):',
                 '        """Publishers: what a method returns is sent here (a dict: one topic per key)."""',
                 '        self.outputs = {}']
        for b, m in enumerate(self.spec.methods):
            if not m.outputs:
                continue
            lines.append(f'        self.outputs[{m.method!r}] = [')
            for o, out in enumerate(m.outputs):
                cls = self.classes[self.ports[b][1][o].type][1]
                lines.append(f'            (self.{create}({cls}, {out.topic!r},')
                lines.append(f'                 {self._qos(out.qos)}),')
                lines.append(f'             {out.key!r}, to_message_{b}_{o}),')
            lines.append('        ]')
        lines += ['', '    def teardown_outputs(self):',
                  '        for entries in self.outputs.values():',
                  '            for publisher, _key, _convert in entries:',
                  f'                self.{destroy}(publisher)',
                  '        self.outputs = {}']
        return lines

    def input_methods(self) -> List[str]:
        spec = self.spec
        in_qos = 'QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)'
        lines = ['', '    def setup_inputs(self):',
                 '        """Subscriptions, timers and action topics: they call the methods."""']
        if any(m.call == 'periodic' for m in spec.methods):
            lines.append('        self.started = time.monotonic()')
        handlers: List[str] = []
        for b, m in enumerate(spec.methods):
            ins = self.ports[b][0]
            if m.call == 'multi_input':
                lines.append(f'        self.latest_{m.method} = {{}}')
            for i, port in enumerate(ins):
                cls = self.classes[port.type][1]
                lines += ['        self.input_subscriptions.append(self.create_subscription(',
                          f'            {cls}, {port.topic!r}, self.on_input_{b}_{i}, {in_qos}))']
                handlers += self._input_handler(b, i)
            if m.call == 'periodic':
                lines.append(f'        self.input_timers.append(self.create_timer('
                             f'{1.0 / float(m.rate_hz):g}, self.on_timer_{m.method}))')
                args = 'time.monotonic() - self.started' if self.methods.get(
                    m.method, {}).get('params') else ''
                handlers += ['', f'    def on_timer_{m.method}(self):',
                             f'        self.run_method({m.method!r}, [{args}])']
        for action in spec.actions:
            lines += ['        # Action: a message on ~/%s calls %s() (no arguments).' % (
                action, action),
                '        self.input_subscriptions.append(self.create_subscription(',
                f'            Empty, \'~/{action}\', self.on_call_{action},',
                '            QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)))']
            handlers += ['', f'    def on_call_{action}(self, _msg):',
                         f'        self.call_action({action!r})']
        if len(lines) == 3:
            lines.append('        pass')
        lines += ['', '    def teardown_inputs(self):',
                  '        for subscription in self.input_subscriptions:',
                  '            self.destroy_subscription(subscription)',
                  '        for timer in self.input_timers:',
                  '            self.destroy_timer(timer)',
                  '        self.input_subscriptions, self.input_timers = [], []']
        return lines + handlers

    def _input_handler(self, b: int, i: int) -> List[str]:
        m = self.spec.methods[b]
        ins = self.ports[b][0]
        lines = ['', f'    def on_input_{b}_{i}(self, msg):']
        if m.call == 'on_message':
            return lines + [f'        self.run_method({m.method!r}, [input_{b}_{i}(msg)], '
                            'stamp_of(msg))']
        lines += [f'        self.latest_{m.method}[{i}] = input_{b}_{i}(msg)',
                  f'        if len(self.latest_{m.method}) < {len(ins)}:',
                  '            return  # wait until every input has sent something']
        if m.trigger != 'any':
            index = [p.topic for p in ins].index(m.trigger)
            if index != i:
                lines += [f'        return  # only {m.trigger} triggers a call']
                return lines
        lines.append(f'        self.run_method({m.method!r}, [self.latest_{m.method}[k] for k in '
                     f'range({len(ins)})], stamp_of(msg))')
        return lines

    def call_methods(self) -> List[str]:
        return ['',
                '    def run_method(self, name, args, stamp=None):',
                '        """instance.<name>(*args), then send what it returned:',
                '        None sends nothing, a dict sends each key to its own topic."""',
                '        if self.instance is None:',
                '            return',
                '        try:',
                '            result = getattr(self.instance, name)(*args)',
                '        except Exception:  # a bug in the class: log it, keep the node running',
                "            self.get_logger().error(f'{name}() failed:\\n' + traceback.format_exc())",
                '            return',
                '        if result is None or name not in self.outputs:',
                '            return',
                '        stamp = stamp or self.get_clock().now().to_msg()',
                '        for publisher, key, convert in self.outputs[name]:',
                '            value = result',
                '            if key is not None:',
                '                if not isinstance(result, dict):',
                "                    self.get_logger().error(f'{name}() must return a dict (one key per output)')",
                '                    return',
                '                value = result.get(key)',
                '                if value is None:',
                '                    continue',
                '            try:',
                '                publisher.publish(convert(value, stamp))',
                '            except Exception:',
                "                self.get_logger().error(f'{name}(): cannot send {key or \"the result\"}:\\n'",
                '                                        + traceback.format_exc())',
                '',
                '    def call_action(self, name):',
                '        """A message on ~/<name>: call instance.<name>() and log the result."""',
                '        if self.instance is None:',
                '            return',
                '        try:',
                '            result = getattr(self.instance, name)()',
                '        except Exception:',
                "            self.get_logger().error(f'{name}() failed:\\n' + traceback.format_exc())",
                '            return',
                "        self.get_logger().info(f'{name}() -> {result!r}')"]

    def lifecycle_methods(self) -> List[str]:
        cls = self.user_cls
        return ['',
                '    def on_configure(self, state):',
                f'        """configure: create the one instance of {cls}, create the publishers."""',
                '        try:',
                f'            self.instance = {cls}(**self.read_kwargs())',
                '        except Exception:',
                "            self.get_logger().error('cannot create the class:\\n' + "
                'traceback.format_exc())',
                '            return TransitionCallbackReturn.FAILURE',
                '        self.setup_outputs()',
                '        return TransitionCallbackReturn.SUCCESS',
                '',
                '    def on_activate(self, state):',
                '        """activate: start listening (subscriptions, timers, action topics)."""',
                '        self.setup_inputs()',
                '        return super().on_activate(state)',
                '',
                '    def on_deactivate(self, state):',
                '        """deactivate: stop listening; the instance (and its state) stays."""',
                '        self.teardown_inputs()',
                '        return super().on_deactivate(state)',
                '',
                '    def on_cleanup(self, state):',
                '        """cleanup: close() the instance and drop it."""',
                '        self.teardown_outputs()',
                '        instance, self.instance = self.instance, None',
                '        self.close_instance(instance)',
                '        return TransitionCallbackReturn.SUCCESS',
                '',
                '    def on_shutdown(self, state):',
                '        self.teardown_inputs()',
                '        return self.on_cleanup(state)']

    def destroy_method(self) -> List[str]:
        return ['',
                '    def destroy_node(self):',
                '        instance, self.instance = self.instance, None',
                '        self.close_instance(instance)',
                '        return super().destroy_node()']

    def main(self) -> str:
        return f'''

def main(args=None):
    rclpy.init(args=args)
    node = {self.node_cls}()
    try:
        rclpy.spin(node)  # one thread: callbacks (and so your methods) never overlap
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == '__main__':
    sys.exit(main())
'''

    def source(self) -> str:
        return (self.header() + self.imports() + self.converters() + self.parameters_block()
                + self.node_class() + self.main())


def generate(spec: ClassSpec, workspace: str, lifecycle: bool = False) -> str:
    return _Gen(spec, workspace, lifecycle).source()


def export_code(spec: ClassSpec, workspace: str, directory: str,
                lifecycle: bool = False) -> Dict[str, str]:
    """Write ``<directory>/<name>_node.py``; ``directory`` is already contained in the workspace."""
    if has_control_chars(directory):
        raise LauncherError('invalid_request', 'directory must not contain control characters')
    # The node name becomes the file name and is written into the code: validate it again
    # (a spec loaded from a project file may be registered as invalid).
    command.validate_class(spec, workspace)
    return write_source(directory, f'{spec.name}_node.py', generate(spec, workspace, lifecycle))
