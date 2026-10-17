"""Launcher with real ROS processes: run / launch targets, roles, mapping, logs."""

import time

import psutil
import pytest
from starlette.websockets import WebSocketDisconnect

from conftest import wait_for


def graph_node(client, node_id):
    graph = client.get('/api/graph').json()
    return next((n for n in graph['nodes'] if n['id'] == node_id), None)


def target(client, target_id):
    return client.get(f'/api/targets/{target_id}').json()


def add_and_start(client, spec):
    resp = client.post('/api/targets', json=spec)
    assert resp.status_code == 201, resp.text
    started = client.post(f'/api/targets/{spec["id"]}/start')
    assert started.status_code == 200, started.text
    return started.json()


def all_gone(pids):
    for pid in pids:
        try:
            if psutil.Process(pid).status() != psutil.STATUS_ZOMBIE:
                return False
        except psutil.NoSuchProcess:
            continue
    return True


def test_run_target_heuristic_mapping_role_mine_and_stop(client):
    add_and_start(client, {'id': 'tk', 'kind': 'run', 'package': 'demo_nodes_cpp',
                           'executable': 'talker', 'role': 'mine'})
    node = wait_for(lambda: (lambda n: n if n and n['role'] == 'mine' else None)(
        graph_node(client, '/talker')), timeout=20)
    assert node['target_id'] == 'tk' and node['confidence'] == 'heuristic'
    info = wait_for(lambda: (lambda t: t if t['nodes'] else None)(
        next(t for t in client.get('/api/targets').json()['targets'] if t['id'] == 'tk')))
    assert info['status'] in ('starting', 'running') and info['nodes'][0]['node'] == '/talker'
    pids = info['pids']
    assert len(pids) >= 2  # ros2 run wrapper + the talker executable
    stopped = client.post('/api/targets/tk/stop').json()
    assert stopped['status'] == 'stopped'
    wait_for(lambda: all_gone(pids), timeout=10)
    wait_for(lambda: (graph_node(client, '/talker') or {'role': 'other'})['role'] == 'other',
             timeout=15)


def test_named_run_target_exact_mapping_and_logs(client):
    add_and_start(client, {'id': 'named', 'kind': 'run', 'package': 'demo_nodes_cpp',
                           'executable': 'talker', 'name': 'rn_exact', 'namespace': 'rn',
                           'remaps': {'chatter': '/rn_chat'}, 'role': 'dependency'})
    node = wait_for(lambda: graph_node(client, '/rn/rn_exact'), timeout=20)
    wait_for(lambda: (graph_node(client, '/rn/rn_exact') or {}).get('confidence') == 'exact')
    node = graph_node(client, '/rn/rn_exact')
    assert node['role'] == 'dependency' and node['target_id'] == 'named'
    mapped = wait_for(lambda: target(client, 'named') and next(
        (t['nodes'] for t in client.get('/api/targets').json()['targets']
         if t['id'] == 'named' and t['nodes']), None))
    child = psutil.Process(mapped[0]['pid'])
    assert child.cmdline()[0].endswith('demo_nodes_cpp/talker')  # the node, not ros2 run
    graph = client.get('/api/graph').json()
    assert any(e['node'] == '/rn/rn_exact' and e['topic'] == '/rn_chat' for e in graph['edges'])

    with client.websocket_connect('ws://localhost/ws/logs/named') as ws:
        seen = []
        while not any('Publishing' in ln['text'] for ln in seen):
            frame = ws.receive_json()
            seen += frame['lines']
        assert seen[0]['stream'] == 'system' and seen[0]['text'].startswith('$ ')
        assert any(ln['stream'] in ('stdout', 'stderr') for ln in seen)
    logs = client.get('/api/targets/named/logs').json()
    assert logs['cursor'] >= len(logs['lines']) > 0
    client.post('/api/targets/named/stop')


def test_launch_target_maps_every_node(client):
    add_and_start(client, {'id': 'pair', 'kind': 'launch', 'package': 'demo_nodes_cpp',
                           'launch_file': 'talker_listener_launch.py'})

    def both():
        talker, listener = graph_node(client, '/talker'), graph_node(client, '/listener')
        return (talker and listener and talker.get('target_id') == 'pair'
                and listener.get('target_id') == 'pair')
    wait_for(both, timeout=25)
    assert graph_node(client, '/listener')['role'] == 'dependency'
    info = target(client, 'pair')
    assert len(info['pids']) >= 3  # ros2 launch + talker + listener
    pids = info['pids']
    client.post('/api/targets/pair/stop')
    wait_for(lambda: all_gone(pids), timeout=10)


def test_restart_and_crash_status(client):
    add_and_start(client, {'id': 'rs', 'kind': 'run', 'package': 'demo_nodes_py',
                           'executable': 'talker', 'name': 'rn_restart'})
    first = target(client, 'rs')['pid']
    again = client.post('/api/targets/rs/restart').json()
    assert again['restart_count'] == 1 and again['pid'] != first
    client.delete('/api/targets/rs')
    assert client.get('/api/targets/rs').status_code == 404


def test_api_rejects_bad_targets(client):
    cases = [
        ({'id': 'x', 'kind': 'run', 'package': 'demo_nodes_cpp', 'executable': 'talker',
          'args': ['--ros-args', '-r', '__node:=x']}, 400, 'invalid_arg'),
        ({'id': 'x', 'kind': 'run', 'package': 'demo_nodes_cpp', 'executable': 'nope'},
         404, 'unknown_executable'),
        ({'id': 'x', 'kind': 'run', 'package': 'demo_nodes_cpp', 'executable': 'talker',
          'params_file': '/etc/passwd'}, 400, 'forbidden_path'),
        ({'id': 'x', 'kind': 'run', 'package': 'demo_nodes_cpp', 'executable': 'talker',
          'shell': 'rm -rf /'}, 422, 'validation_error'),
        ({'id': '../x', 'kind': 'run', 'package': 'demo_nodes_cpp', 'executable': 'talker'},
         422, 'validation_error'),
    ]
    for body, status, code in cases:
        resp = client.post('/api/targets', json=body)
        assert resp.status_code == status, (body, resp.text)
        assert resp.json()['error']['code'] == code
    assert client.post('/api/targets/none/start').json()['error']['code'] == 'not_found'
    with client.websocket_connect('ws://localhost/ws/logs/none') as ws:
        assert ws.receive_json()['error']['code'] == 'not_found'


def test_autostart_from_project(tmp_path, data_dir):
    from roshanavi.lab import Lab
    project = tmp_path / 'roshanavi.yaml'
    project.write_text('targets:\n- {id: auto, kind: run, package: demo_nodes_cpp, '
                       'executable: listener, name: rn_auto, autostart: true}\n'
                       '- {id: manual, kind: run, package: demo_nodes_cpp, executable: talker}\n')
    lab = Lab(data_dir=str(data_dir), period_sec=0.2, workspace=str(tmp_path),
              project_path=str(project)).start()
    try:
        wait_for(lambda: lab.launcher.manager.get('auto')['status'] == 'running', timeout=15)
        assert lab.launcher.manager.get('manual')['status'] == 'stopped'
    finally:
        lab.stop()
    assert lab.launcher.manager.get('auto')['status'] == 'stopped'

    lab = Lab(data_dir=str(data_dir), period_sec=0.2, workspace=str(tmp_path),
              project_path=str(project), autostart=False).start()  # --no-autostart
    try:
        time.sleep(3.0)  # past the autostart delay
        assert lab.launcher.manager.get('auto')['status'] == 'stopped'
    finally:
        lab.stop()


def test_log_websocket_and_mutations_pass_the_security_middleware(client):
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect('ws://localhost/ws/logs/_build',
                                      headers={'Origin': 'http://evil.com'}) as ws:
            ws.receive_json()
    assert exc.value.code == 1008
    resp = client.post('/api/targets', content='{}', headers={'Content-Type': 'text/plain'})
    assert resp.status_code == 415
    resp = client.post('/api/build', json={'package': 'roshanavi'},
                       headers={'Host': 'evil.example:6871'})
    assert resp.status_code == 403
