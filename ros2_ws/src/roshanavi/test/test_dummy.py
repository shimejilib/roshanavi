"""Persistent dummy nodes: executable, inject job -> dummy, launch-file export."""

import os
import signal
import subprocess

import pytest
from std_msgs.msg import String

from conftest import wait_for
from roshanavi.launcher.dummy_config import config_text, export, load_config
from roshanavi.launcher.errors import LauncherError
from roshanavi.launcher.schema import DummySpec
from roshanavi.launcher.service import Launcher


def spec(**kw):
    return DummySpec(**{'id': 'cam', 'name': 'rn_dummy_cam', 'topic': '/rn_dummy_topic',
                        'type': 'std_msgs/msg/String', 'mode': 'periodic',
                        'payload': {'data': 'frame ${i}'}, 'rate_hz': 10, **kw})


def publisher_nodes(helper, topic):
    return {i.node_name for i in helper.node.get_publishers_info_by_topic(topic)}


def stop_group(proc):
    os.killpg(proc.pid, signal.SIGINT)
    try:
        return proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        return proc.wait()


def test_config_round_trip(tmp_path):
    path = tmp_path / 'cam.yaml'
    path.write_text(config_text(spec(), str(tmp_path)))
    loaded = load_config(str(path))
    assert loaded['spec'] == spec() and loaded['data_dir'] == os.path.realpath(tmp_path)


def test_dummy_executable_publishes_under_its_own_name(tmp_path, helper):
    received = helper.collector(String, '/rn_dummy_topic')
    path = tmp_path / 'cam.yaml'
    path.write_text(config_text(spec(), str(tmp_path)))
    proc = subprocess.Popen(['ros2', 'run', 'roshanavi', 'dummy', '--config', str(path),
                             '--ros-args', '-r', '__node:=rn_dummy_cam'],
                            start_new_session=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    try:
        wait_for(lambda: len(received) >= 3, timeout=20)
        assert received[0].data.startswith('frame ')
        wait_for(lambda: publisher_nodes(helper, '/rn_dummy_topic') == {'rn_dummy_cam'},
                 timeout=10)
    finally:
        assert stop_group(proc) == 0, proc.stdout.read()


def test_bad_config_exits_with_error(tmp_path):
    path = tmp_path / 'bad.yaml'
    path.write_text('dummy: {id: x}\n')
    result = subprocess.run(['ros2', 'run', 'roshanavi', 'dummy', '--config', str(path)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 2 and 'name: field required' in result.stderr


def test_inject_job_becomes_persistent_dummy(client):
    job = client.post('/api/inject', json={'mode': 'periodic', 'topic': '/rn_persist_topic',
                                           'type': 'std_msgs/msg/String',
                                           'payload': {'data': 'p ${i}'}, 'rate_hz': 10}).json()
    resp = client.post(f'/api/inject/{job["id"]}/persist', json={'name': 'rn_persist'})
    assert resp.status_code == 201, resp.text
    target = resp.json()
    assert target['kind'] == 'dummy' and target['role'] == 'dummy'
    assert target['spec']['payload'] == {'data': 'p ${i}'} and target['spec']['rate_hz'] == 10
    assert client.get(f'/api/inject/{job["id"]}').json()['state'] == 'stopped'

    def mapped():
        graph = client.get('/api/graph').json()
        return next((n for n in graph['nodes'] if n['id'] == '/rn_persist'
                     and n.get('confidence') == 'exact'), None)
    node = wait_for(mapped, timeout=20)
    assert node['role'] == 'dummy' and node['target_id'] == target['id']
    assert client.get('/api/project').json()['project']['dummies'][0]['name'] == 'rn_persist'

    bad = client.post(f'/api/inject/{job["id"]}/persist', json={'name': 'bad name'})
    assert bad.json()['error']['code'] == 'invalid_name'
    escape = client.post('/api/dummies/export', json={'directory': '../../etc'})
    assert escape.status_code == 400 and escape.json()['error']['code'] == 'forbidden_path'


def test_export_runs_with_plain_ros2_launch(tmp_path, data_dir, helper):
    received = helper.collector(String, '/rn_dummy_topic')
    launcher = Launcher(str(tmp_path), str(data_dir), autostart=False)
    try:
        launcher.manager.add(spec())
        result = launcher.export_dummies('launch/dummies')
    finally:
        launcher.close()
    launch_file = result['launch_file']
    assert launch_file == str(tmp_path / 'launch' / 'dummies' / 'roshanavi_dummies.launch.py')
    header = open(launch_file).read()
    assert 'roshanavi package must still be installed' in header
    proc = subprocess.Popen(['ros2', 'launch', launch_file], start_new_session=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        wait_for(lambda: len(received) >= 3, timeout=30)
        wait_for(lambda: publisher_nodes(helper, '/rn_dummy_topic') == {'rn_dummy_cam'},
                 timeout=10)
    finally:
        stop_group(proc)


@pytest.mark.parametrize('bad', ['launch\ndir', 'launch\rdir', 'launch\x7fdir'])
def test_export_rejects_control_characters_in_directory(tmp_path, bad):
    directory = str(tmp_path / bad)
    with pytest.raises(LauncherError) as err:
        export([spec()], directory, str(tmp_path))
    assert err.value.code == 'invalid_request'
    assert not os.path.exists(directory)
    assert os.listdir(tmp_path) == []


def test_export_launch_file_names_its_path_and_compiles(tmp_path):
    result = export([spec()], str(tmp_path / 'launch'), str(tmp_path))
    launch_file = result['launch_file']
    with open(launch_file, encoding='utf-8') as fh:
        text = fh.read()
    assert f'#     ros2 launch {launch_file!r}' in text
    compile(text, launch_file, 'exec')


def test_input_node_created_and_started_in_one_request(client):
    """`＋ 入力ノードを作る`: POST /api/dummies?start=true on a brand-new topic."""
    body = {'id': 'rn-input', 'name': 'rn_input', 'topic': '/rn_brand_new_topic',
            'type': 'std_msgs/msg/String', 'mode': 'periodic', 'payload': {'data': 'n ${i}'},
            'rate_hz': 5, 'autostart': True}
    resp = client.post('/api/dummies?start=true', json=body)
    assert resp.status_code == 201, resp.text
    assert resp.json()['status'] in ('starting', 'running')
    project = client.get('/api/project').json()
    assert project['dirty'] is False  # autosaved
    assert project['project']['dummies'][0]['topic'] == '/rn_brand_new_topic'

    def on_graph():
        graph = client.get('/api/graph').json()
        topic = any(t['name'] == '/rn_brand_new_topic' for t in graph['topics'])
        node = any(n['id'] == '/rn_input' and n['role'] == 'dummy' for n in graph['nodes'])
        return topic and node
    wait_for(on_graph, timeout=20)
    params = wait_for(lambda: client.get('/api/nodes/rn_input/parameters').json()
                      .get('parameters'), timeout=10)
    assert any(p['name'] == 'paused' for p in params)
    paused = client.put('/api/nodes/rn_input/parameters',
                        json={'name': 'paused', 'type': 'bool', 'value': True})
    assert paused.status_code == 200, paused.text  # roshanavi-owned: no confirmation needed
    assert client.delete('/api/targets/rn-input').status_code == 200
    assert client.get('/api/project').json()['project'].get('dummies', []) == []
