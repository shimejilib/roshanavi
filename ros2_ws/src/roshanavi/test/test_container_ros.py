"""Composable container verified with real nodes (testing.md H-30 / K-31).

A generated relay pipeline (12 nodes, a 4 x 3 grid of independent columns whose sources run at
20 / 10 / 5 Hz) runs inside one ComposableNodeContainer started by `ros2 launch`. roshanavi must
then: map every node to the container process and group them in the node list, show the
resources per container (not per node), list all nodes that stop together for the confirmation,
stop the whole container, import the launch file as a whole (the container is a fallback), and
still measure every node separately with the detailed tracing mode.
"""

import time
from types import SimpleNamespace

import psutil
import pytest

from conftest import WS_ROOT, wait_for
from pipeline_fixtures import launch_target, pipeline_node_ids, write_spec
from roshanavi.tracing.service import availability
from roshanavi_examples import pipeline_gen as gen

TARGET = 'pc'
WINDOW = 5.0
RATES = (20.0, 10.0, 5.0)  # sources src_0, src_1, src_2 -> the columns
PARAMS = gen.PipelineParams(shape='grid', stages=4, width=3, links='straight')


def graph_ids(client):
    return {n['id'] for n in client.get('/api/graph').json()['nodes']}


def target_info(client, target_id=TARGET):
    return next(t for t in client.get('/api/targets').json()['targets'] if t['id'] == target_id)


@pytest.fixture(scope='module')
def running(tmp_path_factory):
    """One Lab with the pipeline running in a composable container (shared by the tests below)."""
    from fastapi.testclient import TestClient
    from roshanavi.lab import Lab
    from roshanavi.server import create_app
    base = tmp_path_factory.mktemp('container')
    spec_path, spec = write_spec(str(base / 'pipe'), PARAMS, source_rates=RATES)
    data = base / 'data'
    data.mkdir()
    lab = Lab(data_dir=str(data), period_sec=0.2, workspace=WS_ROOT,
              project_path=str(base / 'project' / 'roshanavi.yaml'), stop_timeouts=(3.0, 2.0),
              probe='auto', tracing='auto').start()
    with TestClient(create_app(lab, static_dir=None, live_period=0.2),
                    base_url='http://localhost') as client:
        assert client.post('/api/targets', json=launch_target(
            TARGET, spec_path, 'container')).status_code == 201
        assert client.post(f'/api/targets/{TARGET}/start').status_code == 200
        ids = pipeline_node_ids(spec)
        wait_for(lambda: set(ids) <= graph_ids(client), timeout=90)
        yield SimpleNamespace(lab=lab, client=client, spec=spec, ids=ids, spec_path=spec_path)
    lab.stop()


def test_every_node_maps_to_the_container_process_and_forms_one_group(running):
    client, ids = running.client, running.ids
    wait_for(lambda: all(n['target_id'] == TARGET for n in client.get('/api/graph').json()['nodes']
                         if n['id'] in ids), timeout=20)
    rows = client.get('/api/node-list').json()
    by_node = {r['node']: r for r in rows['rows']}
    container = by_node['/pipeline_container']
    pids = {by_node[i]['pid'] for i in ids}
    assert pids == {container['pid']}  # one process: the container
    assert psutil.Process(container['pid']).name().startswith('component_conta')
    assert {by_node[i]['confidence'] for i in ids} == {'heuristic'}  # per container, not per node
    assert container['confidence'] == 'exact'  # the container's own node carries __node:=
    assert {by_node[i]['group'] for i in ids} == {TARGET}
    group = next(g for g in rows['groups'] if g['id'] == TARGET)
    assert set(ids) <= set(group['nodes']) and '/pipeline_container' in group['nodes']
    assert group['kind'] == 'launch' and group['label'] == 'pipeline.launch.py'
    assert {by_node[i]['control'] for i in ids} == {'target'}  # the map offers stop / restart


def test_the_launch_services_own_node_is_not_attributed_to_the_container(running):
    client = running.client
    launch_node = next(n for n in client.get('/api/graph').json()['nodes']
                       if n['id'].startswith('/launch_ros_'))
    launch_pid = int(launch_node['id'].rsplit('_', 1)[1])
    row = next(r for r in client.get('/api/node-list').json()['rows'] if r['node'] == launch_node['id'])
    assert row['pid'] == launch_pid  # lives in the `ros2 launch` process (found in this fixed bug)
    container_pid = next(r['pid'] for r in client.get('/api/node-list').json()['rows']
                         if r['node'] == '/pipeline_container')
    assert launch_pid != container_pid


def test_resources_are_per_container_not_per_node(running):
    client, ids = running.client, running.ids
    def container_with_nodes():
        snap = client.get('/api/resources').json()
        procs = [p for p in snap['processes'] if p['name'].startswith('component_conta')]
        return snap if procs and set(ids) <= set(procs[0]['nodes']) else None
    snap = wait_for(container_with_nodes, timeout=30)
    containers = [p for p in snap['processes'] if p['name'].startswith('component_conta')]
    assert len(containers) == 1
    proc = containers[0]
    assert proc['label'] == TARGET and proc['target_id'] == TARGET and proc['role'] == 'mine'
    assert set(ids) <= set(proc['nodes'])
    assert proc['rss'] > 0 and proc['threads'] >= 1
    wait_for(lambda: client.get('/api/resources').json()['nodes'][ids[0]]['cpu_pct'] is not None,
             timeout=20)
    nodes = client.get('/api/resources').json()['nodes']
    for node in ids:
        entry = nodes[node]
        assert entry['pid'] == proc['pid'] and entry['scope'] == 'process'
        assert set(entry['shared']) | {node} >= set(ids)  # "shared with n nodes"
    # the value of a node is the value of the whole container
    assert len({nodes[i]['cpu_pct'] for i in ids}) == 1 and len({nodes[i]['rss'] for i in ids}) == 1
    wrapper = [p for p in snap['processes'] if p['name'] == 'ros2' and p['target_id'] == TARGET]
    assert wrapper and not set(wrapper[0]['nodes']) & set(ids)  # ros2 launch itself hosts none of them


def test_traffic_between_nodes_in_the_container_is_visible(running):
    client = running.client
    topics = wait_for(lambda: (lambda t: t if t.get('/pipe/src_0') and t['/pipe/src_0']['hz'] > 10
                               else None)({e['topic']: e for e in client.get('/api/traffic').json()['topics']}),
                      timeout=30)
    assert topics['/pipe/src_0']['hz'] == pytest.approx(20.0, rel=0.2)
    assert topics['/pipe/src_2']['hz'] == pytest.approx(5.0, rel=0.3)
    entry = topics['/pipe/src_0']
    assert [p['node'] for p in entry['publishers']] == ['/src_0']
    assert [s['node'] for s in entry['subscribers']] == ['/relay_1_0']


@pytest.mark.skipif(availability() is not None, reason='lttng-tools / python3-bt2 not installed')
def test_tracing_counts_callbacks_of_each_node_inside_the_container(running):
    lab, client = running.lab, running.client
    assert client.put('/api/tracing', json={'enabled': True}).json()['active'] is True

    def subscribers():
        if (lab.tracing.status()['active_sec'] or 0) < WINDOW + 2.5:
            return None
        found = {}
        for entry in lab.traffic_view(WINDOW):
            for sub in entry.get('subscribers') or []:
                if sub['node'].startswith('/relay_') and sub.get('basis') == 'measured':
                    found[sub['node']] = sub
        return found if len(found) >= 6 else None
    measured = wait_for(subscribers, timeout=60.0, interval=0.5)
    for column, rate in enumerate(RATES):
        for stage in (1, 2):
            sub = measured[f'/relay_{stage}_{column}']
            assert sub['lang'] == 'cpp' and sub['cb_ms'] is not None
            assert sub['hz_processed'] == pytest.approx(rate, rel=0.25), sub['node']
            assert sub['hz_recv'] == pytest.approx(rate, rel=0.25), sub['node']
    # three nodes of one process, three different counts: the trace separates them
    assert len({round(measured[f'/relay_1_{c}']['hz_processed']) for c in range(3)}) == 3
    status = client.get('/api/tracing').json()
    unsupported = {u['node']: u['reason'] for u in status['unsupported']}
    assert not [n for n in running.ids if n in unsupported]  # all pipeline nodes are measured
    assert all(n.startswith('/launch_ros_') for n in unsupported), unsupported  # rclpy: receive only
    assert client.put('/api/tracing', json={'enabled': False}).json()['active'] is False


def test_the_confirmation_lists_every_node_that_stops_with_the_container(running):
    client, ids = running.client, running.ids
    info = target_info(client)
    nodes = {n['node'] for n in info['nodes']}
    assert set(ids) <= nodes and '/pipeline_container' in nodes  # what the dialog enumerates
    graph = {n['id']: n for n in client.get('/api/graph').json()['nodes']}
    for node in ids:  # whichever node the user picks on the map leads to the same target
        assert graph[node]['target_id'] == TARGET
    assert info['status'] == 'running' and len(info['pids']) >= 2  # ros2 launch + the container


def test_stopping_one_node_stops_the_whole_container(running):
    """The last test: stop via any node's target stops all of them (and nothing is left behind)."""
    client, ids = running.client, running.ids
    pids = list(target_info(client)['pids'])
    stopped = client.post(f'/api/targets/{TARGET}/stop')
    assert stopped.status_code == 200 and stopped.json()['status'] == 'stopped'
    wait_for(lambda: not (set(ids) & graph_ids(client)), timeout=30)  # all gone at once
    wait_for(lambda: all(not psutil.pid_exists(p) or psutil.Process(p).status() == psutil.STATUS_ZOMBIE
                         for p in pids), timeout=15)
    rows = client.get('/api/node-list').json()['rows']
    stopped_row = next(r for r in rows if r['key'] == f'target:{TARGET}')
    assert stopped_row['running'] is False and stopped_row['status'] == 'stopped'
    time.sleep(0.5)
    assert client.post(f'/api/targets/{TARGET}/start').status_code == 200  # and it comes back whole
    wait_for(lambda: set(ids) <= graph_ids(client), timeout=90)
    client.post(f'/api/targets/{TARGET}/stop')


# ---- launch import: the container is a fallback, the whole launch file is the unit -------------

@pytest.fixture
def pipeline_spec(tmp_path):
    return write_spec(str(tmp_path / 'pipe'), PARAMS, source_rates=RATES)


def preview(client, spec_path, mode):
    body = {'source': {'kind': 'package', 'package': 'roshanavi_examples',
                       'launch_file': 'pipeline.launch.py'},
            'args': {'spec': spec_path, 'mode': mode}}
    resp = client.post('/api/launch-import/preview', json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_launch_import_treats_the_container_as_a_fallback_and_offers_the_whole_launch(
        client, pipeline_spec):
    spec_path, spec = pipeline_spec
    plan = preview(client, spec_path, 'container')
    assert plan['nodes'] == []  # nothing can be taken apart
    blocked = [b for b in plan['blocked'] if b['code'] == 'composable_container']
    assert len(blocked) == 1
    assert sorted(c.split('(')[1].rstrip(')') for c in blocked[0]['composable_nodes']) == \
        sorted(n['name'] for n in spec['nodes'])  # the nodes inside are listed
    assert plan['whole'] is not None and plan['whole_reason'] is None
    commit = client.post('/api/launch-import/commit', json={
        'preview_id': plan['preview_id'], 'mode': 'whole', 'role': 'mine'})
    assert commit.status_code == 201, commit.text
    created = commit.json()['created'][0]
    assert created['kind'] == 'launch' and created['spec']['launch_file'] == 'pipeline.launch.py'
    assert 'mode:=container' in created['spec']['args']


def test_launch_import_of_the_same_pipeline_in_process_mode_is_taken_apart(client, pipeline_spec):
    spec_path, spec = pipeline_spec
    plan = preview(client, spec_path, 'process')
    assert sorted(n['spec']['name'] for n in plan['nodes']) == sorted(n['name'] for n in spec['nodes'])
    assert all(n['importable'] for n in plan['nodes'])
    assert not [b for b in plan['blocked'] if b['code'] == 'composable_container']


def test_launch_import_of_a_200_node_launch_stays_within_the_time_limit(client, tmp_path):
    """K-34: a launch file with hundreds of nodes is evaluated within 20 seconds."""
    spec_path, spec = write_spec(str(tmp_path / 'pipe'), gen.preset_params('large'))
    started = time.monotonic()
    plan = preview(client, spec_path, 'process')
    elapsed = time.monotonic() - started
    assert len(plan['nodes']) == 200 and all(n['importable'] for n in plan['nodes'])
    assert elapsed < 20.0, elapsed


@pytest.fixture
def intra_pipeline(data_dir, tmp_path):
    """The small pipeline in a container with use_intra_process_comms, in its own Lab."""
    from fastapi.testclient import TestClient
    from roshanavi.lab import Lab
    from roshanavi.server import create_app
    spec_path, _ = write_spec(str(tmp_path / 'pipe'),
                              gen.preset_params('small', rate_hz=20.0, payload_bytes=512))
    lab = Lab(data_dir=str(data_dir), period_sec=0.2, workspace=WS_ROOT,
              project_path=str(tmp_path / 'project' / 'roshanavi.yaml'), stop_timeouts=(3.0, 2.0),
              probe='auto', tracing='auto').start()
    try:
        with TestClient(create_app(lab, static_dir=None, live_period=0.2),
                        base_url='http://localhost') as client:
            assert client.post('/api/targets', json=launch_target(
                'ip', spec_path, 'container', intra_process='true')).status_code == 201
            client.post('/api/targets/ip/start')
            wait_for(lambda: {'/src', '/relay_1', '/sink'} <= graph_ids(client), timeout=60)
            yield lab, client
            client.post('/api/targets/ip/stop')
    finally:
        lab.stop()


def test_intra_process_container_keeps_the_traffic_visible(intra_pipeline):
    """The probe is a separate process, so the traffic of intra-process nodes is still measured."""
    lab, client = intra_pipeline
    topics = wait_for(lambda: (lambda t: t if t.get('/pipe/relay_1') and t['/pipe/relay_1']['hz'] > 10
                               else None)({e['topic']: e for e in
                                           client.get('/api/traffic').json()['topics']}),
                      timeout=30)
    assert topics['/pipe/src']['hz'] == pytest.approx(20.0, rel=0.25)
    assert topics['/pipe/relay_1']['hz'] == pytest.approx(20.0, rel=0.25)


@pytest.mark.xfail(strict=True, reason=(
    'found by the container check: with use_intra_process_comms the callbacks of the '
    'container nodes are not attributed to their subscriptions (hz_processed 0, intra false), so '
    'the detailed tracing mode shows a false "processing behind". Remove this xfail when the '
    'tracing model handles intra-process subscriptions.'))
@pytest.mark.skipif(availability() is not None, reason='lttng-tools / python3-bt2 not installed')
def test_intra_process_container_is_not_reported_as_behind_by_tracing(intra_pipeline):
    lab, client = intra_pipeline
    assert client.put('/api/tracing', json={'enabled': True}).json()['active'] is True

    def measured():
        if (lab.tracing.status()['active_sec'] or 0) < WINDOW + 2.5:
            return None
        entry = next((e for e in lab.traffic_view(WINDOW) if e['topic'] == '/pipe/src'), None)
        sub = next((s for s in (entry or {}).get('subscribers') or [] if s['node'] == '/relay_1'), None)
        return sub if sub and sub.get('basis') == 'measured' else None
    sub = wait_for(measured, timeout=60.0, interval=0.5)
    assert sub['behind'] is None and sub['hz_processed'] == pytest.approx(20.0, rel=0.25)
