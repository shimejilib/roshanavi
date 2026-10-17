"""Lifecycle client against a real lifecycle node (lifecycle/lifecycle_talker) + API."""

import os
import signal
import subprocess
import uuid

import pytest

from conftest import wait_for
from roshanavi.api_errors import ApiError
from roshanavi.graph import lifecycle_nodes
from roshanavi.lifecycle import LifecycleService, plan_goal
from roshanavi.ros_runtime import RosRuntime


def test_lifecycle_nodes_from_service_list():
    services = [('/lc/get_state', ['lifecycle_msgs/srv/GetState']),
                ('/fake/get_state', ['example_interfaces/srv/Trigger']),
                ('/lc/change_state', ['lifecycle_msgs/srv/ChangeState']),
                ('/ns/b/get_state', ['lifecycle_msgs/srv/GetState'])]
    assert lifecycle_nodes(services) == ['/lc', '/ns/b']


@pytest.mark.parametrize('state,goal,steps', [
    ('unconfigured', 'active', ['configure', 'activate']),
    ('inactive', 'active', ['activate']),
    ('active', 'active', []),
    ('active', 'inactive', ['deactivate']),
    ('inactive', 'inactive', []),
    ('finalized', 'active', [])])
def test_plan_goal(state, goal, steps):
    assert plan_goal(state, goal) == steps


def test_plan_goal_rejects_unknown_goal():
    with pytest.raises(ApiError):
        plan_goal('active', 'off')


@pytest.fixture
def lc_node():
    name = f'lc_{uuid.uuid4().hex[:6]}'
    proc = subprocess.Popen(['ros2', 'run', 'lifecycle', 'lifecycle_talker', '--ros-args',
                             '-r', f'__node:={name}'], start_new_session=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    yield f'/{name}'
    os.killpg(proc.pid, signal.SIGINT)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()


@pytest.fixture
def lc_runtime():
    runtime = RosRuntime(f'roshanavi_lc_{uuid.uuid4().hex[:6]}')
    runtime.start()
    yield runtime
    runtime.stop()


@pytest.fixture
def lifecycle_service(lc_runtime):
    service = LifecycleService(lc_runtime, timeout_sec=5.0)
    yield service
    service.close()


def test_real_lifecycle_node_transitions(lc_node, lifecycle_service):
    info = wait_for(lambda: _try_info(lifecycle_service, lc_node), timeout=20)
    assert info['state']['label'] == 'unconfigured'
    assert [t['label'] for t in info['transitions']] == ['configure']  # shutdown hidden
    with pytest.raises(ApiError) as err:
        lifecycle_service.change(lc_node, 'activate')
    assert err.value.code == 'lifecycle_transition_unavailable'
    assert lifecycle_service.change(lc_node, 'configure')['state']['label'] == 'inactive'
    reached = lifecycle_service.reach(lc_node, 'active')
    assert reached['state']['label'] == 'active' and reached['steps'] == ['activate']
    assert lifecycle_service.reach(lc_node, 'inactive')['state']['label'] == 'inactive'
    assert lifecycle_service.states([lc_node]) == {lc_node: 'inactive'}
    assert lifecycle_service.change(lc_node, 'cleanup')['state']['label'] == 'unconfigured'
    with pytest.raises(ApiError) as err:
        lifecycle_service.change(lc_node, 'shutdown')
    assert err.value.code == 'invalid_lifecycle_transition'


def test_missing_node_times_out(lc_runtime):
    service = LifecycleService(lc_runtime, timeout_sec=0.3)
    assert service.states(['/no_such_lc_node']) == {'/no_such_lc_node': None}
    with pytest.raises(ApiError) as err:
        service.state('/no_such_lc_node')
    assert err.value.code == 'lifecycle_unavailable' and err.value.status == 504
    service.close()


def _try_info(service, node):
    try:
        return service.info(node)
    except ApiError:
        return None


def test_lifecycle_api(lc_node, client):
    path = f'/api/nodes{lc_node}/lifecycle'

    def on_graph():
        nodes = client.get('/api/graph').json()['nodes']
        return any(n['id'] == lc_node and n.get('lifecycle') for n in nodes)
    wait_for(on_graph, timeout=20)
    assert client.get(path).json()['state']['label'] == 'unconfigured'
    denied = client.post(path, json={'goal': 'active'})
    assert denied.status_code == 403 and denied.json()['error']['code'] == 'external_node_readonly'
    both = client.post(path, json={'goal': 'active', 'transition': 'configure',
                                   'allow_external': True})
    assert both.status_code == 400
    done = client.post(path, json={'goal': 'active', 'allow_external': True})
    assert done.status_code == 200, done.text
    assert done.json()['state']['label'] == 'active' and done.json()['steps'] == [
        'configure', 'activate']
    rows = client.get('/api/node-list').json()['rows']
    row = next(r for r in rows if r['node'] == lc_node)
    assert row['control'] == 'lifecycle' and row['lifecycle']['state'] == 'active'
    plain = client.get('/api/nodes/roshanavi_nope/lifecycle')
    assert plain.status_code == 404
