"""Resource monitoring with real nodes: launcher targets attributed exactly, busy_demo CPU
as seen by the monitor, API / WebSocket through the middleware, scenario steps.

The busy_demo comparison is TIMING- AND ENVIRONMENT-SENSITIVE (CPU of a real rclpy executor
over ~6 s). Margins are generous (~89 % vs ~8 % measured; asserted >= 3x and >= 30 %). If the
busy-loop does not reproduce (another RMW, an upstream fix of ros2/rmw_fastrtps#929) the
comparison is skipped with that reason, as in test_executor_busy_demo.py.
"""

import os
import statistics
import time

import pytest
import yaml
from starlette.websockets import WebSocketDisconnect

from conftest import WS_ROOT, wait_for
from roshanavi.ros_runtime import RosRuntime
from roshanavi.scenario import parse_data
from roshanavi.scenario.api import run_scenario
from roshanavi.scenario.result import FAILED, PASSED
from test_launcher_ros import add_and_start

EXAMPLES = os.environ.get('ROSHANAVI_EXAMPLES', '/examples')
BUSY_PARAMS = {'executor': 'multi', 'work_ms': 5.0, 'num_threads': 4}
BUSY_MIN_PCT = 30.0  # multi + default measured at ~89 %


def snapshot(client):
    return client.get('/api/resources').json()


def node_entry(client, node):
    return snapshot(client).get('nodes', {}).get(node)


def test_launcher_target_is_attributed_exactly_with_cpu_fds_and_threads(client):
    add_and_start(client, {'id': 'res_drv', 'kind': 'run', 'package': 'roshanavi_examples',
                           'executable': 'busy_demo_driver', 'name': 'res_driver',
                           'params': {'rate_hz': 200.0}, 'role': 'mine'})

    def ready():
        n = node_entry(client, '/res_driver')
        return n if n and n['confidence'] == 'exact' and (n['cpu_pct'] or 0) > 0 else None
    node = wait_for(ready, timeout=30, interval=0.5)
    assert node['source'] == 'launcher' and node['target_id'] == 'res_drv'
    assert node['scope'] == 'process' and node['shared'] == []
    assert node['threads'] >= 1 and node['fds'] > 3 and node['rss'] > 10 * 1024 ** 2
    snap = snapshot(client)
    proc = next(p for p in snap['processes'] if p['pid'] == node['pid'])
    assert proc['group'] == 'ros' and proc['role'] == 'mine' and proc['nodes'] == ['/res_driver']
    assert proc['udp_sockets'] >= 1  # DDS sockets are counted, not listed
    wrapper = [p for p in snap['processes'] if p['target_id'] == 'res_drv' and p['pid'] != proc['pid']]
    assert wrapper and wrapper[0]['name'] in ('ros2', 'python3')  # the ros2 run wrapper
    own = {p['label'] for p in snap['processes'] if p['group'] == 'self'}
    assert 'server' in own
    assert snap['own_user_only'] is (os.geteuid() != 0)
    assert snap['host']['cpu']['total_pct'] is not None and snap['host']['mem']['total'] > 0
    assert all(n['name'] != 'lo' for n in snap['host']['nics'])
    assert snap['host']['disk']['level'] in ('ok', 'warn', 'stop')
    assert snap['sampler']['processes'] >= 3
    hist = client.get('/api/resources/history', params={'node': '/res_driver'}).json()
    assert hist['node'] == '/res_driver' and len(hist['history']['cpu_pct']) >= 1
    assert hist['history']['pids'] == [node['pid']]
    assert hist['current']['pid'] == node['pid'] and isinstance(hist['connections'], list)
    with client.websocket_connect('ws://localhost/ws/live') as ws:
        live = wait_for(lambda: (lambda m: m if '/res_driver' in m['resources']['nodes'] else None)(
            ws.receive_json()), timeout=10)
    badge = live['resources']['nodes']['/res_driver']
    assert badge['confidence'] == 'exact' and badge['rss'] > 0


def median_cpu(client, node, seconds):
    """Median of the monitor's 1 Hz CPU values of ``node`` over the last ``seconds``."""
    wait_for(lambda: node_entry(client, node), timeout=30, interval=0.5)
    time.sleep(2.0)  # start-up (imports, discovery) settles
    values = []
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        snap = snapshot(client)
        if snap['sampled_at'] != last:
            last = snap['sampled_at']
            value = (snap['nodes'].get(node) or {}).get('cpu_pct')
            if value is not None:
                values.append(value)
        time.sleep(0.25)
    assert len(values) >= seconds / 2, values
    return statistics.median(values)


def test_busy_demo_default_is_clearly_busier_than_off_on_the_map(client):
    add_and_start(client, {'id': 'res_bd_drv', 'kind': 'run', 'package': 'roshanavi_examples',
                           'executable': 'busy_demo_driver', 'name': 'res_bd_driver',
                           'params': {'rate_hz': 100.0}, 'role': 'dependency'})
    measured = {}
    for qos in ('default', 'off'):
        tid = f'res_bd_{qos}'
        add_and_start(client, {'id': tid, 'kind': 'run', 'package': 'roshanavi_examples',
                               'executable': 'executor_busy_demo', 'name': f'res_busy_{qos}',
                               'params': {**BUSY_PARAMS, 'qos_events': qos,
                                          'stats_topic': f'/res_busy/{qos}/stats'},
                               'role': 'mine'})
        measured[qos] = median_cpu(client, f'/res_busy_{qos}', 6.0)
        assert client.post(f'/api/targets/{tid}/stop').status_code == 200
    print(f'busy_demo as seen by the monitor: multi+default {measured["default"]:.1f}% '
          f'multi+off {measured["off"]:.1f}%')
    assert measured['off'] < 50.0, measured  # the workaround is healthy in any case
    if measured['default'] < BUSY_MIN_PCT:
        pytest.skip(f'busy-loop did not reproduce here (multi+default {measured["default"]:.1f}%)')
    assert measured['default'] >= 3 * max(measured['off'], 1.0), measured


SAMPLER_MAX_PCT = 4.0  # target < 2 % of one core at ~50 processes; 2x margin for a busy machine


def test_sampler_stays_light_with_fifty_processes(lab):
    import subprocess
    sleepers = [subprocess.Popen(['sleep', '120']) for _ in range(50)]  # tracked: our children
    try:
        time.sleep(1.0)
        first = lab.resources.ticks
        wait_for(lambda: lab.resources.ticks >= first + 11, timeout=30, interval=0.2)
        cost = lab.resources.snapshot()['sampler']
    finally:
        for proc in sleepers:
            proc.kill()
        for proc in sleepers:
            proc.wait()
    print(f'sampler cost: {cost}')
    assert cost['processes'] >= 50
    assert cost['cpu_pct'] is not None and cost['cpu_pct'] < SAMPLER_MAX_PCT, cost


def test_resources_routes_are_behind_the_host_check(client):
    assert client.get('/api/resources').status_code == 200
    for path in ('/api/resources', '/api/resources/history'):
        assert client.get(path, headers={'Host': 'evil.example'}).status_code == 403
    for headers in ({'Origin': 'http://evil.example'}, {'Host': 'evil.example'}):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('ws://localhost/ws/resources', headers=headers) as ws:
                ws.receive_json()
    with client.websocket_connect('ws://localhost/ws/resources') as ws:
        snap = wait_for(lambda: (lambda m: m if m.get('available') else None)(ws.receive_json()),
                        timeout=10)
    assert snap['scope'] == 'this_host' and 'processes' in snap
    assert client.get('/api/resources/history', params={'scope': 'host'}).json()['scope'] == 'host'
    assert client.get('/api/resources/history', params={'scope': 'nope'}).status_code == 422
    assert client.get('/api/resources/history', params={'node': '/'}).status_code == 400


# ---- scenario steps against real nodes ----------------------------------------------------------

@pytest.fixture(scope='module')
def runtime():
    rt = RosRuntime('roshanavi_resources_test')
    rt.start()
    yield rt
    rt.stop()


def run(data, runtime, data_dir):
    return run_scenario(parse_data(data), runtime=runtime, data_dir=str(data_dir),
                        workspace=WS_ROOT)


TALKER = {'cmd': ['ros2', 'run', 'demo_nodes_cpp', 'talker', '--ros-args', '-r',
                  '__node:=res_talker', '-r', 'chatter:=/res/chatter'],
          'wait_for_node': '/res_talker'}


def test_resources_and_mem_growth_steps_pass_and_fail(runtime, data_dir):
    result = run({'name': 'res_ok', 'setup': [TALKER], 'steps': [
        {'resources': {'node': '/res_talker', 'cpu_max': 50, 'mem_max_mb': 500, 'for': 2.0}},
        {'mem_growth': {'node': 'res_talker', 'max_mb_per_min': 20, 'for': 10.0}}]},
        runtime, data_dir)
    assert result.status == PASSED, '\n'.join(result.failures())
    res = result.steps[0]
    assert res.details['confidence'] == 'exact' and res.details['samples'] >= 4
    assert 0 < res.details['mem_max_mb'] < 500 and '推定' not in res.message
    result = run({'name': 'res_fail', 'setup': [TALKER], 'steps': [
        {'resources': {'node': '/res_talker', 'mem_max_mb': 1, 'for': 1.0}}]}, runtime, data_dir)
    assert result.status == FAILED and 'メモリが上限を超えました' in result.steps[0].message
    result = run({'name': 'res_missing', 'steps': [
        {'resources': {'node': '/res_nobody', 'cpu_max': 5, 'for': 1.0}}]}, runtime, data_dir)
    assert result.status == FAILED and '見つかりませんでした' in result.steps[0].message


def test_server_run_marks_its_setup_processes_exact(client):
    from test_scenario_server import wait_run
    spec = {'name': 'res_server', 'setup': [TALKER], 'steps': [
        {'resources': {'node': '/res_talker', 'cpu_max': 50, 'mem_max_mb': 500, 'for': 3.0}}]}
    assert client.post('/api/scenarios', json={'spec': spec}).status_code == 201
    run = client.post('/api/scenarios/project:res_server.yaml/run').json()
    result = wait_run(client, run['run_id'])
    step = result['steps'][0]
    assert result['status'] == 'passed', step['message']
    assert step['details']['confidence'] == 'exact' and '推定' not in step['message']


def busy_example():
    with open(os.path.join(EXAMPLES, 'scenarios', 'busy_cpu.yaml'), encoding='utf-8') as fh:
        return yaml.safe_load(fh)


def test_busy_cpu_example_passes_and_multi_default_fails(runtime, data_dir):
    result = run(busy_example(), runtime, data_dir)
    assert result.status == PASSED, '\n'.join(result.failures())
    off_cpu = result.steps[1].details['cpu_avg_pct']
    broken = busy_example()
    broken['setup'][1]['run']['params']['qos_events'] = 'default'
    result = run(broken, runtime, data_dir)
    step = result.steps[1]
    print(f'busy_cpu example: multi+off {off_cpu:.1f}%, multi+default '
          f'{step.details.get("cpu_avg_pct")}%')
    if result.status == PASSED and (step.details.get('cpu_avg_pct') or 0) < BUSY_MIN_PCT:
        pytest.skip('busy-loop did not reproduce here: multi+default stayed under '
                    f'{BUSY_MIN_PCT}% ({step.details.get("cpu_avg_pct")}%)')
    assert result.status == FAILED and step.status == FAILED
    assert 'CPU が上限を超えました' in step.message
