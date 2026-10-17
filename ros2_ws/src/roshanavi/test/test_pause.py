"""Pause / resume of inject jobs and of persistent dummy nodes (``paused`` parameter)."""

import time

import pytest

from conftest import wait_for
from roshanavi.dummy_node import install_pause_parameter
from roshanavi.jobs import InjectError
from roshanavi.params import ParamService
from roshanavi.ros_runtime import RosRuntime

PERIODIC = {'mode': 'periodic', 'topic': '/pause_test', 'type': 'std_msgs/msg/String',
            'payload': {'data': 'x'}, 'rate_hz': 50}


def sent(client, job_id):
    return client.get(f'/api/inject/{job_id}').json()['sent']


def test_periodic_job_pauses_and_resumes(client):
    job = client.post('/api/inject', json=PERIODIC).json()
    wait_for(lambda: sent(client, job['id']) > 3)
    paused = client.post(f'/api/inject/{job["id"]}/pause').json()
    assert paused['paused'] is True and paused['pausable'] is True
    time.sleep(0.2)
    frozen = sent(client, job['id'])
    time.sleep(0.4)
    assert sent(client, job['id']) == frozen
    assert client.post(f'/api/inject/{job["id"]}/resume').json()['paused'] is False
    wait_for(lambda: sent(client, job['id']) > frozen + 3)
    client.delete(f'/api/inject/{job["id"]}')


def test_once_and_finished_jobs_cannot_pause(client):
    once = client.post('/api/inject', json={**PERIODIC, 'mode': 'once'}).json()
    assert once['pausable'] is False
    resp = client.post(f'/api/inject/{once["id"]}/pause')
    assert resp.status_code in (400, 409)
    assert client.post('/api/inject/nope/pause').status_code == 404


class FakeInjector:
    def __init__(self):
        self.calls = []

    def set_paused(self, job_id, paused):
        if job_id == 'gone':
            raise InjectError('not_running', 'job is not running', 409)
        self.calls.append((job_id, paused))


@pytest.fixture
def pair():
    node_rt, client_rt = RosRuntime('roshanavi_dummy_t', require_self_name=False), \
        RosRuntime('roshanavi_pclient')
    node_rt.start()
    client_rt.start()
    yield node_rt, ParamService(client_rt, timeout_sec=3.0)
    client_rt.stop()
    node_rt.stop()


def test_dummy_paused_parameter_drives_the_job(pair):
    node_rt, service = pair
    injector = FakeInjector()
    install_pause_parameter(node_rt.node, injector, 'job1')
    name = node_rt.node.get_fully_qualified_name()
    params = {p['name']: p for p in service.list(name)}
    assert params['paused']['value'] is False
    service.set(name, 'paused', 'bool', True)
    service.set(name, 'paused', 'bool', False)
    assert injector.calls == [('job1', True), ('job1', False)]
    with pytest.raises(Exception):
        service.set(name, 'paused', 'string', 'yes')


def test_dummy_paused_parameter_reports_job_errors(pair):
    node_rt, service = pair
    install_pause_parameter(node_rt.node, FakeInjector(), 'gone')
    with pytest.raises(Exception) as info:
        service.set(node_rt.node.get_fully_qualified_name(), 'paused', 'bool', True)
    assert 'not running' in str(info.value)
