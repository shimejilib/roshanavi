"""FastAPI endpoints via TestClient against a live Lab."""

import pytest
from fastapi.testclient import TestClient
from std_msgs.msg import String

from conftest import wait_for
from roshanavi.server import create_app


def test_index_without_static(client):
    body = client.get('/').json()
    assert body['name'] == 'roshanavi'


def test_static_index_served(lab, tmp_path):
    (tmp_path / 'index.html').write_text('<html>ui</html>')
    with TestClient(create_app(lab, static_dir=str(tmp_path)),
                    base_url='http://localhost') as c:
        assert 'ui' in c.get('/').text
        assert c.get('/api/traffic').status_code == 200


def test_graph_and_traffic(client, helper):
    helper.periodic_publisher(String, '/tl_api', 10.0, lambda i: String(data='x'))

    def seen():
        topics = client.get('/api/traffic').json()['topics']
        return any(t['topic'] == '/tl_api' and t['total_count'] > 3 for t in topics)
    wait_for(seen, timeout=15.0)
    graph = client.get('/api/graph').json()
    assert {'nodes', 'topics', 'edges', 'hash'} <= set(graph)
    assert any(t['name'] == '/tl_api' for t in graph['topics'])


def test_inject_job_appears_as_dummy_node_with_diagnostics(client):
    job = client.post('/api/inject', json={'mode': 'periodic', 'topic': '/tl_api_dummy',
                                           'type': 'std_msgs/msg/Int32', 'payload': {'data': 1},
                                           'rate_hz': 20}).json()
    try:
        def dummy_present():
            graph = client.get('/api/graph').json()
            return graph if any(n['id'] == f'dummy:{job["id"]}' for n in graph['nodes']) else None
        graph = wait_for(dummy_present, timeout=15.0)
        assert any(d['code'] == 'no_subscriber' and d['topic'] == '/tl_api_dummy'
                   for d in graph['diagnostics'])

        def counted():
            topics = client.get('/api/traffic').json()['topics']
            return any(t['topic'] == '/tl_api_dummy' and t['recent_count'] > 0 for t in topics)
        wait_for(counted, timeout=15.0)
    finally:
        client.delete(f'/api/inject/{job["id"]}')


def test_types_and_template(client):
    assert 'std_msgs/msg/String' in client.get('/api/types').json()['types']
    body = client.get('/api/types/geometry_msgs/msg/Point/template').json()
    assert body == {'type': 'geometry_msgs/msg/Point', 'template': {'x': 0.0, 'y': 0.0, 'z': 0.0}}
    err = client.get('/api/types/std_msgs/msg/Nope/template')
    assert err.status_code == 404
    assert err.json()['error']['code'] == 'unknown_type'


def test_type_groups_and_data_kinds(client):
    body = client.get('/api/types').json()
    assert body['groups'][0]['id'] == 'common'
    assert body['groups'][0]['types'][0] == 'std_msgs/msg/String'
    assert [g['id'] for g in body['groups'][:2]] == ['common', 'workspace']
    kinds = client.get('/api/data-kinds').json()
    assert kinds['kinds'][0] == {'id': 'string', 'type': 'std_msgs/msg/String',
                                 'available': True, 'python': 'str'}
    assert kinds['type_kinds']['std_msgs/msg/Int32'] == 'int'


def test_inject_lifecycle(client):
    resp = client.post('/api/inject', json={
        'mode': 'periodic', 'topic': '/tl_api_inject', 'type': 'std_msgs/msg/String',
        'payload': {'data': 'v${i}'}, 'rate_hz': 50, 'count': 5})
    assert resp.status_code == 201, resp.text
    job_id = resp.json()['id']
    wait_for(lambda: client.get(f'/api/inject/{job_id}').json()['state'] == 'done', timeout=10.0)
    jobs = client.get('/api/inject').json()['jobs']
    assert any(j['id'] == job_id and j['sent'] == 5 for j in jobs)
    assert client.delete(f'/api/inject/{job_id}').json()['state'] == 'done'


def test_inject_stop_running(client):
    job = client.post('/api/inject', json={'mode': 'periodic', 'topic': '/tl_api_stop',
                                           'type': 'std_msgs/msg/Int32', 'payload': {'data': 1},
                                           'rate_hz': 10}).json()
    assert client.delete(f'/api/inject/{job["id"]}').json()['state'] == 'stopped'


@pytest.mark.parametrize('body,status,code', [
    ({'mode': 'periodic'}, 400, 'invalid_request'),
    ({'mode': 'warp'}, 422, 'validation_error'),
    ({'mode': 'once', 'topic': '/x', 'type': 'std_msgs/msg/String', 'extra': 1},
     422, 'validation_error'),
    ({'mode': 'once', 'topic': '/x', 'type': 'std_msgs/msg/String',
      'payload': {'data': '${open("/etc/passwd")}'}}, 400, 'invalid_expression'),
    ({'mode': 'stream', 'topic': '/x', 'type': 'std_msgs/msg/String',
      'source': '../../etc/passwd', 'rate_hz': 1}, 400, 'forbidden_path'),
    ({'mode': 'bag', 'source': 'missing_bag'}, 404, 'not_found'),
])
def test_inject_errors_use_envelope(client, body, status, code):
    resp = client.post('/api/inject', json=body)
    assert resp.status_code == status, resp.text
    assert resp.json()['error']['code'] == code


def test_unknown_job_404(client):
    resp = client.delete('/api/inject/nope')
    assert resp.status_code == 404
    assert resp.json()['error']['code'] == 'not_found'


def test_files(client, data_dir):
    (data_dir / 'x.jsonl').write_text('{}\n')
    files = client.get('/api/files').json()['files']
    assert files == [{'path': 'x.jsonl', 'size': 3, 'kind': 'jsonl'}]


def test_ws_live_pushes_graph_then_only_traffic(client):
    with client.websocket_connect('ws://localhost/ws/live') as ws:
        first = ws.receive_json()
        assert {'traffic', 'jobs', 'graph'} <= set(first)
        second = ws.receive_json()
        assert 'traffic' in second and 'jobs' in second


def test_ws_echo(client, lab, helper):
    helper.periodic_publisher(String, '/tl_ws_echo', 20.0, lambda i: String(data=f'e{i}'))
    wait_for(lambda: '/tl_ws_echo' in dict(lab.runtime.topic_names_and_types()), timeout=15.0)
    with client.websocket_connect('ws://localhost/ws/echo/tl_ws_echo') as ws:
        frame = ws.receive_json()
        assert frame['topic'] == '/tl_ws_echo'
        assert frame['type'] == 'std_msgs/msg/String'
        assert frame['msg']['data'].startswith('e')


def test_ws_echo_unknown_topic(client):
    with client.websocket_connect('ws://localhost/ws/echo/tl_does_not_exist') as ws:
        assert ws.receive_json()['error']['code'] == 'not_found'
