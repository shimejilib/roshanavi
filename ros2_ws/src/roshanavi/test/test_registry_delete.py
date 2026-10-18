"""Node list bulk delete + undo: only roshanavi's registrations, processes stop, undo restores
(and restarts what was running); code and packages are never touched."""

import pytest

from conftest import wait_for
from roshanavi.launcher.errors import LauncherError
from roshanavi.launcher.schema import DummySpec, TargetSpec
from roshanavi.launcher.service import Launcher
from roshanavi.launcher.trash import Trash

DUMMY = dict(name='rd_dummy', topic='/rd_topic', type='std_msgs/msg/String', mode='periodic',
             payload={'data': 'x'}, rate_hz=2.0)


@pytest.fixture
def launcher(tmp_path, data_dir):
    instance = Launcher('/ws', str(data_dir), project_path=str(tmp_path / 'p.yaml'),
                        autostart=False, timeouts=(3.0, 2.0))
    yield instance
    instance.close()


def test_delete_stops_and_undo_restores(launcher, tmp_path):
    clock = [0.0]
    trash = Trash(launcher, ttl_sec=10.0, clock=lambda: clock[0])
    launcher.add(TargetSpec(id='rd-talker', kind='run', package='demo_nodes_cpp',
                            executable='talker', name='rd_talker', params={'x': 1}), start=True)
    launcher.add(DummySpec(id='rd-dummy', **DUMMY))  # registered, not running
    wait_for(lambda: launcher.manager.target('rd-talker').alive(), timeout=10)
    pid = launcher.manager.get('rd-talker')['pid']
    result = trash.delete(['rd-talker', 'rd-dummy'])
    assert [(r['id'], r['kind'], r['was_running']) for r in result['removed']] == [
        ('rd-talker', 'run', True), ('rd-dummy', 'dummy', False)]
    assert launcher.manager.list() == []
    assert 'rd-talker' not in (tmp_path / 'p.yaml').read_text()  # autosaved
    restored = trash.undo(result['undo_id'])
    assert restored == {'restored': ['rd-talker', 'rd-dummy'], 'started': ['rd-talker'],
                        'errors': []}
    assert launcher.manager.get('rd-talker')['spec']['params'] == {'x': 1}
    assert launcher.manager.get('rd-talker')['pid'] != pid
    assert launcher.manager.get('rd-dummy')['status'] == 'stopped'
    assert 'rd-dummy' in (tmp_path / 'p.yaml').read_text()
    with pytest.raises(LauncherError) as err:
        trash.undo(result['undo_id'])  # once only
    assert err.value.code == 'undo_expired'
    again = trash.delete(['rd-dummy'])
    clock[0] = 11.0
    with pytest.raises(LauncherError):
        trash.undo(again['undo_id'])  # too late


def test_unknown_id_changes_nothing(launcher):
    trash = Trash(launcher)
    launcher.add(DummySpec(id='rd-dummy', **DUMMY))
    with pytest.raises(LauncherError) as err:
        trash.delete(['rd-dummy', 'nope'])
    assert err.value.code == 'not_found'
    assert [t['id'] for t in launcher.manager.list()] == ['rd-dummy']


def test_delete_api(client):
    created = client.post('/api/dummies', json={'id': 'rd-api', **DUMMY})
    assert created.status_code == 201, created.text
    resp = client.post('/api/registry/delete', json={'ids': ['rd-api']})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body['removed'][0]['id'] == 'rd-api' and body['undo_sec'] > 10
    assert client.get('/api/targets/rd-api').status_code == 404
    assert client.post('/api/registry/delete', json={'ids': ['Bad Id']}).status_code in (400,
                                                                                          422)
    undo = client.post('/api/registry/undo', json={'undo_id': body['undo_id']})
    assert undo.status_code == 200 and undo.json()['restored'] == ['rd-api']
    assert client.get('/api/targets/rd-api').status_code == 200
    assert client.post('/api/registry/undo', json={'undo_id': body['undo_id']}
                       ).status_code == 404
    client.delete('/api/targets/rd-api')
