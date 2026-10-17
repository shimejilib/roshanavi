"""Class nodes over real ROS: the executable (parameters, action topic, reload, close), the API,
the scenario ``call`` step and the exported plain / lifecycle nodes."""

import os
import shutil
import subprocess
import time
import uuid

import pytest
from std_msgs.msg import Empty, Float64, Int64, String

from conftest import WS_ROOT, wait_for
from roshanavi.launcher.dummy_config import class_config_text
from roshanavi.launcher.schema import ClassSpec
from roshanavi.ros_runtime import RosRuntime
from roshanavi.scenario import parse_data
from roshanavi.scenario.api import run_scenario
from roshanavi.scenario.result import ERROR, FAILED, PASSED
from test_class_unit import KEEPING, STATEFUL
from test_dummy import publisher_nodes, stop_group
from test_function_ros import read_status
from test_function_unit import write
from ws_fixtures import fake_source


def cspec(name, **kw):
    base = {'id': name.replace('_', '-'), 'name': name, 'module': 'roshanavi_examples.stateful',
            'class_name': 'MovingAverage', 'params': {'window': 3},
            'methods': [{'method': 'process', 'inputs': [{'topic': f'/{name}_in', 'kind': 'float'}],
                         'outputs': [{'topic': f'/{name}_out', 'kind': 'float'}]}],
            'actions': ['reset']}
    return ClassSpec.model_validate({**base, **kw})


def start(tmp_path, spec, workspace=WS_ROOT):
    status = tmp_path / f'{spec.name}.status.json'
    config = tmp_path / f'{spec.name}.yaml'
    config.write_text(class_config_text(spec, str(workspace), str(status)))
    proc = subprocess.Popen(['ros2', 'run', 'roshanavi', 'function', '--config', str(config),
                             '--ros-args', '-r', f'__node:={spec.name}'], start_new_session=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return proc, status


class Sender:
    """Publishes single messages once the node's subscription is discovered."""

    def __init__(self, helper, msg_type, topic):
        self.pub = helper.node.create_publisher(msg_type, topic, 10)
        self.msg_type = msg_type

    def ready(self, timeout=30):
        wait_for(lambda: self.pub.get_subscription_count() > 0, timeout=timeout)
        time.sleep(1.0)   # the subscriber's side of the match settles a moment later

    def send(self, value=None):
        self.pub.publish(self.msg_type(data=value) if value is not None else self.msg_type())


def fail_with_log(proc, status):
    """Debug aid: the node's output and status when a wait fails."""
    pytest.fail(f'{read_status(status)}\n{stop_group(proc) and ""}{proc.stdout.read()}')


# The ros2 CLI starts a background daemon (a graph node `_ros2cli_daemon_*`) that would outlive
# these tests and show up in the node lists of the tests that follow: it is stopped at the end.
@pytest.fixture(autouse=True, scope='module')
def no_cli_daemon_left_behind():
    yield
    subprocess.run(['ros2', 'daemon', 'stop'], capture_output=True, timeout=30)


def listeners(helper, topic):
    """Nodes subscribed to ``topic`` (the roshanavi server's own probes are ignored)."""
    return {i.node_name for i in helper.node.get_subscriptions_info_by_topic(topic)
            if not i.node_name.startswith('roshanavi')}


def param(args, timeout=40):
    """``ros2 param ...``; retried while the CLI's daemon has not discovered the node yet."""
    deadline = time.monotonic() + timeout
    while True:
        done = subprocess.run(['ros2', 'param', *args], capture_output=True,
                              text=True, timeout=30)
        text = done.stdout + done.stderr
        if text.strip() and 'not found' not in text.lower() and 'no node' not in text.lower():
            return done
        if time.monotonic() > deadline:
            return done
        time.sleep(0.5)


def test_executable_parameters_actions_and_dict_free_basics(tmp_path, helper):
    spec = cspec('rn_ma_exe')
    out = helper.collector(Float64, '/rn_ma_exe_out')
    numbers = Sender(helper, Float64, '/rn_ma_exe_in')
    reset = Sender(helper, Empty, '/rn_ma_exe/reset')
    proc, status = start(tmp_path, spec)
    try:
        numbers.ready()
        reset.ready()
        wait_for(lambda: read_status(status).get('state') == 'running', timeout=10)
        wait_for(lambda: publisher_nodes(helper, '/rn_ma_exe_out') == {'rn_ma_exe'}, timeout=15)
        for x in (1, 2, 3):
            numbers.send(float(x))
        wait_for(lambda: len(out) == 3, timeout=10)
        assert [m.data for m in out] == [1.0, 1.5, 2.0]

        # __init__ arguments are parameters (declared with the spec's start value).
        listed = param(['list', '/rn_ma_exe']).stdout
        assert 'window' in listed
        assert param(['get', '/rn_ma_exe', 'window']).stdout.strip() == 'Integer value is: 3'
        # MovingAverage has on_param_change: the numbers inside the new window are kept.
        resp = param(['set', '/rn_ma_exe', 'window', '2'])
        assert 'Set parameter successful' in resp.stdout, resp.stdout + resp.stderr
        numbers.send(10.0)
        wait_for(lambda: len(out) == 4, timeout=10)
        assert out[-1].data == 6.5                     # (3 + 10) / 2
        # A refused value is reported by ros2 param and nothing changes.
        bad = param(['set', '/rn_ma_exe', 'window', '0'])
        assert 'failed' in (bad.stdout + bad.stderr).lower() and 'window must be 1' in (
            bad.stdout + bad.stderr)
        assert param(['get', '/rn_ma_exe', 'window']).stdout.strip() == 'Integer value is: 2'
        wrong = param(['set', '/rn_ma_exe', 'window', 'x'])
        assert 'failed' in (wrong.stdout + wrong.stderr).lower()

        # The action topic /<node>/<method> calls the method and records it in the status.
        reset.send()
        wait_for(lambda: read_status(status).get('actions', {}).get('reset', {}).get('count') == 1,
                 timeout=10)
        record = read_status(status)['actions']['reset']
        assert record['ok'] is True and record['last_at'] and record['topic'] == '~/reset'
        numbers.send(100.0)
        wait_for(lambda: len(out) == 5, timeout=10)
        assert out[-1].data == 100.0                    # forgot 3 and 10
        wait_for(lambda: read_status(status).get('stats', {}).get('calls') == 5, timeout=10)
        snap = read_status(status)
        assert snap['class'].endswith('MovingAverage')
        assert [p['name'] for p in snap['params']] == ['window']
    finally:
        code = stop_group(proc)
        log = proc.stdout.read()
    assert code == 0, log


def test_parameter_change_without_a_hook_recreates_the_instance(tmp_path, helper):
    spec = cspec('rn_ctr_param', class_name='Counter', params={'start': 5},
                 methods=[{'method': 'process',
                           'inputs': [{'topic': '/rn_ctr_param_in', 'kind': 'string'}],
                           'outputs': [{'topic': '/rn_ctr_param_out', 'kind': 'int'}]}])
    out = helper.collector(Int64, '/rn_ctr_param_out')
    texts = Sender(helper, String, '/rn_ctr_param_in')
    proc, status = start(tmp_path, spec)
    try:
        texts.ready()
        wait_for(lambda: read_status(status).get('state') == 'running', timeout=10)
        for _ in range(3):
            texts.send('x')
        wait_for(lambda: len(out) == 3, timeout=10)
        assert [m.data for m in out] == [6, 7, 8]
        assert 'Set parameter successful' in param(['set', '/rn_ctr_param', 'start', '100']).stdout
        texts.send('x')
        wait_for(lambda: len(out) == 4, timeout=10)
        assert out[-1].data == 101                      # a new instance, counting from 100
        notice = read_status(status)['notice']
        assert notice['kind'] == 'reset' and notice['reason'] == 'param'
    finally:
        code = stop_group(proc)
        log = proc.stdout.read()
    assert code == 0, log
    assert 'Counter stopped at 101' in log             # close() ran when the node stopped


def test_dict_return_publishes_each_key_to_its_own_topic(tmp_path, helper):
    spec = cspec('rn_stats_exe', class_name='RunningStats', params={},
                 methods=[{'method': 'process',
                           'inputs': [{'topic': '/rn_stats_in', 'kind': 'float'}],
                           'outputs': [{'topic': '/rn_stats_mean', 'kind': 'float', 'key': 'mean'},
                                       {'topic': '/rn_stats_count', 'kind': 'int', 'key': 'count'},
                                       {'topic': '/rn_stats_max', 'kind': 'float',
                                        'key': 'max'}]}])
    mean = helper.collector(Float64, '/rn_stats_mean')
    count = helper.collector(Int64, '/rn_stats_count')
    biggest = helper.collector(Float64, '/rn_stats_max')
    numbers = Sender(helper, Float64, '/rn_stats_in')
    proc, status = start(tmp_path, spec)
    try:
        numbers.ready()
        for x in (2.0, 8.0, 5.0):
            numbers.send(x)
        try:
            wait_for(lambda: len(mean) == len(count) == len(biggest) == 3, timeout=10)
        except BaseException:
            fail_with_log(proc, status)
        assert [m.data for m in mean] == [2.0, 5.0, 5.0]
        assert [m.data for m in count] == [1, 2, 3]
        assert [m.data for m in biggest] == [2.0, 8.0, 8.0]
    finally:
        assert stop_group(proc) == 0, proc.stdout.read()


def test_hot_reload_resets_or_keeps_state_and_errors_keep_the_old_instance(tmp_path, helper):
    ws = tmp_path / 'ws'
    pkg = fake_source(ws / 'src', 'my_ros_pkg')
    write(pkg / 'cl_pkg' / '__init__.py', '')
    module = pkg / 'cl_pkg' / 'keeping.py'
    write(module, KEEPING.replace("class Acc", "class Keep"))
    write(pkg / 'cl_pkg' / 'plain.py', STATEFUL)
    spec = cspec('rn_keep_exe', module='cl_pkg.keeping', class_name='Keep', params={},
                 methods=[{'method': 'add', 'inputs': [{'topic': '/rn_keep_in', 'kind': 'float'}],
                           'outputs': [{'topic': '/rn_keep_out', 'kind': 'float'}]}])
    out = helper.collector(Float64, '/rn_keep_out')
    numbers = Sender(helper, Float64, '/rn_keep_in')
    proc, status = start(tmp_path, spec, ws)
    try:
        numbers.ready()
        wait_for(lambda: read_status(status).get('state') == 'running', timeout=15)
        numbers.send(5.0)
        wait_for(lambda: len(out) == 1, timeout=10)
        # get_state()/set_state() exist: the total is carried over to the new code.
        write(module, KEEPING.replace("class Acc", "class Keep").replace(
            'self.total += x * self.scale', 'self.total += x * self.scale * 10'))
        wait_for(lambda: read_status(status).get('stats', {}).get('reloads') == 1, timeout=15)
        assert read_status(status)['notice']['kind'] == 'kept'
        numbers.send(1.0)
        wait_for(lambda: len(out) == 2, timeout=10)
        assert out[-1].data == 15.0
        # A syntax error: the old instance keeps running, the status says where.
        write(module, 'class Keep:\n    def add(self, x:\n')
        wait_for(lambda: read_status(status).get('state') == 'reload_error', timeout=15)
        problem = read_status(status)['problem']
        assert problem['kind'] == 'import' and problem['location'].startswith('cl_pkg/keeping.py:')
        numbers.send(1.0)
        wait_for(lambda: len(out) == 3, timeout=10)
        assert out[-1].data == 25.0
        # __init__ that fails on the new code: same, with the reason.
        write(module, KEEPING.replace("class Acc", "class Keep").replace(
            'self.total = 0.0\n        self.scale = scale', 'raise ValueError("bad init")'))
        wait_for(lambda: (read_status(status).get('problem') or {}).get('kind') == 'init',
                 timeout=15)
        assert 'bad init' in read_status(status)['problem']['message']
        # A fixed file clears the error.
        write(module, KEEPING.replace("class Acc", "class Keep"))
        wait_for(lambda: read_status(status).get('state') == 'running', timeout=15)
        assert read_status(status)['problem'] is None and proc.poll() is None
    finally:
        assert stop_group(proc) == 0, proc.stdout.read()


def test_hot_reload_without_get_state_resets_and_tells_the_user(tmp_path, helper):
    ws = tmp_path / 'ws'
    pkg = fake_source(ws / 'src', 'my_ros_pkg')
    write(pkg / 'cl_pkg' / '__init__.py', '')
    module = pkg / 'cl_pkg' / 'plain.py'
    write(module, STATEFUL)
    spec = cspec('rn_plain_exe', module='cl_pkg.plain', class_name='Acc', params={},
                 methods=[{'method': 'add', 'inputs': [{'topic': '/rn_plain_in', 'kind': 'float'}],
                           'outputs': [{'topic': '/rn_plain_out', 'kind': 'float'}]}])
    out = helper.collector(Float64, '/rn_plain_out')
    numbers = Sender(helper, Float64, '/rn_plain_in')
    proc, status = start(tmp_path, spec, ws)
    try:
        numbers.ready()
        wait_for(lambda: read_status(status).get('state') == 'running', timeout=15)
        numbers.send(5.0)
        numbers.send(5.0)
        wait_for(lambda: len(out) == 2, timeout=10)
        assert out[-1].data == 10.0
        write(module, STATEFUL + '\n# saved\n')
        wait_for(lambda: read_status(status).get('stats', {}).get('reloads') == 1, timeout=15)
        notice = read_status(status)['notice']
        assert notice['kind'] == 'reset' and notice['reason'] == 'reload'
        numbers.send(1.0)
        wait_for(lambda: len(out) == 3, timeout=10)
        assert out[-1].data == 1.0                      # the state was reset
    finally:
        code = stop_group(proc)
        log = proc.stdout.read()
    assert code == 0 and '状態をリセットしました' in log


def test_init_failure_is_shown_and_does_not_stop_the_node(tmp_path, helper):
    spec = cspec('rn_ma_bad', params={'window': 0})
    proc, status = start(tmp_path, spec)
    try:
        wait_for(lambda: read_status(status).get('state') == 'init_error', timeout=20)
        problem = read_status(status)['problem']
        assert problem['kind'] == 'init' and 'window must be 1 or more' in problem['message']
        assert 'roshanavi_examples/stateful.py:' in problem['location']
        assert proc.poll() is None
        assert 'Set parameter successful' in param(['set', '/rn_ma_bad', 'window', '2']).stdout
        wait_for(lambda: read_status(status).get('state') == 'running', timeout=10)
    finally:
        assert stop_group(proc) == 0, proc.stdout.read()


# ---- API, graph, code export --------------------------------------------------------------------
def wait_node(client, node_id, role='function'):
    def on_graph():
        nodes = client.get('/api/graph').json()['nodes']
        return any(n['id'] == node_id and n['role'] == role for n in nodes)
    wait_for(on_graph, timeout=40)


def test_class_api_call_button_status_project_and_exports(client, helper, tmp_path):
    info = client.get('/api/functions/module', params={'name': 'roshanavi_examples.stateful'}).json()
    names = {c['name']: c for c in info['classes']}
    assert {'MovingAverage', 'Counter', 'RunningStats'} <= set(names)
    ma = names['MovingAverage']
    assert [(p['name'], p['kind'], p['default']) for p in ma['init_params']] == [
        ('window', 'int', 5)]
    assert {m['name'] for m in ma['methods'] if m['action_candidate']} == {'reset'}
    assert ma['hooks']['on_param_change'] and ma['hooks']['get_state']

    out = helper.collector(Float64, '/rn_cls_api_out')
    numbers = Sender(helper, Float64, '/rn_cls_api_in')
    body = cspec('rn_cls_api').model_dump()
    resp = client.post('/api/classes?start=true', json=body)
    assert resp.status_code == 201, resp.text
    assert resp.json()['kind'] == 'class' and resp.json()['role'] == 'function'
    assert client.get('/api/project').json()['project']['classes'][0]['class_name'] == 'MovingAverage'
    wait_node(client, '/rn_cls_api')
    numbers.ready()
    wait_for(lambda: (client.get('/api/targets/rn-cls-api').json().get('function_status') or {})
             .get('state') == 'running', timeout=15)
    numbers.send(4.0)
    numbers.send(8.0)
    wait_for(lambda: len(out) == 2 and out[-1].data == 6.0, timeout=10)
    rows = client.get('/api/node-list').json()['rows']
    row = next(r for r in rows if r['target_id'] == 'rn-cls-api')
    assert row['role'] == 'function' and row['origin']['kind'] == 'class'
    assert row['origin']['topic'] == '/rn_cls_api_out'

    # The button / menu path: POST /call publishes Empty on /<node>/<method> and waits.
    called = client.post('/api/classes/rn-cls-api/call', json={'method': 'reset'})
    assert called.status_code == 200, called.text
    assert called.json()['topic'] == '/rn_cls_api/reset'
    assert called.json()['record']['count'] == 1 and called.json()['record']['ok'] is True
    numbers.send(50.0)
    wait_for(lambda: len(out) == 3, timeout=10)
    assert out[-1].data == 50.0
    status = client.get('/api/targets/rn-cls-api').json()['function_status']
    assert status['actions']['reset']['count'] == 1 and status['notice'] is None
    assert client.post('/api/classes/rn-cls-api/call', json={'method': 'process'}).status_code == 404
    assert client.post('/api/classes/rn-cls-api/call', json={'method': 'bad name'}).status_code == 422
    assert client.post('/api/classes/nope/call', json={'method': 'reset'}).status_code == 404

    bad = client.post('/api/classes', json={**body, 'id': 'rn-cls-bad', 'name': 'rn_cls_bad',
                                             'module': 'roshanavi_examples.nope'})
    assert bad.status_code == 404
    escape = client.post('/api/classes/rn-cls-api/export-code', json={'directory': '../../etc'})
    assert escape.status_code == 400 and escape.json()['error']['code'] == 'forbidden_path'

    directory = f'rn_cls_export_{uuid.uuid4().hex[:8]}'
    try:
        # plain rclpy node
        resp = client.post('/api/classes/rn-cls-api/export-code', json={'directory': directory})
        assert resp.status_code == 200, resp.text
        path = resp.json()['file']
        assert path == os.path.join(os.path.realpath(WS_ROOT), directory, 'rn_cls_api_node.py')
        assert client.post('/api/targets/rn-cls-api/stop').status_code == 200
        not_running = client.post('/api/classes/rn-cls-api/call', json={'method': 'reset'})
        assert not_running.status_code == 409 and not_running.json()['error']['code'] == 'not_running'
        assert client.delete('/api/targets/rn-cls-api').status_code == 200
        out.clear()
        proc = subprocess.Popen(['python3', path], start_new_session=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            numbers.pub.get_subscription_count()
            wait_for(lambda: numbers.pub.get_subscription_count() > 0, timeout=30)
            wait_for(lambda: publisher_nodes(helper, '/rn_cls_api_out') == {'rn_cls_api'},
                     timeout=15)
            numbers.send(4.0)
            numbers.send(8.0)
            wait_for(lambda: len(out) == 2 and out[-1].data == 6.0, timeout=15)
            # the action topic works on the generated node too
            reset = Sender(helper, Empty, '/rn_cls_api/reset')
            reset.ready()
            reset.send()
            time.sleep(0.5)
            numbers.send(9.0)
            wait_for(lambda: len(out) == 3 and out[-1].data == 9.0, timeout=15)
            # a parameter change goes through the class's on_param_change
            assert 'Set parameter successful' in param(['set', '/rn_cls_api', 'window', '1']).stdout
            numbers.send(2.0)
            wait_for(lambda: len(out) == 4 and out[-1].data == 2.0, timeout=15)
        finally:
            code = stop_group(proc)
            log = proc.stdout.read()
        assert code == 0 and 'Traceback' not in log, log
    finally:
        shutil.rmtree(os.path.join(WS_ROOT, directory), ignore_errors=True)
        client.delete('/api/targets/rn-cls-api')
    assert client.get('/api/project').json()['project'].get('classes', []) == []


def test_lifecycle_export_runs_and_follows_the_lifecycle(client, helper, tmp_path):
    spec = cspec('rn_cls_lc')
    out = helper.collector(Float64, '/rn_cls_lc_out')
    numbers = Sender(helper, Float64, '/rn_cls_lc_in')
    assert client.post('/api/classes', json=spec.model_dump()).status_code == 201
    directory = f'rn_cls_lc_export_{uuid.uuid4().hex[:8]}'
    try:
        resp = client.post('/api/classes/rn-cls-lc/export-code',
                           json={'directory': directory, 'lifecycle': True})
        assert resp.status_code == 200, resp.text
        path = resp.json()['file']
        assert 'LifecycleNode' in open(path).read()
        proc = subprocess.Popen(['python3', path], start_new_session=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            def lifecycle(*args):
                deadline = time.monotonic() + 40
                while True:     # the CLI daemon may not have discovered the node yet
                    done = subprocess.run(['ros2', 'lifecycle', *args],
                                          capture_output=True, text=True, timeout=60)
                    if 'not found' not in done.stderr.lower() or time.monotonic() > deadline:
                        return done
                    time.sleep(0.5)
            wait_for(lambda: 'unconfigured' in lifecycle('get', '/rn_cls_lc').stdout, timeout=40)
            # unconfigured: no instance, no subscriptions yet
            assert listeners(helper, '/rn_cls_lc_in') == set()
            assert 'Transitioning successful' in lifecycle('set', '/rn_cls_lc', 'configure').stdout
            assert 'inactive' in lifecycle('get', '/rn_cls_lc').stdout
            assert listeners(helper, '/rn_cls_lc_in') == set()   # still not listening
            assert 'Transitioning successful' in lifecycle('set', '/rn_cls_lc', 'activate').stdout
            wait_for(lambda: listeners(helper, '/rn_cls_lc_in') == {'rn_cls_lc'}, timeout=15)
            time.sleep(1.0)
            numbers.send(4.0)
            numbers.send(8.0)
            wait_for(lambda: len(out) == 2 and out[-1].data == 6.0, timeout=15)
            assert 'Transitioning successful' in lifecycle('set', '/rn_cls_lc',
                                                           'deactivate').stdout
            wait_for(lambda: listeners(helper, '/rn_cls_lc_in') == set(), timeout=15)
            # cleanup drops the instance; configure + activate again starts from scratch
            assert 'Transitioning successful' in lifecycle('set', '/rn_cls_lc', 'cleanup').stdout
            assert 'Transitioning successful' in lifecycle('set', '/rn_cls_lc', 'configure').stdout
            assert 'Transitioning successful' in lifecycle('set', '/rn_cls_lc', 'activate').stdout
            wait_for(lambda: listeners(helper, '/rn_cls_lc_in') == {'rn_cls_lc'}, timeout=15)
            time.sleep(1.0)
            numbers.send(7.0)
            wait_for(lambda: len(out) == 3 and out[-1].data == 7.0, timeout=15)
        finally:
            code = stop_group(proc)
            log = proc.stdout.read()
        assert code == 0 and 'Traceback' not in log, log
    finally:
        shutil.rmtree(os.path.join(WS_ROOT, directory), ignore_errors=True)
        client.delete('/api/targets/rn-cls-lc')


def test_export_launch_runs_class_nodes(tmp_path, data_dir, helper):
    from roshanavi.launcher.service import Launcher
    out = helper.collector(Float64, '/rn_cls_lx_out')
    numbers = Sender(helper, Float64, '/rn_cls_lx_in')
    launcher = Launcher(WS_ROOT, str(data_dir), project_path=str(tmp_path / 'p.yaml'),
                        autostart=False)
    directory = f'rn_cls_launch_{uuid.uuid4().hex[:8]}'
    try:
        launcher.manager.add(cspec('rn_cls_lx'))
        result = launcher.export_dummies(directory)
    finally:
        launcher.close()
    try:
        assert "executable='function'" in open(result['launch_file']).read()
        proc = subprocess.Popen(['ros2', 'launch', result['launch_file']], start_new_session=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            numbers.ready(timeout=60)
            time.sleep(0.5)
            numbers.send(3.0)
            wait_for(lambda: out and out[-1].data == 3.0, timeout=30)
        finally:
            stop_group(proc)
    finally:
        shutil.rmtree(os.path.join(WS_ROOT, directory), ignore_errors=True)


# ---- scenario: the call step ----------------------------------------------------------------------
@pytest.fixture(scope='module')
def runtime():
    rt = RosRuntime('roshanavi_class_scenario_test')
    rt.start()
    yield rt
    rt.stop()


def scenario(steps, actions=('reset',), name='scenario_cls'):
    return parse_data({
        'version': 1, 'name': 'class_call',
        'setup': [{'class': {'name': name, 'module': 'roshanavi_examples.stateful',
                             'class_name': 'MovingAverage', 'params': {'window': 3},
                             'methods': [{'method': 'process',
                                          'inputs': [{'topic': '/scn_cls_in', 'kind': 'float'}],
                                          'outputs': [{'topic': '/scn_cls_out',
                                                       'kind': 'float'}]}],
                             'actions': list(actions)}}],
        'steps': steps})


def run(data, runtime, data_dir):
    return run_scenario(data, runtime=runtime, data_dir=str(data_dir), workspace=WS_ROOT)


def test_call_step_resets_the_state(runtime, data_dir):
    result = run(scenario([
        {'send': {'topic': '/scn_cls_in', 'kind': 'float', 'value': 10}},
        {'send': {'topic': '/scn_cls_in', 'kind': 'float', 'value': 20}},
        {'expect': {'topic': '/scn_cls_out', 'within': 2.0,
                    'where': [{'field': 'data', 'op': 'eq', 'value': 15.0}]}},
        {'call': {'node': '/scenario_cls', 'method': 'reset'}},
        {'send': {'topic': '/scn_cls_in', 'kind': 'float', 'value': 100}},
        {'expect': {'topic': '/scn_cls_out', 'within': 2.0,
                    'where': [{'field': 'data', 'op': 'eq', 'value': 100.0}]}}]),
        runtime, data_dir)
    assert result.status == PASSED, '\n'.join(result.failures()) + result.message
    call = result.steps[3]
    assert call.kind == 'call' and '/scenario_cls の reset() を呼びました' in call.message


def test_call_step_failure_messages(runtime, data_dir):
    missing = run(scenario([{'call': {'node': '/scenario_cls', 'method': 'nothing'}}]),
                  runtime, data_dir)
    assert missing.steps[0].status == ERROR and '/scenario_cls/nothing を受け取るノードが見つかりません' in \
        missing.steps[0].message
    ghost = run(scenario([{'call': {'node': '/no_such_node', 'method': 'reset'}}]),
                runtime, data_dir)
    assert ghost.steps[0].status == ERROR and '受け取るノードが見つかりません' in ghost.steps[0].message
    with pytest.raises(Exception):
        parse_data({'version': 1, 'name': 'x', 'steps': [{'call': {'node': '/n'}}]})
    failing = run(scenario([{'call': {'node': '/scenario_cls', 'method': 'fail'}}],
                           actions=('reset', 'fail')), runtime, data_dir)
    assert failing.status == FAILED and failing.steps[0].status == ERROR
    assert 'reset の' not in failing.steps[0].message
    assert '/scenario_cls の fail() がエラーになりました' in failing.steps[0].message
