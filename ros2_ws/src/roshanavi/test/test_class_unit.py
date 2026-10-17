"""Class nodes without a running ROS graph: static listing, parameters, core, reload, codegen."""

import threading
import time

import pytest
from std_msgs.msg import Float64

from roshanavi.function import class_codegen, class_modules, class_params
from roshanavi.function.class_core import ClassCore
from roshanavi.function.class_loader import ClassLoader
from roshanavi.function.class_params import UNSET
from roshanavi.function.loader import LoadError, Watcher
from roshanavi.function.serial import SerialExecutor
from roshanavi.launcher.dummy_config import class_config_text, load_function_config
from roshanavi.launcher.errors import LauncherError
from roshanavi.launcher.schema import ClassSpec
from roshanavi.pydantic_compat import ValidationError
from test_function_unit import write
from ws_fixtures import fake_source

STATEFUL = '''\
from typing import Dict, List, Optional


class Acc:
    """Adds numbers up."""

    def __init__(self, start: float = 0.0, scale: int = 1, label: str = 'acc',
                 gains: List[float] = [], note: Optional[str] = None, config: dict = {}):
        if scale < 1:
            raise ValueError(f'scale must be 1 or more (got {scale})')
        self.total, self.scale, self.label = start, scale, label
        self.gains, self.note, self.config = gains, note, config
        self.closed = False

    def add(self, x: float) -> float:
        self.total += x * self.scale
        return self.total

    def stats(self, x: float) -> dict:
        return {'total': self.total, 'count': 1, 'extra': 'ignored'}

    def maybe(self, x: float) -> Optional[float]:
        return None if x < 0 else x

    def boom(self, x: float) -> float:
        return 1 / 0

    def mix(self, a: float, b: float) -> float:
        return a + b

    def since(self, t: float) -> float:
        return t

    def tick(self) -> float:
        self.total += 1
        return self.total

    def reset(self) -> int:
        self.total = 0.0
        return 7

    def fail(self) -> None:
        raise RuntimeError('nope')

    def close(self) -> None:
        self.closed = True

    def _hidden(self):
        pass

    @staticmethod
    def helper():
        pass
'''

KEEPING = '''\
class Acc:
    def __init__(self, scale: int = 1):
        self.total = 0.0
        self.scale = scale
        self.closed = False

    def add(self, x: float) -> float:
        self.total += x * self.scale
        return self.total

    def reset(self) -> None:
        self.total = 0.0

    def get_state(self):
        return {'total': self.total}

    def set_state(self, state):
        self.total = state['total']

    def close(self):
        self.closed = True

    def on_param_change(self, name, value):
        if value < 0:
            raise ValueError('scale must not be negative')
        self.scale = value
'''


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / 'ws'
    pkg = fake_source(root / 'src', 'my_ros_pkg')
    write(pkg / 'cl_pkg' / '__init__.py', '')
    write(pkg / 'cl_pkg' / 'stateful.py', STATEFUL)
    return root


def spec(**kw):
    base = {'id': 'acc', 'name': 'acc', 'module': 'cl_pkg.stateful', 'class_name': 'Acc',
            'methods': [{'method': 'add', 'inputs': [{'topic': '/in', 'kind': 'float'}],
                         'outputs': [{'topic': '/out', 'kind': 'float'}]}],
            'actions': ['reset']}
    return ClassSpec.model_validate({**base, **kw})


class Rig:
    """A ClassCore with a fake publisher; ``sent`` is [(method index, output index, message)]."""

    def __init__(self, ws, class_spec=None, module='cl_pkg.stateful', start=True):
        self.spec = class_spec or spec()
        self.loader = ClassLoader(str(ws), module, self.spec.class_name)
        self.loader.load()
        self.sent = []
        self.core = ClassCore(self.spec, self.loader, lambda b, o, m: self.sent.append((b, o, m)))
        self.declared = []
        self.core.on_signature = self.declared.append
        if start:
            self.core.start()
            self.sync()

    def sync(self):
        self.core.executor.run(lambda: None, 5)   # everything queued before this has run

    @property
    def instance(self):
        return self.core._s.instance

    def feed(self, value, binding=0, index=0):
        self.core.on_message(binding, index, Float64(data=float(value)))
        self.sync()

    def values(self):
        return [m.data for _, _, m in self.sent]

    def close(self):
        self.core.close()


@pytest.fixture
def rig(ws):
    made = []

    def make(**kw):
        r = Rig(ws, **kw)
        made.append(r)
        return r
    yield make
    for r in made:
        r.close()


# ---- static listing (no import) -----------------------------------------------------------
def test_signature_to_parameters_is_read_without_importing(ws):
    info = class_modules.describe_module(str(ws), 'cl_pkg.stateful')
    assert 'classes' in info and 'functions' in info
    acc = next(c for c in info['classes'] if c['name'] == 'Acc')
    params = {p['name']: p for p in acc['init_params']}
    assert {n: p['kind'] for n, p in params.items()} == {
        'start': 'float', 'scale': 'int', 'label': 'string', 'gains': 'numbers',
        'note': 'string', 'config': 'json'}
    assert params['scale']['default'] == 1 and params['scale']['has_default']
    assert params['note']['default'] is None and params['note']['default_text'] == 'None'
    assert acc['signature'].startswith('Acc(start: float = 0.0, scale: int = 1')
    assert acc['doc'] == 'Adds numbers up.'
    names = [m['name'] for m in acc['methods']]
    assert names == ['add', 'stats', 'maybe', 'boom', 'mix', 'since', 'tick', 'reset', 'fail']
    candidates = [m['name'] for m in acc['methods'] if m['action_candidate']]
    assert candidates == ['tick', 'reset', 'fail']
    assert acc['hooks']['close'] and not acc['hooks']['get_state']
    add = next(m for m in acc['methods'] if m['name'] == 'add')
    assert add['signature'] == 'add(x: float) -> float' and add['returns_kind'] == 'float'
    assert add['params'] == [{'name': 'x', 'annotation': 'float', 'kind': 'float',
                              'optional': False}]


def test_unsupported_argument_types_are_not_parameters(ws, tmp_path):
    write(tmp_path / 'ws' / 'src' / 'my_ros_pkg' / 'cl_pkg' / 'odd.py', '''\
import numpy as np

class Odd:
    def __init__(self, image: np.ndarray, raw: bytes = b'', names: list[str] = [], n=3, f=0.5,
                 flag=True, text='x', untyped=None, *args, **kwargs):
        pass
''')
    odd = class_modules.list_classes(str(tmp_path / 'ws' / 'src' / 'my_ros_pkg' / 'cl_pkg'
                                         / 'odd.py'))[0]
    kinds = {p['name']: p['kind'] for p in odd['init_params']}
    assert kinds == {'image': None, 'raw': None, 'names': 'json', 'n': 'int', 'f': 'float',
                     'flag': 'bool', 'text': 'string', 'untyped': None}


@pytest.mark.parametrize('annotation,default,kind', [
    ('int', UNSET, 'int'), ('float', 1, 'float'), ('str', UNSET, 'string'), ('bool', UNSET, 'bool'),
    ('List[float]', UNSET, 'numbers'), ('list', UNSET, 'numbers'), ('list[int]', UNSET, 'numbers'),
    ('List[str]', UNSET, 'json'), ('dict', UNSET, 'json'), ('Dict[str, int]', UNSET, 'json'),
    ('Optional[int]', None, 'int'), ('int | None', None, 'int'), ('None | float', None, 'float'),
    ('Union[str, None]', None, 'string'), ('Optional[List[float]]', None, 'numbers'), ('int | str', UNSET, None), ('list[str] | None', None, 'json'), ('List[float] | None', None, 'numbers'), (None, 3, 'int'), (None, 1.5, 'float'), (None, 'a', 'string'),
    (None, True, 'bool'), (None, [1, 2], 'numbers'), (None, ['a'], 'json'), (None, {}, 'json'),
    (None, UNSET, None), (None, None, None), ('bytes', UNSET, None), ('np.ndarray', UNSET, None),
    ('Foo', UNSET, None)])
def test_argument_kind_table(annotation, default, kind):
    assert class_params.kind_for(annotation, default) == kind


def test_parameter_value_conversion_is_strict():
    assert class_params.to_python('int', 5.0) == 5
    assert class_params.to_python('float', 2) == 2.0 and isinstance(
        class_params.to_python('float', 2), float)
    assert class_params.to_python('numbers', [1, 2.5]) == [1.0, 2.5]
    assert class_params.to_python('json', '{"a": [1]}') == {'a': [1]}
    for kind, bad in [('int', True), ('int', 1.5), ('int', 'x'), ('float', 'x'), ('float', True),
                      ('bool', 1), ('string', 3), ('numbers', ['a']), ('json', '{oops'),
                      ('json', 3)]:
        with pytest.raises(ValueError):
            class_params.to_python(kind, bad)
    assert class_params.to_ros('json', {'a': 1}) == '{"a": 1}'


# ---- spec validation ------------------------------------------------------------------------
@pytest.mark.parametrize('patch,message', [
    ({'methods': [], 'actions': []}, 'at least one method'),
    ({'actions': ['add']}, 'once'),
    ({'actions': ['close']}, 'itself'),
    ({'methods': [{'method': 'close', 'inputs': [{'topic': '/in'}]}]}, 'itself'),
    ({'methods': [{'method': 'add', 'inputs': []}]}, 'exactly one input'),
    ({'methods': [{'method': 'add', 'call': 'periodic', 'inputs': []}]}, 'rate_hz'),
    ({'methods': [{'method': 'add', 'inputs': [{'topic': '/in'}], 'outputs': [
        {'topic': '/a', 'key': 'x'}, {'topic': '/b'}]}]}, 'every output a key'),
    ({'methods': [{'method': 'add', 'inputs': [{'topic': '/in'}], 'outputs': [
        {'topic': '/a'}, {'topic': '/b'}]}]}, 'key each'),
    ({'methods': [{'method': 'add', 'inputs': [{'topic': '/in'}], 'outputs': [
        {'topic': '/a', 'key': 'x'}, {'topic': '/b', 'key': 'x'}]}]}, 'unique'),
    ({'methods': [{'method': 'add', 'inputs': [{'topic': '/in'}],
                   'outputs': [{'topic': '/in'}]}]}, 'both an input and an output'),
    ({'methods': [{'method': '_private', 'inputs': [{'topic': '/in'}]}]}, 'match'),
    ({'class_name': 'bad name'}, 'match'),
    ({'module': 'roshanavi.x'}, 'not roshanavi'),
    ({'params': {'x': {'a': 1}}}, ''),
])
def test_spec_validation(patch, message):
    with pytest.raises(ValidationError) as err:
        spec(**patch)
    assert message in str(err.value) or message == ''


def test_config_round_trip_and_project_ids(tmp_path):
    s = spec(params={'scale': 3, 'gains': [1, 2.5]})
    path = tmp_path / 'c.yaml'
    path.write_text(class_config_text(s, str(tmp_path), str(tmp_path / 'st.json')))
    loaded = load_function_config(str(path))
    assert loaded['spec'] == s and isinstance(loaded['spec'], ClassSpec)
    assert loaded['status_file'] == str(tmp_path / 'st.json')
    path.write_text('class: {}\nfunction: {}\nworkspace: /x\n')
    with pytest.raises(LauncherError):
        load_function_config(str(path))


# ---- core: messages, dict outputs, errors ---------------------------------------------------
def test_on_message_calls_the_method_and_publishes(rig):
    r = rig()
    for x in (1, 2, 3):
        r.feed(x)
    assert r.values() == [1.0, 3.0, 6.0]
    stats = r.core.snapshot()
    assert stats['state'] == 'running' and stats['stats']['calls'] == 3
    assert stats['stats']['published'] == 3 and stats['methods'][0]['calls'] == 3


def test_none_sends_nothing_and_exceptions_keep_the_node_going(rig):
    s = spec(methods=[
        {'method': 'maybe', 'inputs': [{'topic': '/a', 'kind': 'float'}],
         'outputs': [{'topic': '/ma', 'kind': 'float'}]},
        {'method': 'boom', 'inputs': [{'topic': '/b', 'kind': 'float'}],
         'outputs': [{'topic': '/mb', 'kind': 'float'}]}])
    r = rig(class_spec=s)
    r.feed(-1, binding=0)
    r.feed(5, binding=0)
    r.feed(1, binding=1)
    r.feed(6, binding=0)
    assert r.values() == [5.0, 6.0]
    snap = r.core.snapshot()
    assert snap['stats']['skipped'] == 1 and snap['stats']['errors'] == 1
    assert snap['last_error']['kind'] == 'call'
    assert 'ZeroDivisionError' in snap['last_error']['message']
    assert snap['last_error']['location'].startswith('my_ros_pkg') is False
    assert snap['last_error']['location'].startswith('cl_pkg/stateful.py:')


def test_dict_return_goes_to_one_topic_per_key(rig):
    s = spec(methods=[{'method': 'stats', 'inputs': [{'topic': '/in', 'kind': 'float'}],
                       'outputs': [{'topic': '/total', 'kind': 'float', 'key': 'total'},
                                   {'topic': '/count', 'kind': 'int', 'key': 'count'},
                                   {'topic': '/never', 'kind': 'float', 'key': 'absent'}]}],
             actions=[])
    r = rig(class_spec=s)
    r.feed(4)
    assert [(b, o, type(m).__name__, m.data) for b, o, m in r.sent] == [
        (0, 0, 'Float64', 0.0), (0, 1, 'Int64', 1)]
    assert r.core.snapshot()['methods'][0]['ignored_keys'] == ['extra']


def test_keyed_outputs_need_a_dict(rig):
    s = spec(methods=[{'method': 'add', 'inputs': [{'topic': '/in', 'kind': 'float'}],
                       'outputs': [{'topic': '/t', 'kind': 'float', 'key': 'total'}]}],
             actions=[])
    r = rig(class_spec=s)
    r.feed(1)
    assert r.sent == []
    assert r.core.snapshot()['last_error']['kind'] == 'convert'
    assert 'dict' in r.core.snapshot()['last_error']['message']


def test_wrong_return_type_is_a_conversion_error(rig):
    s = spec(methods=[{'method': 'add', 'inputs': [{'topic': '/in', 'kind': 'float'}],
                       'outputs': [{'topic': '/t', 'kind': 'string'}]}], actions=[])
    r = rig(class_spec=s)
    r.feed(1)
    assert r.sent == [] and r.core.snapshot()['last_error']['kind'] == 'convert'


def test_multi_input_joins_the_latest_values(rig):
    s = spec(methods=[{'method': 'mix', 'call': 'multi_input',
                       'inputs': [{'topic': '/a', 'kind': 'float'},
                                  {'topic': '/b', 'kind': 'float'}],
                       'outputs': [{'topic': '/sum', 'kind': 'float'}], 'trigger': '/b'}],
             actions=[])
    r = rig(class_spec=s)
    r.feed(1, index=0)
    r.feed(10, index=1)
    r.feed(2, index=0)     # not the trigger
    r.feed(20, index=1)
    assert r.values() == [11.0, 22.0]
    assert r.core.snapshot()['stats']['waiting'] == 1


def test_periodic_passes_elapsed_seconds_only_when_wanted(rig):
    s = spec(methods=[{'method': 'since', 'call': 'periodic', 'rate_hz': 5,
                       'outputs': [{'topic': '/t', 'kind': 'float'}]},
                      {'method': 'tick', 'call': 'periodic', 'rate_hz': 5,
                       'outputs': [{'topic': '/n', 'kind': 'float'}]}], actions=[])
    r = rig(class_spec=s)
    time.sleep(0.05)
    r.core.tick(0)
    r.core.tick(1)
    r.sync()
    by_output = {b: m.data for b, _, m in r.sent}
    assert 0.04 < by_output[0] < 2 and by_output[1] == 1.0


def test_ticks_are_not_queued_up_behind_a_slow_call(ws):
    r = Rig(ws, spec(methods=[{'method': 'tick', 'call': 'periodic', 'rate_hz': 5,
                               'outputs': [{'topic': '/n', 'kind': 'float'}]}], actions=[]))
    gate = threading.Event()
    r.core.executor.submit(gate.wait)        # the worker is busy
    for _ in range(50):
        r.core.tick(0)
    gate.set()
    r.sync()
    assert len(r.sent) == 1
    r.close()


def test_full_queue_drops_and_counts(ws):
    r = Rig(ws)
    r.core.executor.close = None
    gate = threading.Event()
    r.core.executor.submit(gate.wait)
    from roshanavi.function import serial
    dropped_before = r.core.snapshot()['stats']['dropped']
    for _ in range(serial.MAX_PENDING + 5):
        r.core.on_message(0, 0, Float64(data=1.0))
    assert r.core.snapshot()['stats']['dropped'] - dropped_before >= 5
    gate.set()
    r.close()


# ---- actions ------------------------------------------------------------------------------
def test_action_call_is_recorded_with_result_and_error(rig):
    s = spec(actions=['reset', 'fail', 'tick'])
    r = rig(class_spec=s)
    r.feed(5)
    assert r.core.call_action('reset')
    assert r.core.call_action('fail')
    assert not r.core.call_action('unknown')
    r.sync()
    actions = r.core.snapshot()['actions']
    assert actions['reset']['count'] == 1 and actions['reset']['ok'] is True
    assert actions['reset']['result'] == '7' and actions['reset']['topic'] == '~/reset'
    assert actions['reset']['last_at'] is not None
    assert actions['fail']['ok'] is False
    assert 'RuntimeError: nope' in actions['fail']['error']['message']
    assert actions['fail']['error']['location'].startswith('cl_pkg/stateful.py:')
    assert actions['tick']['count'] == 0
    r.feed(2)
    assert r.values() == [5.0, 2.0]    # reset() really cleared the total


def test_action_changes_are_pushed_to_the_status_hook(rig):
    r = rig()
    changes = []
    r.core.on_change = lambda: changes.append(r.core.snapshot()['actions']['reset']['count'])
    r.core.call_action('reset')
    r.sync()
    assert changes == [1]


# ---- parameters -----------------------------------------------------------------------------
def test_state_is_starting_until_the_first_instance_exists(ws):
    r = Rig(ws, start=False)
    assert r.core.snapshot()['state'] == 'starting'
    r.core.start()
    r.sync()
    assert r.core.snapshot()['state'] == 'running'
    r.close()


def test_declarations_use_spec_values_then_defaults(ws):
    r = Rig(ws, spec(params={'scale': 4, 'start': 2, 'config': '{"a": 1}'}), start=False)
    decl = {p.name: (p.kind, v) for p, v in r.core.declarations()}
    assert decl['scale'] == ('int', 4)
    assert decl['start'] == ('float', 2.0) and isinstance(decl['start'][1], float)
    assert decl['label'] == ('string', 'acc')
    assert decl['gains'] == ('numbers', [])
    assert decl['note'] == ('string', UNSET)        # default None: not set, class default applies
    assert decl['config'] == ('json', {'a': 1})
    r.close()


def test_unknown_or_bad_spec_params_are_shown_as_warnings(ws):
    r = Rig(ws, spec(params={'nope': 1, 'scale': 'x'}), start=False)
    warnings = r.core.snapshot()['warnings']
    assert any('nope' in w for w in warnings) and any('scale' in w for w in warnings)
    r.close()


def test_parameter_change_recreates_the_instance_and_resets_state(rig):
    r = rig()
    r.feed(1)
    old = r.instance
    ok, reason = r.core.apply_params({'scale': 10})
    assert (ok, reason) == (True, '')
    assert r.instance is not old and old.closed
    r.feed(1)
    assert r.values() == [1.0, 10.0]              # state was reset and scale applies
    snap = r.core.snapshot()
    assert snap['notice']['kind'] == 'reset' and snap['notice']['reason'] == 'param'
    assert snap['stats']['resets'] == 1
    assert [p['value'] for p in snap['params'] if p['name'] == 'scale'] == [10]


def test_invalid_parameter_keeps_the_old_instance_and_says_why(rig):
    r = rig()
    r.feed(1)
    old = r.instance
    ok, reason = r.core.apply_params({'scale': 0})
    assert not ok and 'scale must be 1 or more' in reason
    assert r.instance is old and not old.closed
    r.feed(1)
    assert r.values() == [1.0, 2.0]                 # the old instance went on
    assert r.core.snapshot()['last_error']['kind'] == 'param'


def test_on_param_change_hook_keeps_the_instance(ws):
    write(ws / 'src' / 'my_ros_pkg' / 'cl_pkg' / 'stateful.py', KEEPING)
    r = Rig(ws)
    r.feed(2)
    old = r.instance
    assert r.core.apply_params({'scale': 5}) == (True, '')
    assert r.instance is old and old.scale == 5 and not old.closed
    r.feed(1)
    assert r.values() == [2.0, 7.0]
    ok, reason = r.core.apply_params({'scale': -1})
    assert not ok and 'must not be negative' in reason and old.scale == 5
    assert r.core.snapshot()['stats']['resets'] == 0
    r.close()


def test_required_argument_without_a_value_waits_for_the_parameter(ws):
    write(ws / 'src' / 'my_ros_pkg' / 'cl_pkg' / 'req.py', '''\
class Need:
    def __init__(self, size: int):
        self.size = size

    def go(self, x: float) -> float:
        return x * self.size
''')
    s = ClassSpec.model_validate({'id': 'n', 'name': 'n', 'module': 'cl_pkg.req',
                                  'class_name': 'Need',
                                  'methods': [{'method': 'go', 'inputs': [{'topic': '/i'}],
                                               'outputs': [{'topic': '/o', 'kind': 'float'}]}]})
    r = Rig(ws, s, module='cl_pkg.req')
    snap = r.core.snapshot()
    assert snap['state'] == 'init_error' and 'size' in snap['problem']['message']
    assert snap['params'][0]['required'] is True
    assert r.core.apply_params({'size': 3}) == (True, '')
    assert r.core.snapshot()['state'] == 'running'
    r.close()


# ---- init failure and hot reload ---------------------------------------------------------------
def test_init_failure_waits_for_a_fix(ws):
    r = Rig(ws, spec(params={'scale': 0}))
    snap = r.core.snapshot()
    assert snap['state'] == 'init_error'
    assert snap['problem']['kind'] == 'init' and '初期化に失敗' in snap['problem']['message']
    assert 'scale must be 1 or more' in snap['problem']['message']
    assert snap['problem']['location'].startswith('cl_pkg/stateful.py:')
    r.feed(1)
    assert r.sent == [] and r.core.snapshot()['stats']['skipped'] == 1
    ok, _ = r.core.apply_params({'scale': 2})        # the user fixes the parameter
    assert ok and r.core.snapshot()['state'] == 'running'
    r.feed(1)
    assert r.values() == [2.0]
    r.close()


def test_reload_creates_a_new_instance_and_resets(ws):
    r = Rig(ws)
    r.feed(3)
    old = r.instance
    write(ws / 'src' / 'my_ros_pkg' / 'cl_pkg' / 'stateful.py',
          STATEFUL.replace('x * self.scale', 'x * self.scale + 100'))
    assert r.loader.changed()
    r.core.reload()
    r.core.on_reload(None)
    assert r.instance is not old and old.closed
    r.feed(1)
    assert r.values() == [3.0, 101.0]
    snap = r.core.snapshot()
    assert snap['notice']['kind'] == 'reset' and snap['notice']['reason'] == 'reload'
    assert snap['stats']['reloads'] == 1 and snap['loads'] == 2
    r.close()


def test_reload_transfers_state_when_the_class_can(ws):
    write(ws / 'src' / 'my_ros_pkg' / 'cl_pkg' / 'stateful.py', KEEPING)
    r = Rig(ws)
    r.feed(3)
    old = r.instance
    write(ws / 'src' / 'my_ros_pkg' / 'cl_pkg' / 'stateful.py',
          KEEPING.replace('self.total += x * self.scale', 'self.total += x * self.scale * 2'))
    r.core.reload()
    assert r.instance is not old and old.closed
    r.feed(1)
    assert r.values() == [3.0, 5.0]               # 3 carried over, new code adds 2
    snap = r.core.snapshot()
    assert snap['notice']['kind'] == 'kept' and snap['stats']['resets'] == 0
    r.close()


def test_failed_reloads_keep_the_old_instance_running(ws):
    path = ws / 'src' / 'my_ros_pkg' / 'cl_pkg' / 'stateful.py'
    fragile = KEEPING.replace("        return {'total': self.total}",
                              "        if self.total > 100:\n            raise KeyError('big')\n"
                              "        return {'total': self.total}")
    write(path, fragile)
    r = Rig(ws)
    r.feed(3)
    old = r.instance

    write(path, 'class Acc:\n    def __init__(self:\n')          # syntax error
    with pytest.raises(LoadError) as err:
        r.core.reload()
    assert err.value.problem.kind == 'import'
    assert r.instance is old and r.core.snapshot()['state'] == 'reload_error'

    write(path, fragile.replace('self.total = 0.0\n        self.scale = scale',
                                'raise ValueError("bad init")'))      # __init__ fails
    with pytest.raises(LoadError) as err:
        r.core.reload()
    assert err.value.problem.kind == 'init' and 'bad init' in err.value.problem.message
    assert r.instance is old and not old.closed
    snap = r.core.snapshot()
    assert snap['state'] == 'reload_error' and snap['problem']['kind'] == 'init'

    write(path, fragile.replace("self.total = state['total']", "raise KeyError('total')"))
    with pytest.raises(LoadError) as err:                              # set_state fails
        r.core.reload()
    assert err.value.problem.kind == 'state' and 'set_state' in err.value.problem.message
    assert r.instance is old and not old.closed

    r.feed(1)
    assert r.values() == [3.0, 4.0]                  # still the old instance, still working

    r.feed(500)                                       # now the OLD get_state() fails
    write(path, fragile)
    with pytest.raises(LoadError) as err:
        r.core.reload()
    assert err.value.problem.kind == 'state' and 'get_state' in err.value.problem.message
    assert r.instance is old and not old.closed
    r.core.call_action('reset')

    write(path, fragile.replace('x * self.scale', 'x * self.scale + 1'))   # fixed: it clears
    r.core.reload()
    r.core.on_reload(None)
    snap = r.core.snapshot()
    assert snap['state'] == 'running' and snap['problem'] is None
    assert r.instance is not old and old.closed
    r.close()


def test_reload_that_changes_the_signature_redeclares_parameters(ws):
    r = Rig(ws)
    path = ws / 'src' / 'my_ros_pkg' / 'cl_pkg' / 'stateful.py'
    write(path, STATEFUL.replace("label: str = 'acc',", "label: str = 'acc', mode: str = 'fast',"))
    r.core.reload()
    names = [p.name for p, _ in r.declared[-1]]
    assert 'mode' in names and 'scale' in names
    write(path, STATEFUL.replace("scale: int = 1, ", '').replace(
        "        if scale < 1:\n            raise ValueError(f'scale must be 1 or more (got {scale})')\n",
        '').replace('self.total, self.scale, self.label = start, scale, label',
                   'self.total, self.scale, self.label = start, 1, label'))
    r.core.reload()
    assert 'scale' not in [p.name for p, _ in r.declared[-1]]
    r.close()


def test_watcher_reloads_on_save_through_the_worker(ws):
    r = Rig(ws)
    problems = []
    watcher = Watcher(r.loader, lambda p: (problems.append(p), r.core.on_reload(p)),
                      poll_sec=0.05, reload_fn=r.core.reload)
    watcher.start()
    try:
        write(ws / 'src' / 'my_ros_pkg' / 'cl_pkg' / 'stateful.py',
              STATEFUL.replace('x * self.scale', 'x * 1000'))
        deadline = time.monotonic() + 10
        while not problems and time.monotonic() < deadline:
            time.sleep(0.05)
        assert problems == [None]
        r.feed(1)
        assert r.values() == [1000.0]
        write(ws / 'src' / 'my_ros_pkg' / 'cl_pkg' / 'stateful.py', 'class Acc(:\n')
        deadline = time.monotonic() + 10
        while len(problems) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert problems[1].kind == 'import'
        r.feed(1)
        assert r.values() == [1000.0, 2000.0]
    finally:
        watcher.close()
        r.close()


def test_import_error_at_start_then_fix(ws):
    path = ws / 'src' / 'my_ros_pkg' / 'cl_pkg' / 'late.py'
    write(path, 'class Acc(:\n')
    loader = ClassLoader(str(ws), 'cl_pkg.late', 'Acc')
    with pytest.raises(LoadError):
        loader.load()
    core = ClassCore(spec(), loader, lambda *a: None)
    core.start()
    assert core.snapshot()['state'] == 'import_error'
    write(path, 'class Acc:\n    def add(self, x):\n        return x\n    def reset(self):\n'
                '        pass\n')
    core.reload()
    assert core.snapshot()['state'] == 'running'
    core.close()


def test_missing_class_is_a_load_error(ws):
    loader = ClassLoader(str(ws), 'cl_pkg.stateful', 'Nope')
    with pytest.raises(LoadError) as err:
        loader.load()
    assert 'has no class' in err.value.problem.message
    loader = ClassLoader(str(ws), 'cl_pkg.stateful', 'Acc')
    loader.function_name = 'Acc'
    write(ws / 'src' / 'my_ros_pkg' / 'cl_pkg' / 'func.py', 'def Acc():\n    pass\n')
    loader = ClassLoader(str(ws), 'cl_pkg.func', 'Acc')
    with pytest.raises(LoadError) as err:
        loader.load()
    assert 'is not a class' in err.value.problem.message


# ---- stop ------------------------------------------------------------------------------------
def test_close_is_called_when_the_node_stops(ws):
    r = Rig(ws)
    instance = r.instance
    r.close()
    assert instance.closed and r.core.snapshot()['state'] == 'stopped'


def test_close_twice_is_harmless(ws):
    r = Rig(ws)
    instance = r.instance
    r.close()
    r.close()
    assert instance.closed


def test_an_unexpected_failure_while_reloading_is_a_load_error_not_a_dead_watcher(ws):
    r = Rig(ws)

    def broken(_declarations):
        raise RuntimeError('cannot declare')
    r.core.on_signature = broken
    write(ws / 'src' / 'my_ros_pkg' / 'cl_pkg' / 'stateful.py', STATEFUL + '\n# edit\n')
    with pytest.raises(LoadError) as err:
        r.core.reload()
    assert 'cannot declare' in err.value.problem.message
    r.close()


def test_shutdown_is_used_when_there_is_no_close(ws):
    write(ws / 'src' / 'my_ros_pkg' / 'cl_pkg' / 'sd.py', '''\
class Acc:
    def __init__(self):
        self.down = False

    def add(self, x):
        return x

    def reset(self):
        pass

    def shutdown(self):
        self.down = True
''')
    r = Rig(ws, module='cl_pkg.sd')
    instance = r.instance
    r.close()
    assert instance.down


def test_close_errors_are_reported_not_raised(ws):
    write(ws / 'src' / 'my_ros_pkg' / 'cl_pkg' / 'bad_close.py', '''\
class Acc:
    def add(self, x):
        return x

    def reset(self):
        pass

    def close(self):
        raise OSError('disk gone')
''')
    r = Rig(ws, module='cl_pkg.bad_close')
    r.close()
    assert 'disk gone' in r.core.snapshot()['last_error']['message']
    assert r.core.snapshot()['last_error']['kind'] == 'close'


def test_a_hanging_close_does_not_block_shutdown_for_long(ws, monkeypatch):
    from roshanavi.function import class_core
    monkeypatch.setattr(class_core, 'CLOSE_TIMEOUT_SEC', 0.3)
    write(ws / 'src' / 'my_ros_pkg' / 'cl_pkg' / 'hang.py', '''\
import time


class Acc:
    def add(self, x):
        return x

    def reset(self):
        pass

    def close(self):
        time.sleep(30)
''')
    r = Rig(ws, module='cl_pkg.hang')
    started = time.monotonic()
    r.close()
    assert time.monotonic() - started < 3


# ---- single thread -----------------------------------------------------------------------------
def test_user_code_only_ever_runs_on_one_thread_one_call_at_a_time(ws):
    write(ws / 'src' / 'my_ros_pkg' / 'cl_pkg' / 'busy.py', '''\
import threading
import time

THREADS = set()
ACTIVE = [0]
OVERLAPS = [0]


class Acc:
    def __init__(self, scale: int = 1):
        self.track()

    def track(self):
        THREADS.add(threading.get_ident())
        ACTIVE[0] += 1
        if ACTIVE[0] > 1:
            OVERLAPS[0] += 1
        time.sleep(0.0005)
        ACTIVE[0] -= 1

    def add(self, x: float) -> float:
        self.track()
        return x

    def reset(self):
        self.track()

    def close(self):
        self.track()
''')
    r = Rig(ws, module='cl_pkg.busy')

    def hammer():
        for i in range(40):
            r.core.on_message(0, 0, Float64(data=float(i)))
            r.core.call_action('reset')
            if i % 10 == 0:
                r.core.apply_params({'scale': i + 1})
    threads = [threading.Thread(target=hammer) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    r.sync()
    import sys
    busy = sys.modules['cl_pkg.busy']
    assert len(busy.THREADS) == 1 and busy.OVERLAPS[0] == 0
    assert next(iter(busy.THREADS)) == r.core.executor.ident
    assert threading.get_ident() not in busy.THREADS
    r.close()


def test_serial_executor_runs_inline_on_its_own_thread():
    ex = SerialExecutor('t')
    assert ex.run(lambda: ex.on_worker()) is True
    assert ex.run(lambda: ex.run(lambda: threading.get_ident())) == ex.ident
    with pytest.raises(ZeroDivisionError):
        ex.run(lambda: 1 / 0)
    ex.stop()
    assert ex.submit(lambda: None) is False


# ---- code export -------------------------------------------------------------------------------
def many(**kw):
    return spec(
        params={'scale': 3, 'gains': [1, 2]},
        methods=[
            {'method': 'add', 'inputs': [{'topic': '/in', 'kind': 'float'}],
             'outputs': [{'topic': '/out', 'kind': 'float'}]},
            {'method': 'stats', 'inputs': [{'topic': '/in2', 'kind': 'float'}],
             'outputs': [{'topic': '/t', 'kind': 'float', 'key': 'total'},
                         {'topic': '/c', 'kind': 'int', 'key': 'count'}]},
            {'method': 'mix', 'call': 'multi_input', 'trigger': '/b',
             'inputs': [{'topic': '/a', 'kind': 'float'}, {'topic': '/b', 'kind': 'float'}],
             'outputs': [{'topic': '/sum', 'kind': 'json'}]},
            {'method': 'since', 'call': 'periodic', 'rate_hz': 2,
             'outputs': [{'topic': '/since', 'kind': 'float'}]},
            {'method': 'tick', 'call': 'periodic', 'rate_hz': 1,
             'outputs': [{'topic': '/tick', 'kind': 'float',
                          'qos': {'reliability': 'best_effort', 'depth': 3}}]}],
        actions=['reset', 'fail'], **kw)


@pytest.mark.parametrize('lifecycle', [False, True])
def test_generated_code_compiles(ws, lifecycle):
    source = class_codegen.generate(many(), str(ws), lifecycle)
    compile(source, 'gen.py', 'exec')
    assert source.startswith('#!/usr/bin/env python3\n' + class_codegen.MARKER)
    assert 'from cl_pkg.stateful import Acc' in source
    assert ('LifecycleNode' in source) is lifecycle
    assert ('def on_configure' in source) is lifecycle
    for needle in ("self.declare_parameter('scale', 3)", "'gains': list", "'config': json.loads",
                   "Empty, '~/reset'", 'def on_timer_since', 'time.monotonic() - self.started',
                   'def on_timer_tick'):
        assert needle in source
    assert 'self.run_method(\'tick\', [])' in source


def test_generated_code_embeds_only_validated_values(ws):
    s = spec(params={'label': "x'); import os; os.system('true') #"})
    source = class_codegen.generate(s, str(ws), False)
    compile(source, 'gen.py', 'exec')
    assert "import os; os.system" in source
    assert repr("x'); import os; os.system('true') #") in source
    for bad in ("x\n", "x\x00y", "a\x1b"):
        with pytest.raises(LauncherError):
            class_codegen.export_code(s, str(ws), bad)


def test_generated_hooks_follow_the_class(ws):
    plain = class_codegen.generate(spec(), str(ws), False)
    assert 'instance.close()' in plain
    assert 'No on_param_change()' in plain          # Acc has none: recreate on a change
    write(ws / 'src' / 'my_ros_pkg' / 'cl_pkg' / 'stateful.py', KEEPING)
    kept = class_codegen.generate(spec(), str(ws), False)
    assert 'self.instance.on_param_change(name' in kept
    assert 'No on_param_change()' not in kept


def test_unknown_class_is_refused(ws):
    with pytest.raises(LauncherError) as err:
        class_codegen.generate(spec(class_name='Nope'), str(ws))
    assert err.value.code == 'unknown_class'


def test_export_code_writes_and_protects_user_files(ws, tmp_path):
    out = ws / 'export'
    result = class_codegen.export_code(spec(), str(ws), str(out), lifecycle=True)
    text = (out / 'acc_node.py').read_text()
    assert result['file'] == str(out / 'acc_node.py') and 'LifecycleNode' in text
    class_codegen.export_code(spec(), str(ws), str(out))          # own file: replaced
    assert 'LifecycleNode' not in (out / 'acc_node.py').read_text()
    (out / 'acc_node.py').write_text('# my own code\n')
    with pytest.raises(LauncherError) as err:
        class_codegen.export_code(spec(), str(ws), str(out))
    assert err.value.code == 'file_exists' and (out / 'acc_node.py').read_text() == '# my own code\n'


# ---- the map: action topics are one-sided on purpose -------------------------------------------
def test_action_topics_are_not_reported_as_missing_publishers(ws, tmp_path, data_dir):
    from roshanavi.diagnostics import diagnose
    from roshanavi.launcher.service import Launcher
    snapshot = {'topics': [{'name': '/acc/reset', 'types': ['std_msgs/msg/Empty']},
                           {'name': '/other', 'types': ['std_msgs/msg/Empty']}],
                'edges': [{'node': '/acc', 'topic': '/acc/reset', 'dir': 'sub', 'qos': {}},
                          {'node': '/x', 'topic': '/other', 'dir': 'sub', 'qos': {}}]}
    assert [d['topic'] for d in diagnose(snapshot)] == ['/acc/reset', '/other']
    assert [d['topic'] for d in diagnose(snapshot, ['/acc/reset'])] == ['/other']
    launcher = Launcher(str(ws), str(data_dir), project_path=str(tmp_path / 'p.yaml'),
                        autostart=False)
    try:
        launcher.manager.add(spec(actions=['reset', 'tick'], namespace='/ns'))
        assert launcher.manager.action_topics() == ['/ns/acc/reset', '/ns/acc/tick']
    finally:
        launcher.close()
