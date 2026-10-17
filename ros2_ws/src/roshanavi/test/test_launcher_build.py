"""Build button against a tiny ament_python package in a temp workspace.

Also covers what only a freshly built (not yet sourced) package can show:
targets of it still start (colcon .dsv overlay) and a launch file that names
its node gives an *exact* node<->process mapping.
"""

import pytest
from fastapi.testclient import TestClient

from conftest import wait_for
from roshanavi.lab import Lab
from roshanavi.launcher.build import extract_errors
from roshanavi.server import create_app
from ws_fixtures import FIXTURE_PKG, ament_python_package


@pytest.fixture(scope='module')
def ws(tmp_path_factory):
    root = tmp_path_factory.mktemp('ws')
    ament_python_package(root / 'src')
    ament_python_package(root / 'src', name='rn_broken', broken=True)
    return root


@pytest.fixture
def ws_client(ws, tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    lab = Lab(data_dir=str(data), period_sec=0.2, workspace=str(ws),
              project_path=str(tmp_path / 'p.yaml'), stop_timeouts=(3.0, 2.0)).start()
    with TestClient(create_app(lab, static_dir=None, live_period=0.2),
                    base_url='http://localhost') as client:
        yield client
    lab.stop()


def build(client, package, **kw):
    resp = client.post('/api/build', json={'package': package, **kw})
    assert resp.status_code == 202, resp.text
    return wait_for(lambda: (lambda s: s if s['state'] != 'running' else None)(
        client.get('/api/build').json()), timeout=180)


def package(client, name):
    return next(p for p in client.get('/api/workspace').json()['packages'] if p['name'] == name)


def test_build_success_then_run_and_launch_unsourced_package(ws_client):
    before = package(ws_client, FIXTURE_PKG)
    assert before['built'] is False and before['source_dir'].endswith(f'src/{FIXTURE_PKG}')
    status = build(ws_client, FIXTURE_PKG)
    assert status['state'] == 'succeeded', status
    assert status['needs_resource'] is True and status['exit_code'] == 0
    logs = ws_client.get('/api/targets/_build/logs').json()['lines']
    assert any('Finished <<< rn_fixture' in ln['text'] for ln in logs)
    after = package(ws_client, FIXTURE_PKG)
    assert after['built'] and not after['sourced']
    assert after['executables'] == ['hello'] and after['launch_files'] == ['named.launch.py']

    ws_client.post('/api/targets', json={'id': 'hello', 'kind': 'run', 'package': FIXTURE_PKG,
                                         'executable': 'hello'})
    ws_client.post('/api/targets/hello/start')
    wait_for(lambda: ws_client.get('/api/targets/hello').json()['status'] == 'exited',
             timeout=20)
    lines = ws_client.get('/api/targets/hello/logs').json()['lines']
    assert any(ln['text'] == 'hello from fixture' for ln in lines), lines

    ws_client.post('/api/targets', json={'id': 'named', 'kind': 'launch', 'package': FIXTURE_PKG,
                                         'launch_file': 'named.launch.py', 'role': 'mine'})
    ws_client.post('/api/targets/named/start')

    def exact():
        graph = ws_client.get('/api/graph').json()
        node = next((n for n in graph['nodes'] if n['id'] == '/rn_ns/rn_named_talker'), None)
        return node if node and node.get('confidence') == 'exact' else None
    node = wait_for(exact, timeout=30)
    assert node['role'] == 'mine' and node['target_id'] == 'named'

    status = build(ws_client, FIXTURE_PKG, restart_running=True)
    assert status['state'] == 'succeeded' and status['restarted'] == ['named']
    assert ws_client.get('/api/targets/named').json()['restart_count'] == 1


def test_build_failure_reports_first_errors(ws_client):
    status = build(ws_client, 'rn_broken')
    # A broken setup.py makes colcon skip the package and still exit 0.
    assert status['state'] == 'failed', status
    assert status['error_lines'], status
    assert any('Error' in line for line in status['error_lines'])


def test_build_rejections(ws_client):
    resp = ws_client.post('/api/build', json={'package': 'demo_nodes_cpp'})
    assert resp.status_code == 400 and resp.json()['error']['code'] == 'not_buildable'
    resp = ws_client.post('/api/build', json={'package': 'a; rm -rf /'})
    assert resp.json()['error']['code'] == 'invalid_package'


def test_extract_errors_finds_compiler_lines():
    lines = ['Starting >>> pkg', 'src/a.cpp:3:5: error: expected ";"', '   3 | int x', 'ok',
             'Failed   <<< pkg']
    assert extract_errors(lines)[0] == 'src/a.cpp:3:5: error: expected ";"'
    assert extract_errors(['all fine', 'really']) == ['all fine', 'really']
