"""Function nodes without a running ROS graph: modules, loader / hot reload, core, codegen."""

import logging
import os
import textwrap
import time

import numpy as np
import pytest
from pydantic import ValidationError
from sensor_msgs.msg import Image
from std_msgs.msg import Float64, String

from roshanavi import data_kinds
from roshanavi.function import codegen, modules
from roshanavi.function.core import FunctionCore
from roshanavi.function.loader import FunctionLoader, LoadError, Watcher
from roshanavi.launcher.dummy_config import function_config_text, load_function_config
from roshanavi.launcher.errors import LauncherError
from roshanavi.launcher.schema import FunctionSpec
from ws_fixtures import fake_source

LOGIC = '''\
import time
from fn_pkg.helper import suffix


def shout(text: str) -> str:
    return text.upper() + suffix()


def maybe(text: str) -> str:
    return None if text == 'skip' else text


def boom(text: str) -> str:
    return 1 / 0


def wrong(text: str) -> int:
    return 'not an int'


def add(a: float, b: float) -> float:
    return a + b


def tick() -> float:
    return 1.0


def since(t: float) -> float:
    return t


def invert(image):
    return 255 - image


def parse(value: dict) -> dict:
    return {'got': value['n'] * 2}


def _private():
    pass
'''


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text))
    # Make sure the mtime differs even on coarse filesystems.
    stamp = time.time() + write.bump
    write.bump += 1
    os.utime(path, (stamp, stamp))


write.bump = 1


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / 'ws'
    pkg = fake_source(root / 'src', 'my_ros_pkg')
    write(pkg / 'fn_pkg' / '__init__.py', '')
    write(pkg / 'fn_pkg' / 'helper.py', "def suffix():\n    return '!'\n")
    write(pkg / 'fn_pkg' / 'logic.py', LOGIC)
    write(pkg / 'fn_pkg' / 'sub' / '__init__.py', '')
    write(pkg / 'fn_pkg' / 'sub' / 'deep.py', 'def f(x: str) -> str:\n    return x\n')
    write(pkg / 'test' / '__init__.py', '')
    write(pkg / 'test' / 'test_x.py', 'def test(): pass\n')
    return root


def spec(**kw):
    base = {'id': 'fn', 'name': 'fn', 'module': 'fn_pkg.logic', 'function': 'shout',
            'inputs': [{'topic': '/in', 'kind': 'string'}],
            'output': {'topic': '/out', 'kind': 'string'}}
    return FunctionSpec.parse_obj({**base, **kw})


# ---- modules (no import) -------------------------------------------------------------------
def test_lists_workspace_modules_only(ws):
    names = [m['module'] for m in modules.list_modules(str(ws))]
    assert names == ['fn_pkg', 'fn_pkg.helper', 'fn_pkg.logic', 'fn_pkg.sub', 'fn_pkg.sub.deep']
    assert modules.list_modules(str(ws))[2]['file'] == 'src/my_ros_pkg/fn_pkg/logic.py'


def test_resolution_is_contained(ws, tmp_path):
    pkg = ws / 'src' / 'my_ros_pkg' / 'fn_pkg'
    outside = tmp_path / 'outside.py'
    outside.write_text('def f(x): return x\n')
    os.symlink(outside, pkg / 'evil.py')
    (tmp_path / 'elsewhere' / 'esc_pkg').mkdir(parents=True)
    (tmp_path / 'elsewhere' / 'esc_pkg' / '__init__.py').write_text('')
    os.symlink(tmp_path / 'elsewhere' / 'esc_pkg', ws / 'src' / 'my_ros_pkg' / 'esc_pkg')
    assert modules.resolve_module(str(ws), 'fn_pkg.logic').file == str((pkg / 'logic.py').resolve())
    for bad, code in [('fn_pkg.evil', 'unknown_module'), ('esc_pkg', 'unknown_module'),
                      ('roshanavi.server', 'invalid_module'), ('os', 'unknown_module'),
                      ('../etc', 'invalid_module'), ('fn_pkg.nope', 'unknown_module')]:
        with pytest.raises(LauncherError) as err:
            modules.resolve_module(str(ws), bad)
        assert err.value.code == code, bad
    assert 'esc_pkg' not in [m['module'] for m in modules.list_modules(str(ws))]
    assert 'fn_pkg.evil' not in [m['module'] for m in modules.list_modules(str(ws))]


def test_signatures_are_read_without_importing(ws, tmp_path):
    marker = tmp_path / 'imported'
    write(ws / 'src' / 'my_ros_pkg' / 'fn_pkg' / 'side.py', f'''\
        open({str(marker)!r}, 'w').write('x')
        def g(img: 'np.ndarray', n: int = 3) -> bytes:
            """Docs here.

            More."""
    ''')
    info = modules.describe_module(str(ws), 'fn_pkg.side')
    assert not marker.exists()
    (g,) = info['functions']
    assert g['signature'] == "g(img: 'np.ndarray', n: int=3) -> bytes"
    assert [(p['name'], p['kind'], p['optional']) for p in g['params']] == [
        ('img', 'image', False), ('n', 'int', True)]
    assert (g['required'], g['returns_kind'], g['doc']) == (1, 'bytes', 'Docs here.')
    names = [f['name'] for f in modules.describe_module(str(ws), 'fn_pkg.logic')['functions']]
    assert 'shout' in names and '_private' not in names
    write(ws / 'src' / 'my_ros_pkg' / 'fn_pkg' / 'broken.py', 'def x(:\n')
    with pytest.raises(LauncherError, match='broken.py:1'):
        modules.describe_module(str(ws), 'fn_pkg.broken')


@pytest.mark.parametrize('annotation,kind', [
    ('str', 'string'), ('Optional[str]', 'string'), ('List[float]', 'numbers'),
    ('np.ndarray', 'image'), ('Dict[str, int]', 'json'), (None, None), ('MyType', None)])
def test_suggest_kind(annotation, kind):
    assert modules.suggest_kind(annotation) == kind


# ---- loader / hot reload ------------------------------------------------------------------------
def test_load_reload_and_keep_old_on_errors(ws):
    logic = ws / 'src' / 'my_ros_pkg' / 'fn_pkg' / 'logic.py'
    loader = FunctionLoader(str(ws), 'fn_pkg.logic', 'shout')
    assert loader.load()('hi') == 'HI!'
    assert loader.location_of_function() == 'fn_pkg/logic.py:5'
    assert not loader.changed()
    write(logic, LOGIC.replace("text.upper() + suffix()", "text.lower() + suffix()"))
    assert loader.changed()
    assert loader.load()('Hi') == 'hi!'
    # A helper module of the same package is watched and reloaded too.
    write(ws / 'src' / 'my_ros_pkg' / 'fn_pkg' / 'helper.py', "def suffix():\n    return '?'\n")
    assert loader.changed()
    assert loader.load()('a') == 'a?'
    # A syntax error keeps the previous function, with the place of the error.
    write(logic, 'def shout(text):\n    return (\n')
    with pytest.raises(LoadError) as err:
        loader.load()
    assert err.value.problem.kind == 'import'
    assert err.value.problem.location.startswith('fn_pkg/logic.py:')
    assert loader.function('a') == 'a?' and loader.problem is not None
    assert not loader.changed()  # the broken file is watched (no reload loop)
    # A renamed function and an exception at import time are reported the same way.
    write(logic, 'def other(text):\n    return text\n')
    with pytest.raises(LoadError, match="no function 'shout'"):
        loader.load()
    write(logic, 'raise RuntimeError("at import")\n')
    with pytest.raises(LoadError) as err:
        loader.load()
    assert err.value.problem.location == 'fn_pkg/logic.py:1 (<module>)'
    write(logic, LOGIC)
    assert loader.load()('ok') == 'OK?' and loader.problem is None


def test_watcher_reloads_on_save(ws):
    logic = ws / 'src' / 'my_ros_pkg' / 'fn_pkg' / 'logic.py'
    loader = FunctionLoader(str(ws), 'fn_pkg.logic', 'shout')
    loader.load()
    events = []
    watcher = Watcher(loader, events.append, poll_sec=0.05)
    watcher.start()
    try:
        write(logic, LOGIC.replace("+ suffix()", "+ '#'"))
        deadline = time.monotonic() + 5
        while not events and time.monotonic() < deadline:
            time.sleep(0.05)
        assert events == [None]
        assert loader.function('x') == 'X#'
    finally:
        watcher.close()


def test_missing_module_is_a_load_error(ws):
    loader = FunctionLoader(str(ws), 'fn_pkg.nothing', 'f')
    with pytest.raises(LoadError, match='not found'):
        loader.load()
    assert loader.function is None


# ---- core: values, None, exceptions, joins, periodic -------------------------------------------
def make_core(ws, **kw):
    s = spec(**kw)
    loader = FunctionLoader(str(ws), s.module, s.function)
    loader.load()
    sent = []
    return FunctionCore(s, loader, sent.append), sent


def test_on_message_converts_both_ways(ws):
    core, sent = make_core(ws)
    core.on_message(0, String(data='hey'))
    assert [m.data for m in sent] == ['HEY!']
    assert core.snapshot()['stats']['published'] == 1


def test_none_sends_nothing(ws):
    core, sent = make_core(ws, function='maybe')
    core.on_message(0, String(data='skip'))
    core.on_message(0, String(data='keep'))
    assert [m.data for m in sent] == ['keep']
    assert core.stats.skipped == 1


class _Lines(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def test_exception_is_reported_with_line_and_the_node_goes_on(ws):
    core, sent = make_core(ws, function='boom')
    handler = _Lines()
    logging.getLogger('roshanavi.function').addHandler(handler)
    try:
        core.on_message(0, String(data='a'))
        core.on_message(0, String(data='b'))
    finally:
        logging.getLogger('roshanavi.function').removeHandler(handler)
    assert sent == [] and core.stats.errors == 2 and core.stats.calls == 2
    err = core.snapshot()['last_error']
    assert err['kind'] == 'call' and err['message'] == 'ZeroDivisionError: division by zero'
    assert err['location'] == 'fn_pkg/logic.py:14 (boom)'
    assert len(handler.lines) == 1 and '関数でエラーが起きました' in handler.lines[0]  # rate-limited


def test_wrong_return_type_is_a_conversion_error(ws):
    core, sent = make_core(ws, function='wrong', output={'topic': '/out', 'kind': 'int'})
    core.on_message(0, String(data='a'))
    assert sent == []
    err = core.snapshot()['last_error']
    assert err['kind'] == 'convert' and 'returned str' in err['message']


def test_json_and_image_values(ws):
    core, sent = make_core(ws, function='parse', inputs=[{'topic': '/in', 'kind': 'json'}],
                           output={'topic': '/out', 'kind': 'json'})
    core.on_message(0, String(data='{"n": 21}'))
    assert sent[0].data == '{"got": 42}'
    core.on_message(0, String(data='not json'))
    assert core.snapshot()['last_error']['kind'] == 'convert'
    core, sent = make_core(ws, function='invert', inputs=[{'topic': '/in', 'kind': 'image'}],
                           output={'topic': '/out', 'kind': 'image'})
    img = data_kinds.from_python('image', np.full((2, 3, 3), 10, np.uint8), 'sensor_msgs/msg/Image')
    img.header.stamp.sec = 77
    core.on_message(0, img)
    out = sent[0]
    assert isinstance(out, Image) and out.encoding == 'rgb8' and set(out.data) == {245}
    assert out.header.stamp.sec == 77  # the input's stamp is kept (latency stays measurable)


def test_multi_input_waits_then_joins_latest(ws):
    inputs = [{'topic': '/a', 'kind': 'float'}, {'topic': '/b', 'kind': 'float'}]
    core, sent = make_core(ws, function='add', call='multi_input', inputs=inputs,
                           output={'topic': '/sum', 'kind': 'float'})
    core.on_message(0, Float64(data=1.0))
    assert sent == [] and core.stats.waiting == 1
    core.on_message(1, Float64(data=2.0))
    core.on_message(0, Float64(data=10.0))
    assert [m.data for m in sent] == [3.0, 12.0]
    core, sent = make_core(ws, function='add', call='multi_input', inputs=inputs, trigger='/b',
                           output={'topic': '/sum', 'kind': 'float'})
    core.on_message(1, Float64(data=1.0))
    core.on_message(0, Float64(data=5.0))  # stored, not the trigger
    core.on_message(1, Float64(data=2.0))
    assert [m.data for m in sent] == [7.0]


def test_periodic_with_and_without_elapsed_time(ws):
    out = {'topic': '/p', 'kind': 'float'}
    core, sent = make_core(ws, function='tick', call='periodic', inputs=[], rate_hz=10, output=out)
    core.tick()
    assert sent[0].data == 1.0
    core, sent = make_core(ws, function='since', call='periodic', inputs=[], rate_hz=10,
                           output=out)
    time.sleep(0.05)
    core.tick()
    assert 0.04 < sent[0].data < 5


def test_reload_applies_to_the_next_message(ws):
    core, sent = make_core(ws)
    core.on_message(0, String(data='a'))
    write(ws / 'src' / 'my_ros_pkg' / 'fn_pkg' / 'logic.py',
          LOGIC.replace('text.upper() + suffix()', "'v2:' + text"))
    core.loader.load()
    core.on_reload(None)
    core.on_message(0, String(data='a'))
    assert [m.data for m in sent] == ['A!', 'v2:a'] and core.stats.reloads == 1


# ---- spec / config ------------------------------------------------------------------------------
@pytest.mark.parametrize('patch,message', [
    ({'inputs': []}, 'exactly one input'),
    ({'call': 'multi_input'}, '2 or more'),
    ({'call': 'periodic'}, 'no inputs'),
    ({'call': 'periodic', 'inputs': []}, 'rate_hz'),
    ({'module': 'roshanavi.server'}, 'not roshanavi'),
    ({'function': '__init__'}, 'function'),
    ({'inputs': [{'topic': '/in', 'kind': 'message'}]}, 'needs a "type"'),
    ({'inputs': [{'topic': '/in', 'kind': 'int', 'type': 'std_msgs/msg/String'}]}, 'does not carry'),
    ({'call': 'multi_input', 'inputs': [{'topic': '/a'}, {'topic': '/b'}], 'trigger': '/c'},
     'trigger'),
    ({'output': {'topic': '/o', 'kind': 'message', 'type': 'std_msgs/msg/String\nimport os'}},
     'type'),
])
def test_spec_validation(patch, message):
    with pytest.raises(ValidationError, match=message):
        spec(**patch)


def test_config_round_trip(tmp_path):
    path = tmp_path / 'fn.yaml'
    path.write_text(function_config_text(spec(), str(tmp_path), '/tmp/s.json'))
    loaded = load_function_config(str(path))
    assert loaded['spec'] == spec() and loaded['status_file'] == '/tmp/s.json'
    path.write_text('function: {}\n')
    with pytest.raises(LauncherError):
        load_function_config(str(path))


# ---- codegen ----------------------------------------------------------------------------------------
@pytest.mark.parametrize('patch', [
    {},
    {'function': 'invert', 'inputs': [{'topic': '/in', 'kind': 'image'}],
     'output': {'topic': '/out', 'kind': 'image'}},
    {'function': 'add', 'call': 'multi_input', 'trigger': '/b',
     'inputs': [{'topic': '/a', 'kind': 'float'}, {'topic': '/b', 'kind': 'int'}],
     'output': {'topic': '/out', 'kind': 'numbers'}},
    {'function': 'since', 'call': 'periodic', 'inputs': [], 'rate_hz': 4,
     'output': {'topic': '/out', 'kind': 'audio', 'type': 'std_msgs/msg/Int16MultiArray'}},
    {'function': 'parse', 'inputs': [{'topic': '/in', 'kind': 'json'}],
     'output': {'topic': '/out', 'kind': 'message', 'type': 'geometry_msgs/msg/Twist'}},
    {'inputs': [{'topic': '/in', 'kind': 'bytes'}], 'output': {'topic': '/out', 'kind': 'bool'}},
])
def test_generated_node_compiles(ws, patch):
    source = codegen.generate(spec(**patch), str(ws))
    compile(source, 'node.py', 'exec')
    assert source.startswith('#!/usr/bin/env python3\n' + codegen.MARKER)
    assert "from fn_pkg.logic import" in source and 'def main(args=None):' in source
    assert "entry_points={'console_scripts'" in source


def test_generated_periodic_passes_elapsed_time_only_when_wanted(ws):
    out = {'topic': '/out', 'kind': 'float'}
    with_t = codegen.generate(spec(function='since', call='periodic', inputs=[], rate_hz=2,
                                   output=out), str(ws))
    assert 'self.call_and_publish(time.monotonic() - self.started)' in with_t
    without = codegen.generate(spec(function='tick', call='periodic', inputs=[], rate_hz=2,
                                    output=out), str(ws))
    assert 'self.call_and_publish()' in without


def test_export_code_writes_and_protects_user_files(ws):
    target = ws / 'generated'
    result = codegen.export_code(spec(), str(ws), str(target))
    assert result['file'] == str(target / 'fn_node.py')
    again = codegen.export_code(spec(), str(ws), str(target))  # ours: replaced
    assert again['file'] == result['file']
    (target / 'fn_node.py').write_text('# my own code\n')
    with pytest.raises(LauncherError) as err:
        codegen.export_code(spec(), str(ws), str(target))
    assert err.value.code == 'file_exists'
    with pytest.raises(LauncherError):
        codegen.export_code(spec(), str(ws), str(target) + '\nx')
    bad_name = spec().copy(update={'name': '../../evil'})  # e.g. an invalid spec from a file
    with pytest.raises(LauncherError):
        codegen.export_code(bad_name, str(ws), str(target))
    assert not (ws / 'evil_node.py').exists()
