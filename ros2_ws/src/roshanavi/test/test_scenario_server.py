"""Scenario API: files (containment, read-only examples, validation with lines), async runs
(progress, cancel, history), record mode (operations + watch timeline + measure), WS."""

import os
import time

import pytest
from starlette.websockets import WebSocketDisconnect
from std_msgs.msg import String

from conftest import WS_ROOT, wait_for

EXAMPLES = os.environ.get('ROSHANAVI_EXAMPLES', '/examples')

PING = {'name': 'ping', 'steps': [
    {'send': {'topic': '/scn_api/ping', 'kind': 'string', 'value': 'hi'}},
    {'expect': {'topic': '/scn_api/pong', 'within': 2.0,
                'where': [{'field': 'data', 'op': 'eq', 'value': 'HI'}]}}]}


@pytest.fixture
def examples_client(data_dir, tmp_path):
    from fastapi.testclient import TestClient
    from roshanavi.lab import Lab
    from roshanavi.server import create_app
    lab = Lab(data_dir=str(data_dir), period_sec=0.2, workspace=WS_ROOT,
              project_path=str(tmp_path / 'p' / 'roshanavi.yaml'), stop_timeouts=(3.0, 2.0),
              examples_dir=EXAMPLES).start()
    with TestClient(create_app(lab, static_dir=None, live_period=0.2),
                    base_url='http://localhost') as c:
        yield c
    lab.stop()


@pytest.fixture
def responder(helper):
    pub = helper.node.create_publisher(String, '/scn_api/pong', 10)
    helper.node.create_subscription(String, '/scn_api/ping',
                                    lambda m: pub.publish(String(data=m.data.upper())), 10)
    return helper


def wait_run(client, run_id, timeout=30.0):
    def done():
        body = client.get(f'/api/scenario-runs/{run_id}').json()
        return body if body['status'] not in ('pending', 'running') else None
    return wait_for(done, timeout=timeout)


def test_save_get_edit_delete(client, lab):
    assert client.get('/api/scenarios').json()['items'] == []
    resp = client.post('/api/scenarios', json={'spec': PING})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body['id'] == 'project:ping.yaml' and body['steps'] == 2
    path = os.path.join(client.get('/api/scenarios').json()['project_dir'], 'ping.yaml')
    assert os.path.isfile(path) and body['yaml'].startswith('# roshanavi のシナリオ')
    assert body['spec']['steps'][0]['send']['value'] == 'hi'
    assert client.post('/api/scenarios', json={'spec': PING}).status_code == 409
    bad = client.put('/api/scenarios/project:ping.yaml',
                     json={'yaml': 'name: x\nsteps:\n  - wait: 1\n  - expect: {topic: /a}\n'})
    assert bad.status_code == 422
    err = bad.json()['error']
    assert err['code'] == 'invalid_scenario' and err['errors'][0]['line'] == 4
    ok = client.put('/api/scenarios/project:ping.yaml',
                    json={'yaml': '# my comment\nname: x\nsteps:\n  - wait: 1\n'})
    assert ok.status_code == 200 and ok.json()['yaml'].startswith('# my comment')
    check = client.post('/api/scenarios/validate', json={'yaml': 'name: x\nsteps: []\n'}).json()
    assert check['ok'] is False and check['errors'][0]['path'] == 'steps'
    assert client.delete('/api/scenarios/project:ping.yaml').json() == {
        'deleted': 'project:ping.yaml'}
    assert not os.path.exists(path)


def test_ids_are_contained(client, tmp_path):
    for bad in ('..%2Fx.yaml', 'project:..%2F..%2Fetc%2Fpasswd', 'other:x.yaml', 'project:x.txt',
                'project:.hidden.yaml'):
        resp = client.get(f'/api/scenarios/{bad}')
        assert resp.status_code in (400, 404), (bad, resp.text)
    project_dir = client.get('/api/scenarios').json()['project_dir']
    os.makedirs(project_dir, exist_ok=True)
    outside = tmp_path / 'outside.yaml'
    outside.write_text('name: secret\nsteps:\n  - wait: 1\n')
    os.symlink(outside, os.path.join(project_dir, 'link.yaml'))
    assert client.get('/api/scenarios/project:link.yaml').status_code == 403
    assert client.delete('/api/scenarios/project:link.yaml').status_code == 403
    assert outside.exists()
    assert [i['id'] for i in client.get('/api/scenarios').json()['items']] == []
    resp = client.post('/api/scenarios', content='{}', headers={'Content-Type': 'text/plain'})
    assert resp.status_code == 415
    resp = client.post('/api/scenarios/project:x.yaml/run', headers={'Host': 'evil.example'})
    assert resp.status_code == 403
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('ws://localhost/ws/scenarios',
                                      headers={'Origin': 'http://evil.com'}) as ws:
            ws.receive_json()


def test_examples_are_listed_and_read_only(examples_client):
    items = {i['id']: i for i in examples_client.get('/api/scenarios').json()['items']}
    assert {'example:state_machine.yaml', 'example:perception.yaml'} <= set(items)
    assert items['example:state_machine.yaml']['read_only'] is True
    assert items['example:state_machine.yaml']['guards'] == 1
    assert examples_client.put('/api/scenarios/example:state_machine.yaml',
                               json={'spec': PING}).status_code == 403
    assert examples_client.delete('/api/scenarios/example:state_machine.yaml').status_code == 403


def test_run_progress_history_and_busy(client, lab, responder):
    client.post('/api/scenarios', json={'spec': PING})
    run = client.post('/api/scenarios/project:ping.yaml/run')
    assert run.status_code == 202
    run_id = run.json()['run_id']
    result = wait_run(client, run_id)
    assert result['status'] == 'passed', result
    assert result['steps'][1]['status'] == 'passed' and '1 件届きました' in result['steps'][1]['message']
    runs = client.get('/api/scenario-runs').json()['runs']
    assert runs[0]['run_id'] == run_id and runs[0]['status'] == 'passed'
    assert os.path.isfile(os.path.join(lab.data_dir, 'scenario_results', f'{run_id}.json'))
    listed = client.get('/api/scenarios').json()['items'][0]
    assert listed['last_result']['run_id'] == run_id
    client.post('/api/scenarios', json={'spec': {'name': 'slow', 'steps': [{'wait': 30}]}})
    slow = client.post('/api/scenarios/project:slow.yaml/run').json()
    assert client.post('/api/scenarios/project:ping.yaml/run').status_code == 409
    with client.websocket_connect('ws://localhost/ws/scenarios') as ws:
        frame = ws.receive_json()
        assert frame['running'] is True and frame['run']['run_id'] == slow['run_id']
        assert frame['run']['steps'][0]['status'] == 'running'
    assert client.post(f'/api/scenario-runs/{slow["run_id"]}/cancel').status_code == 200
    assert wait_run(client, slow['run_id'])['status'] == 'cancelled'


def test_run_failure_has_explanation_and_hints(client):
    client.post('/api/scenarios', json={'spec': {'name': 'lost', 'steps': [
        {'send': {'topic': '/scn_api/nobody_listens', 'kind': 'string', 'value': 'x'}},
        {'expect': {'topic': '/scn_api/no_reply', 'within': 0.5, 'kind': 'string'}}]}})
    run_id = client.post('/api/scenarios/project:lost.yaml/run').json()['run_id']
    result = wait_run(client, run_id)
    step = result['steps'][1]
    assert result['status'] == 'failed' and '1 件も届きませんでした' in step['message']
    codes = [h['code'] for h in step['hints']]
    assert 'no_publisher' in codes and 'no_subscriber' in codes


def test_invalid_file_run_gives_error_result(client, lab):
    project_dir = client.get('/api/scenarios').json()['project_dir']
    os.makedirs(project_dir, exist_ok=True)
    with open(os.path.join(project_dir, 'broken.yaml'), 'w') as fh:
        fh.write('name: b\nsteps:\n  - expekt: {}\n')
    item = client.get('/api/scenarios').json()['items'][0]
    assert item['errors'][0]['line'] == 3
    result = client.post('/api/scenarios/project:broken.yaml/run').json()
    assert result['status'] == 'error' and result['schema_errors'][0]['line'] == 3


def test_record_mode_timeline_ops_and_measure(client, lab, helper):
    helper.periodic_publisher(String, '/scn_rec/out', 20.0, lambda i: String(data=f'v{i}'))
    wait_for(lambda: '/scn_rec/out' in dict(lab.runtime.topic_names_and_types()))
    assert client.post('/api/scenario-record', json={'watch': ['/scn_rec/missing']}
                       ).status_code == 404
    started = client.post('/api/scenario-record', json={'watch': ['/scn_rec/out']})
    assert started.status_code == 201, started.text
    assert started.json()['session']['types'] == {'/scn_rec/out': 'std_msgs/msg/String'}
    job = client.post('/api/inject', json={'mode': 'once', 'topic': '/scn_rec/in',
                                           'type': 'std_msgs/msg/String',
                                           'payload': {'data': 'go'}}).json()
    periodic = client.post('/api/inject', json={'mode': 'periodic', 'topic': '/scn_rec/in',
                                                'type': 'std_msgs/msg/String',
                                                'payload': {'data': 'tick'}, 'rate_hz': 5}).json()
    client.delete(f'/api/inject/{periodic["id"]}')
    time.sleep(1.5)
    body = client.get('/api/scenario-record').json()
    ops = [e for e in body['events'] if e['kind'] == 'op']
    assert [o['op']['kind'] for o in ops] == ['inject', 'inject', 'inject_stop']
    assert ops[0]['op']['request']['payload'] == {'data': 'go'} and ops[0]['op']['job_id'] == job['id']
    msgs = [e for e in body['events'] if e['kind'] == 'msg']
    assert msgs and msgs[0]['topic'] == '/scn_rec/out' and msgs[0]['data']['data'].startswith('v')
    # The 20 Hz topic is thinned on the timeline: a burst of 10, then 10 per second.
    session = body['session']
    assert len(msgs) < session['counts']['/scn_rec/out']
    assert len(msgs) <= 10 + 10 * session['elapsed_sec'] + 2
    since = body['events'][-1]['seq']
    assert all(e['seq'] > since for e in client.get(f'/api/scenario-record?since={since}').json()['events'])
    stopped = client.delete('/api/scenario-record').json()
    assert stopped['active'] is False
    end = stopped['session']['elapsed_sec']
    rate = client.post('/api/scenario-record/measure',
                       json={'kind': 'rate', 'topic': '/scn_rec/out', 'start': 0.2,
                             'end': end}).json()
    assert 15 < rate['hz'] < 25 and rate['count'] > 20
    counted = client.post('/api/scenario-record/measure',
                          json={'kind': 'throughput', 'input': '/scn_rec/out',
                                'output': '/scn_rec/out', 'start': 0.2, 'end': end}).json()
    assert counted['ratio'] == 1.0
    # Operations made after the session stopped are not recorded.
    client.post('/api/inject', json={'mode': 'once', 'topic': '/scn_rec/in',
                                     'type': 'std_msgs/msg/String', 'payload': {'data': 'late'}})
    assert len([e for e in client.get('/api/scenario-record').json()['events']
                if e['kind'] == 'op']) == 3
    assert client.delete('/api/scenario-record?discard=true').json() == {'active': False,
                                                                        'session': None}
    assert client.get('/api/scenario-record').json()['events'] == []
