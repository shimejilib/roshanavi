"""Map wiring on the backend side (docs/design/wiring.md): the kind compatibility rules shared
with the web UI, input ports that take a convertible type, and ports that are not wired yet."""

import json
import os

import pytest
from std_msgs.msg import Int64, String

from roshanavi import data_kinds as dk
from roshanavi.function import class_codegen, codegen
from roshanavi.function.core import FunctionCore
from roshanavi.function.loader import FunctionLoader
from roshanavi.launcher import command
from roshanavi.launcher.errors import LauncherError
from roshanavi.launcher.schema import ClassSpec, FunctionSpec
from roshanavi.pydantic_compat import ValidationError
from ws_fixtures import fake_source

CASES = os.path.join(os.path.dirname(__file__), 'data', 'wire_compat_cases.json')

LOGIC = '''\
def shout(text: str) -> str:
    return text.upper()


def half(x: float) -> float:
    return x / 2


def add(a: float, b: float) -> float:
    return a + b


class Keep:
    def process(self, x: str) -> str:
        return x

    def reset(self) -> None:
        pass
'''


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / 'ws'
    pkg = fake_source(root / 'src', 'my_ros_pkg')
    (pkg / 'wire_pkg').mkdir(parents=True)
    (pkg / 'wire_pkg' / '__init__.py').write_text('')
    (pkg / 'wire_pkg' / 'logic.py').write_text(LOGIC)
    return root


def fn_spec(**kw):
    base = {'id': 'fn', 'name': 'fn', 'module': 'wire_pkg.logic', 'function': 'shout',
            'inputs': [{'topic': '', 'kind': 'string'}], 'output': {'topic': '', 'kind': 'string'}}
    return FunctionSpec.model_validate({**base, **kw})


def class_spec(**kw):
    base = {'id': 'keep', 'name': 'keep', 'module': 'wire_pkg.logic', 'class_name': 'Keep',
            'methods': [{'method': 'process', 'inputs': [{'topic': '', 'kind': 'string'}],
                         'outputs': [{'topic': '', 'kind': 'string'}]}],
            'actions': ['reset']}
    return ClassSpec.model_validate({**base, **kw})


def core_for(ws, spec):
    loader = FunctionLoader(str(ws), spec.module, spec.function)
    loader.load()
    sent = []
    return FunctionCore(spec, loader, sent.append), sent


# ---- the shared compatibility rules -------------------------------------------------------------
def load_cases():
    with open(CASES, encoding='utf-8') as fh:
        return json.load(fh)['cases']


@pytest.mark.parametrize('case', load_cases(), ids=lambda c: f"{c['sender']}->{c['receiver']}")
def test_wire_compat_matches_the_shared_cases(case):
    s, r = case['sender'], case['receiver']
    assert list(dk.wire_compat(s['kind'], s['type'], r['kind'], r['type'])) == case['expect']


def test_catalog_lists_the_conversions_for_the_ui():
    body = dk.catalog(installed=lambda t: True)
    assert {(c['from'], c['to']): c['note'] for c in body['conversions']} == dk.CONVERSIONS


def test_input_ports_accept_a_convertible_type_outputs_do_not():
    assert dk.accepts('float', 'std_msgs/msg/Int32')
    assert not dk.fits('float', 'std_msgs/msg/Int32')
    assert not dk.accepts('int', 'std_msgs/msg/Float64')  # decimals would be lost
    assert not dk.accepts('string', 'sensor_msgs/msg/Image')
    assert dk.resolve('float', 'std_msgs/Int64', receiving=True) == ('float', 'std_msgs/msg/Int64')
    with pytest.raises(dk.KindError):
        dk.resolve('float', 'std_msgs/Int64')
    fn_spec(inputs=[{'topic': '/n', 'kind': 'float', 'type': 'std_msgs/msg/Int64'}],
            function='half', output={'topic': '/h', 'kind': 'float'})
    with pytest.raises(ValidationError):
        fn_spec(function='half', inputs=[{'topic': '/n', 'kind': 'float'}],
                output={'topic': '/h', 'kind': 'float', 'type': 'std_msgs/msg/Int64'})


def test_an_integer_topic_reaches_a_float_input_as_a_float(ws):
    spec = fn_spec(function='half', inputs=[{'topic': '/n', 'kind': 'float',
                                             'type': 'std_msgs/msg/Int64'}],
                   output={'topic': '/h', 'kind': 'float'})
    core, sent = core_for(ws, spec)
    core.on_message(0, Int64(data=3))
    assert [m.data for m in sent] == [1.5]


# ---- ports that are not wired yet ------------------------------------------------------------------
def test_unwired_ports_are_valid_and_checked_like_wired_ones(ws):
    spec = fn_spec()
    command.validate_function(spec, str(ws))   # empty topics are skipped, not "invalid topic"
    with pytest.raises(LauncherError):
        command.validate_function(fn_spec(inputs=[{'topic': 'no_slash', 'kind': 'string'}]),
                                  str(ws))
    with pytest.raises(LauncherError):        # the loop check still applies to wired topics
        command.validate_function(fn_spec(inputs=[{'topic': '/a', 'kind': 'string'}],
                                          output={'topic': '/a', 'kind': 'string'}), str(ws))
    # Two inputs that are both unwired are not "the same topic twice"; trigger never matches ''.
    fn_spec(function='add', call='multi_input',
            inputs=[{'topic': '', 'kind': 'float'}, {'topic': '', 'kind': 'float'}],
            output={'topic': '', 'kind': 'float'})
    with pytest.raises(ValidationError):
        fn_spec(function='add', call='multi_input', trigger='',
                inputs=[{'topic': '', 'kind': 'float'}, {'topic': '/b', 'kind': 'float'}])
    with pytest.raises(ValidationError):
        fn_spec(function='add', call='multi_input',
                inputs=[{'topic': '/b', 'kind': 'float'}, {'topic': '/b', 'kind': 'float'}])


def test_class_ports_may_be_unwired(ws):
    spec = class_spec()
    command.validate_class(spec, str(ws))
    two = class_spec(methods=[
        {'method': 'process', 'inputs': [{'topic': '', 'kind': 'string'}],
         'outputs': [{'topic': '', 'kind': 'string', 'key': 'a'},
                     {'topic': '', 'kind': 'string', 'key': 'b'}]}])
    assert [o.topic for o in two.methods[0].outputs] == ['', '']
    with pytest.raises(ValidationError):   # wired outputs are still unique
        class_spec(methods=[
            {'method': 'process', 'inputs': [{'topic': '', 'kind': 'string'}],
             'outputs': [{'topic': '/x', 'kind': 'string', 'key': 'a'},
                         {'topic': '/x', 'kind': 'string', 'key': 'b'}]}])


def test_an_unwired_output_calls_the_function_but_sends_nothing(ws):
    core, sent = core_for(ws, fn_spec(inputs=[{'topic': '/in', 'kind': 'string'}]))
    core.on_message(0, String(data='hey'))
    stats = core.snapshot()['stats']
    assert sent == [] and stats['calls'] == 1 and stats['skipped'] == 1


def test_code_export_needs_every_port_wired(ws, tmp_path):
    with pytest.raises(LauncherError) as err:
        codegen.export_code(fn_spec(), str(ws), str(tmp_path / 'gen'))
    assert err.value.code == 'unwired_ports' and err.value.status == 409
    with pytest.raises(LauncherError) as err:
        class_codegen.export_code(class_spec(), str(ws), str(tmp_path / 'gen'))
    assert err.value.code == 'unwired_ports'
    wired = fn_spec(inputs=[{'topic': '/in', 'kind': 'string'}],
                    output={'topic': '/out', 'kind': 'string'})
    assert codegen.export_code(wired, str(ws), str(tmp_path / 'gen'))['file'].endswith('fn_node.py')


# ---- over real ROS: nodes with unwired ports start and run -------------------------------------
def _run_node(tmp_path, spec, name):
    import subprocess
    from roshanavi.launcher.dummy_config import class_config_text, function_config_text
    from conftest import WS_ROOT
    status = tmp_path / f'{name}.status.json'
    config = tmp_path / f'{name}.yaml'
    text = class_config_text if isinstance(spec, ClassSpec) else function_config_text
    config.write_text(text(spec, WS_ROOT, str(status)))
    proc = subprocess.Popen(['ros2', 'run', 'roshanavi', 'function', '--config', str(config),
                             '--ros-args', '-r', f'__node:={name}'], start_new_session=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return proc, status


def _status(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def test_function_node_with_unwired_ports_runs(tmp_path, helper):
    from conftest import wait_for
    from test_dummy import stop_group
    spec = FunctionSpec.model_validate({
        'id': 'rn-wire-fn', 'name': 'rn_wire_fn', 'module': 'roshanavi_examples.logic',
        'function': 'shout', 'inputs': [{'topic': '/rn_wire_in', 'kind': 'string'}],
        'output': {'topic': '', 'kind': 'string'}})
    helper.periodic_publisher(String, '/rn_wire_in', 20, lambda i: String(data=f'm{i}'))
    proc, status = _run_node(tmp_path, spec, 'rn_wire_fn')
    try:
        wait_for(lambda: _status(status).get('stats', {}).get('calls', 0) >= 3, timeout=30)
        stats = _status(status)['stats']
        assert _status(status)['state'] == 'running' and stats['published'] == 0
    finally:
        assert stop_group(proc) == 0, proc.stdout.read()
    # Nothing wired at all: the node still starts (and waits to be wired on the map).
    idle = spec.model_copy(update={'inputs': [spec.inputs[0].model_copy(update={'topic': ''})]})
    proc, status = _run_node(tmp_path, idle, 'rn_wire_idle')
    try:
        wait_for(lambda: _status(status).get('state') == 'running', timeout=30)
    finally:
        assert stop_group(proc) == 0, proc.stdout.read()


def test_class_node_with_unwired_ports_runs(tmp_path, helper):
    from conftest import wait_for
    from test_dummy import stop_group
    spec = ClassSpec.model_validate({
        'id': 'rn-wire-avg', 'name': 'rn_wire_avg', 'module': 'roshanavi_examples.stateful',
        'class_name': 'MovingAverage',
        'methods': [{'method': 'process', 'inputs': [{'topic': '', 'kind': 'float'}],
                     'outputs': [{'topic': '', 'kind': 'float'}]}],
        'actions': ['reset']})
    proc, status = _run_node(tmp_path, spec, 'rn_wire_avg')
    try:
        wait_for(lambda: _status(status).get('state') == 'running', timeout=30)
    finally:
        assert stop_group(proc) == 0, proc.stdout.read()
