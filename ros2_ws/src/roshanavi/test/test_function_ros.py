"""Function nodes over real ROS: the executable with hot reload, the API, launch and code export."""

import json
import os
import shutil
import subprocess
import time
import uuid

from std_msgs.msg import String

from conftest import WS_ROOT, wait_for
from roshanavi.launcher.dummy_config import function_config_text
from roshanavi.launcher.schema import FunctionSpec
from roshanavi.launcher.service import Launcher
from test_dummy import publisher_nodes, stop_group
from test_function_unit import LOGIC, write
from ws_fixtures import fake_source


def fspec(name, **kw):
    base = {'id': name.replace('_', '-'), 'name': name, 'module': 'fn_pkg.logic',
            'function': 'shout', 'inputs': [{'topic': f'/{name}_in', 'kind': 'string'}],
            'output': {'topic': f'/{name}_out', 'kind': 'string'}}
    return FunctionSpec.parse_obj({**base, **kw})


def text_publisher(helper, topic, rate_hz, make=lambda i: f'm{i}'):
    return helper.periodic_publisher(String, topic, rate_hz, lambda i: String(data=make(i)))


def read_status(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def test_executable_hot_reload_errors_and_status(tmp_path, helper):
    ws = tmp_path / 'ws'
    pkg = fake_source(ws / 'src', 'my_ros_pkg')
    write(pkg / 'fn_pkg' / '__init__.py', '')
    write(pkg / 'fn_pkg' / 'helper.py', "def suffix():\n    return '!'\n")
    logic = pkg / 'fn_pkg' / 'logic.py'
    write(logic, LOGIC)
    spec = fspec('rn_fn_exe')
    status = tmp_path / 'status.json'
    config = tmp_path / 'fn.yaml'
    config.write_text(function_config_text(spec, str(ws), str(status)))
    out = helper.collector(String, '/rn_fn_exe_out')
    text_publisher(helper, '/rn_fn_exe_in', 10, lambda i: f'x{i}')
    proc = subprocess.Popen(['ros2', 'run', 'roshanavi', 'function', '--config', str(config),
                             '--ros-args', '-r', '__node:=rn_fn_exe'], start_new_session=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        wait_for(lambda: out and out[-1].data.endswith('!'), timeout=30)
        assert out[-1].data.startswith('X')
        assert publisher_nodes(helper, '/rn_fn_exe_out') == {'rn_fn_exe'}
        wait_for(lambda: read_status(status).get('state') == 'running', timeout=10)

        # Save a change: the running node picks it up without a restart.
        pid = read_status(status)['pid']
        write(logic, LOGIC.replace('text.upper() + suffix()', "'v2:' + text"))
        wait_for(lambda: out and out[-1].data.startswith('v2:'), timeout=15)
        wait_for(lambda: read_status(status).get('stats', {}).get('reloads') == 1, timeout=10)
        assert read_status(status)['pid'] == pid == proc.pid or read_status(status)['pid'] == pid

        # A syntax error keeps the previous version running, and says where.
        write(logic, 'def shout(text):\n    return (\n')
        wait_for(lambda: read_status(status).get('state') == 'reload_error', timeout=15)
        problem = read_status(status)['problem']
        assert problem['kind'] == 'import' and problem['location'].startswith('fn_pkg/logic.py:')
        count = len(out)
        wait_for(lambda: len(out) > count + 2, timeout=10)
        assert out[-1].data.startswith('v2:')

        # An exception in the function: reported with the line; the node keeps running.
        write(logic, "def shout(text):\n    if text.endswith('5'):\n        raise ValueError(text)\n"
                     "    return 'v3:' + text\n")
        wait_for(lambda: out and out[-1].data.startswith('v3:'), timeout=15)
        wait_for(lambda: (read_status(status).get('last_error') or {}).get('kind') == 'call',
                 timeout=15)
        err = read_status(status)['last_error']
        assert err['location'] == 'fn_pkg/logic.py:3 (shout)' and 'ValueError' in err['message']
        assert proc.poll() is None
    finally:
        code = stop_group(proc)
        log = proc.stdout.read()
    assert code == 0, log
    assert '関数を読み直しました' in log and '関数でエラーが起きました' in log


def test_module_that_does_not_import_yet_waits_for_a_fix(tmp_path, helper):
    ws = tmp_path / 'ws'
    pkg = fake_source(ws / 'src', 'my_ros_pkg')
    write(pkg / 'fn_pkg' / '__init__.py', '')
    logic = pkg / 'fn_pkg' / 'logic.py'
    write(logic, 'def shout(text:\n')
    spec = fspec('rn_fn_late')
    status = tmp_path / 'status.json'
    config = tmp_path / 'fn.yaml'
    config.write_text(function_config_text(spec, str(ws), str(status)))
    out = helper.collector(String, '/rn_fn_late_out')
    text_publisher(helper, '/rn_fn_late_in', 10)
    proc = subprocess.Popen(['ros2', 'run', 'roshanavi', 'function', '--config', str(config),
                             '--ros-args', '-r', '__node:=rn_fn_late'], start_new_session=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        wait_for(lambda: read_status(status).get('state') == 'import_error', timeout=30)
        assert read_status(status)['last_error']['location'] == 'fn_pkg/logic.py:1'
        write(logic, "def shout(text):\n    return 'fixed'\n")
        wait_for(lambda: out and out[-1].data == 'fixed', timeout=20)
        wait_for(lambda: read_status(status).get('state') == 'running', timeout=10)
    finally:
        assert stop_group(proc) == 0, proc.stdout.read()


def test_function_api_role_status_project_and_code_export(client, helper):
    """「＋ 関数ノードを作る」 with the example module: POST /api/functions?start=true."""
    modules = client.get('/api/functions/modules').json()['modules']
    assert 'roshanavi_examples.logic' in [m['module'] for m in modules]
    assert not any(m['module'].startswith('roshanavi.') for m in modules)
    info = client.get('/api/functions/module', params={'name': 'roshanavi_examples.logic'}).json()
    shout = next(f for f in info['functions'] if f['name'] == 'shout')
    assert shout['signature'] == 'shout(text: str) -> str' and shout['returns_kind'] == 'string'
    assert client.get('/api/functions/module', params={'name': 'os.path'}).status_code == 404
    assert client.get('/api/functions/module', params={'name': '../x'}).status_code == 422

    out = helper.collector(String, '/rn_fn_api_out')
    text_publisher(helper, '/rn_fn_api_in', 10, lambda i: f'api{i}')
    body = fspec('rn_fn_api', module='roshanavi_examples.logic').dict()
    resp = client.post('/api/functions?start=true', json=body)
    assert resp.status_code == 201, resp.text
    assert resp.json()['kind'] == 'function' and resp.json()['role'] == 'function'
    assert client.get('/api/project').json()['project']['functions'][0]['function'] == 'shout'

    def on_graph():
        nodes = client.get('/api/graph').json()['nodes']
        return any(n['id'] == '/rn_fn_api' and n['role'] == 'function' for n in nodes)
    wait_for(on_graph, timeout=30)
    wait_for(lambda: out and out[-1].data.startswith('API'), timeout=20)
    wait_for(lambda: (client.get('/api/targets/rn-fn-api').json().get('function_status') or {})
             .get('stats', {}).get('published', 0) > 0, timeout=10)
    status = client.get('/api/targets/rn-fn-api').json()['function_status']
    assert status['state'] == 'running' and status['signature'] == 'shout(text: str) -> str'
    rows = client.get('/api/node-list').json()['rows']
    row = next(r for r in rows if r['target_id'] == 'rn-fn-api')
    assert row['role'] == 'function' and row['origin']['executable'] == 'function'

    bad = client.post('/api/functions', json={**body, 'id': 'rn-fn-bad', 'name': 'rn_fn_bad',
                                               'module': 'roshanavi_examples.nope'})
    assert bad.status_code == 404 and 'not found' in bad.text
    escape = client.post('/api/functions/rn-fn-api/export-code', json={'directory': '../../etc'})
    assert escape.status_code == 400 and escape.json()['error']['code'] == 'forbidden_path'

    # 「ROS ノードのコードとして書き出す」: the generated node works without roshanavi.
    directory = f'rn_fn_export_{uuid.uuid4().hex[:8]}'
    try:
        resp = client.post('/api/functions/rn-fn-api/export-code', json={'directory': directory})
        assert resp.status_code == 200, resp.text
        path = resp.json()['file']
        assert path == os.path.join(os.path.realpath(WS_ROOT), directory, 'rn_fn_api_node.py')
        assert client.delete('/api/targets/rn-fn-api').status_code == 200
        out.clear()
        proc = subprocess.Popen(['python3', path], start_new_session=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            wait_for(lambda: out and out[-1].data.startswith('API') and out[-1].data.endswith('!'),
                     timeout=30)
            assert publisher_nodes(helper, '/rn_fn_api_out') == {'rn_fn_api'}
        finally:
            stop_group(proc)
    finally:
        shutil.rmtree(os.path.join(WS_ROOT, directory), ignore_errors=True)
        client.delete('/api/targets/rn-fn-api')
    assert client.get('/api/project').json()['project'].get('functions', []) == []


def test_export_launch_runs_functions(tmp_path, data_dir, helper):
    out = helper.collector(String, '/rn_fn_lx_out')
    text_publisher(helper, '/rn_fn_lx_in', 10, lambda i: f'l{i}')
    launcher = Launcher(WS_ROOT, str(data_dir), project_path=str(tmp_path / 'p.yaml'),
                        autostart=False)
    directory = f'rn_fn_launch_{uuid.uuid4().hex[:8]}'
    try:
        launcher.manager.add(fspec('rn_fn_lx', module='roshanavi_examples.logic'))
        result = launcher.export_dummies(directory)
    finally:
        launcher.close()
    try:
        text = open(result['launch_file']).read()
        assert "executable='function'" in text
        proc = subprocess.Popen(['ros2', 'launch', result['launch_file']], start_new_session=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            wait_for(lambda: out and out[-1].data.startswith('L'), timeout=40)
        finally:
            stop_group(proc)
    finally:
        shutil.rmtree(os.path.join(WS_ROOT, directory), ignore_errors=True)


def test_periodic_example_publishes_a_wave(tmp_path, helper):
    from std_msgs.msg import Float64
    spec = fspec('rn_fn_wave', module='roshanavi_examples.logic', function='wave',
                 call='periodic', inputs=[], rate_hz=20, output={'topic': '/rn_fn_wave_out',
                                                                  'kind': 'float'})
    config = tmp_path / 'fn.yaml'
    config.write_text(function_config_text(spec, WS_ROOT))
    out = helper.collector(Float64, '/rn_fn_wave_out')
    proc = subprocess.Popen(['ros2', 'run', 'roshanavi', 'function', '--config', str(config),
                             '--ros-args', '-r', '__node:=rn_fn_wave'], start_new_session=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        wait_for(lambda: len(out) >= 10, timeout=30)
        values = [m.data for m in out]
        assert all(-1.0 <= v <= 1.0 for v in values) and len(set(values)) > 5
        started = time.monotonic()
        count = len(out)
        time.sleep(1.0)
        assert 8 <= (len(out) - count) / (time.monotonic() - started) <= 30  # ~20 Hz, loose
    finally:
        assert stop_group(proc) == 0, proc.stdout.read()
