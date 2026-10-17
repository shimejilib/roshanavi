"""Transform nodes over real ROS: map, relay of images, throttle / delay / drop, join, process."""

import random
import subprocess
import time

import pytest
from sensor_msgs.msg import Image
from std_msgs.msg import String

from conftest import wait_for
from roshanavi.launcher.dummy_config import transform_config_text
from roshanavi.launcher.schema import TransformSpec
from roshanavi.launcher.service import Launcher
from roshanavi.ros_runtime import RosRuntime
from roshanavi.transform.runner import TransformConfigError, TransformRunner
from test_dummy import publisher_nodes, stop_group

STRING = 'std_msgs/msg/String'


def tspec(name, **kw):
    base = {'id': name.replace('_', '-'), 'name': name,
            'inputs': [{'topic': f'/{name}_in', 'type': STRING}],
            'output': {'topic': f'/{name}_out', 'type': STRING},
            'mapping': {'data': '${upper(msg.data)}'}}
    return TransformSpec.model_validate({**base, **kw})


@pytest.fixture
def make_runner():
    created = []

    def make(spec, **kw):
        runtime = RosRuntime(spec.name, require_self_name=False)
        runtime.start()
        runner = TransformRunner(spec, runtime, **kw)
        created.append((runner, runtime))
        return runner
    yield make
    for runner, runtime in created:
        runner.close()
        runtime.stop()


def text_publisher(helper, topic, rate_hz, make=lambda i: f'm{i}'):
    return helper.periodic_publisher(String, topic, rate_hz, lambda i: String(data=make(i)))


def test_map_upper_and_filter(helper, make_runner):
    spec = tspec('rn_tf_map', condition="msg.data != 'skip'")
    runner = make_runner(spec)
    out = helper.collector(String, '/rn_tf_map_out')
    text_publisher(helper, '/rn_tf_map_in', 20, lambda i: 'skip' if i % 2 else f'hello{i}')
    wait_for(lambda: len(out) >= 5, timeout=20)
    assert all(m.data.startswith('HELLO') for m in out)
    stats = runner.snapshot()
    assert stats['filtered'] >= 3 and stats['errors'] == 0


def test_relay_image_keeps_bytes(helper, make_runner):
    spec = tspec('rn_tf_relay', mode='relay', mapping=None,
                 inputs=[{'topic': '/rn_tf_relay_in', 'type': 'sensor_msgs/msg/Image'}],
                 output={'topic': '/rn_tf_relay_out'})
    make_runner(spec)
    out = helper.collector(Image, '/rn_tf_relay_out')

    def image(i):
        return Image(width=64, height=48, encoding='rgb8', step=192,
                     data=bytes((i + k) % 256 for k in range(192 * 48)))
    helper.periodic_publisher(Image, '/rn_tf_relay_in', 10, image)
    wait_for(lambda: len(out) >= 3, timeout=20)
    msg = out[-1]
    assert (msg.width, msg.height, msg.encoding, len(msg.data)) == (64, 48, 'rgb8', 192 * 48)
    first = msg.data[0]
    assert bytes(msg.data) == bytes((first + k) % 256 for k in range(192 * 48))


def test_throttle_caps_the_rate(helper, make_runner):
    runner = make_runner(tspec('rn_tf_thr', throttle_hz=5))
    arrivals = []
    helper.node.create_subscription(String, '/rn_tf_thr_out',
                                    lambda m: arrivals.append(time.monotonic()), 10)
    text_publisher(helper, '/rn_tf_thr_in', 50)
    wait_for(lambda: len(arrivals) >= 8, timeout=30)
    gaps = [b - a for a, b in zip(arrivals[1:], arrivals[2:])]
    assert min(gaps) >= 0.15  # 5 Hz = 0.2 s; delivery jitter only shortens a gap slightly
    stats = runner.snapshot()
    assert stats['throttled'] > stats['published']


def test_fixed_delay(helper, make_runner):
    make_runner(tspec('rn_tf_delay', mapping=None, delay={'min_ms': 400}))
    latencies = []
    helper.node.create_subscription(
        String, '/rn_tf_delay_out',
        lambda m: latencies.append(time.time() - float(m.data)), 10)
    text_publisher(helper, '/rn_tf_delay_in', 5, lambda i: repr(time.time()))
    wait_for(lambda: len(latencies) >= 4, timeout=30)
    assert min(latencies) >= 0.39
    assert sorted(latencies)[len(latencies) // 2] < 2.0  # loose: loaded hosts


def test_drop_ratio_counts(helper, make_runner):
    runner = make_runner(tspec('rn_tf_drop', drop_ratio=0.5), rng=random.Random(7))
    out = helper.collector(String, '/rn_tf_drop_out')
    text_publisher(helper, '/rn_tf_drop_in', 50)
    wait_for(lambda: runner.snapshot()['received'] >= 100, timeout=30)
    stats = runner.snapshot()
    assert 0.3 <= stats['dropped'] / stats['received'] <= 0.7
    wait_for(lambda: len(out) >= stats['published'] - 2, timeout=10)
    assert stats['published'] + stats['dropped'] <= stats['received']


def test_multi_input_join_on_trigger(helper, make_runner):
    spec = tspec('rn_tf_join', inputs=[{'topic': '/rn_tf_join_a', 'type': STRING, 'alias': 'a'},
                                       {'topic': '/rn_tf_join_b', 'type': STRING, 'alias': 'b'}],
                 trigger='b', mapping={'data': '${a.data + "+" + b.data}'})
    runner = make_runner(spec)
    out = helper.collector(String, '/rn_tf_join_out')
    text_publisher(helper, '/rn_tf_join_a', 20, lambda i: f'a{i}')
    text_publisher(helper, '/rn_tf_join_b', 2, lambda i: f'b{i}')
    wait_for(lambda: len(out) >= 3, timeout=30)
    assert all(m.data.startswith('a') and '+b' in m.data for m in out)
    stats = runner.snapshot()
    assert stats['received'] > stats['published'] * 3  # only b triggers


def test_compile_errors_refuse_to_start():
    runtime = RosRuntime('rn_tf_bad', require_self_name=False)
    runtime.start()
    try:
        with pytest.raises(TransformConfigError, match='data'):
            TransformRunner(tspec('rn_tf_bad', mapping={'data': '${msg.__class__}'}), runtime)
    finally:
        runtime.stop()


def test_transform_executable(tmp_path, helper):
    spec = tspec('rn_tf_exe')
    path = tmp_path / 'tf.yaml'
    path.write_text(transform_config_text(spec))
    out = helper.collector(String, '/rn_tf_exe_out')
    text_publisher(helper, '/rn_tf_exe_in', 10, lambda i: f'x{i}')
    proc = subprocess.Popen(['ros2', 'run', 'roshanavi', 'transform', '--config', str(path),
                             '--ros-args', '-r', '__node:=rn_tf_exe'], start_new_session=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        wait_for(lambda: len(out) >= 3, timeout=30)
        assert out[-1].data.startswith('X')
        wait_for(lambda: publisher_nodes(helper, '/rn_tf_exe_out') == {'rn_tf_exe'}, timeout=10)
    finally:
        assert stop_group(proc) == 0, proc.stdout.read()


def test_transform_executable_rejects_bad_expression(tmp_path):
    path = tmp_path / 'bad.yaml'
    path.write_text(transform_config_text(tspec('rn_tf_bad2', mapping={'data': '${open(1)}'})))
    result = subprocess.run(['ros2', 'run', 'roshanavi', 'transform', '--config', str(path)],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 2, result.stdout + result.stderr
    assert 'invalid expression' in result.stdout + result.stderr


def test_export_launch_runs_transforms(tmp_path, data_dir, helper):
    out = helper.collector(String, '/rn_tf_exp_out')
    text_publisher(helper, '/rn_tf_exp_in', 10, lambda i: f'e{i}')
    launcher = Launcher(str(tmp_path), str(data_dir), autostart=False)
    try:
        launcher.manager.add(tspec('rn_tf_exp'))
        result = launcher.export_dummies('launch/nodes')
    finally:
        launcher.close()
    text = open(result['launch_file']).read()
    assert "executable='transform'" in text
    proc = subprocess.Popen(['ros2', 'launch', result['launch_file']], start_new_session=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        wait_for(lambda: len(out) >= 3, timeout=40)
        assert out[-1].data.startswith('E')
    finally:
        stop_group(proc)


def test_transform_api_graph_role_and_autosave(client, helper):
    """``＋ 変換ノードを作る``: POST /api/transforms?start=true -> role transform on the map."""
    out = helper.collector(String, '/rn_tf_api_out')
    text_publisher(helper, '/rn_tf_api_in', 10, lambda i: f'api{i}')
    body = tspec('rn_tf_api').model_dump()
    body['autostart'] = True
    resp = client.post('/api/transforms?start=true', json=body)
    assert resp.status_code == 201, resp.text
    assert resp.json()['kind'] == 'transform' and resp.json()['role'] == 'transform'
    saved = client.get('/api/project').json()
    assert saved['dirty'] is False
    assert saved['project']['transforms'][0]['mapping'] == {'data': '${upper(msg.data)}'}

    def on_graph():
        nodes = client.get('/api/graph').json()['nodes']
        return any(n['id'] == '/rn_tf_api' and n['role'] == 'transform' for n in nodes)
    wait_for(on_graph, timeout=30)
    wait_for(lambda: len(out) >= 2, timeout=20)
    assert out[-1].data.startswith('API')
    changed = {**body, 'mapping': {'data': '${lower(msg.data)}'}}
    assert client.put('/api/transforms/rn-tf-api', json=changed).status_code == 200
    bad = client.put('/api/transforms/rn-tf-api', json={**body, 'output': {
        'topic': '/rn_tf_api_in', 'type': STRING}})
    assert bad.status_code == 400 and 'output topic' in bad.text
    assert client.delete('/api/targets/rn-tf-api').status_code == 200
    assert client.get('/api/project').json()['project'].get('transforms', []) == []
