"""Launch takeover (--launch): import + start, carry-over / lost report, idempotent restart,
change detection and re-import, the remainder launch, whole mode (docs/design/integration.md)."""

import os
import time

import psutil
import pytest
import yaml

from conftest import wait_for
from roshanavi.launch_import.importer import LaunchImporter
from roshanavi.launch_import.skip import REST_LAUNCH_FILE, decode
from roshanavi.launch_import.takeover import TakeoverService
from roshanavi.launcher.errors import LauncherError
from roshanavi.launcher.service import Launcher
from takeover_fixtures import PACKAGE, make_workspace


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / 'ws'
    make_workspace(root)
    return root


class Rig:
    """Launcher + takeover on one project file; ``restart()`` simulates a server restart."""

    def __init__(self, ws, data_dir, project):
        self.ws, self.data_dir, self.project = ws, data_dir, project
        self.launcher = self.takeover = None
        self.open()

    def open(self, autostart=True):
        self.launcher = Launcher(str(self.ws), str(self.data_dir), project_path=str(self.project),
                                 autostart=False, timeouts=(3.0, 2.0))
        importer = LaunchImporter(self.launcher, str(self.data_dir), timeout_sec=30.0)
        self.takeover = TakeoverService(importer, str(self.data_dir), poll_sec=0.2,
                                        autostart=autostart)

    def close(self):
        self.takeover.close()
        self.launcher.close()

    def restart(self, autostart=True):
        self.close()
        self.open(autostart)

    def targets(self):
        return {t['id']: t for t in self.launcher.targets()}


@pytest.fixture
def rig(ws, data_dir, tmp_path):
    instance = Rig(ws, data_dir, tmp_path / 'roshanavi.yaml')
    yield instance
    instance.close()


def codes(items):
    return sorted(i['code'] for i in items)


def take(rig, launch_file, mode='node', mine=(), **args):
    rig.takeover.configure(PACKAGE, launch_file, args, mode=mode, mine=mine, wait=True)
    status = rig.takeover.status()
    assert status['state'] == 'ready', status
    return status


def test_per_node_takeover_carries_and_reports(rig):
    status = take(rig, 'tk_full.launch.py', mine=['tk_talker'], rate='7')
    targets = rig.targets()
    runs = {t['spec']['name']: t for t in targets.values() if t['kind'] == 'run'}
    assert sorted(runs) == ['tk_extra', 'tk_inner', 'tk_listener', 'tk_talker']
    talker = runs['tk_talker']['spec']
    assert talker['role'] == 'mine' and runs['tk_listener']['spec']['role'] == 'dependency'
    assert talker['auto_restart'] is True  # respawn=True
    assert talker['env'] == {'TK_COLOR': 'blue', 'TK_SHAPE': 'square'}
    assert talker['params'] == {'rate': 7, 'label': 'from file'}
    assert all(t['spec']['takeover'] and t['spec']['imported_from'] ==
               f'{PACKAGE}/tk_full.launch.py' for t in targets.values())
    rest = [t for t in targets.values() if t['kind'] == 'launch']
    assert len(rest) == 1 and rest[0]['spec']['launch_file'] == REST_LAUNCH_FILE
    skip_arg = next(a for a in rest[0]['spec']['args'] if a.startswith('roshanavi_skip:='))
    assert {k[2] for k in decode(skip_arg.split(':=', 1)[1])} == set(runs)
    assert 'rate:=7' in rest[0]['spec']['args']
    report = status['report']
    assert codes(report['carried']) == ['env', 'respawn']
    lost = {i['code']: i for i in report['lost']}
    assert {'required', 'respawn_delay', 'events', 'timer_order', 'conditions_fixed'} <= set(lost)
    assert lost['required']['nodes'] == ['/tk_listener']
    assert report['suggest_whole'] is True
    assert {i['code'] for i in report['rest']} >= {'timer', 'event_handler', 'execute_process'}
    # everything runs, and the persisted project remembers which file was taken over
    wait_for(lambda: all(t['status'] == 'running' for t in rig.launcher.targets()), timeout=20)
    saved = yaml.safe_load(rig.project.read_text())
    assert saved['takeover'] == {'package': PACKAGE, 'launch_file': 'tk_full.launch.py',
                                 'args': ['rate:=7'], 'mode': 'node'}


def _node_procs(target):
    procs = []
    for pid in target['pids']:
        try:
            procs.append(' '.join(psutil.Process(pid).cmdline()))
        except psutil.Error:
            continue
    return procs


def test_remainder_skips_the_separate_nodes_and_env_reaches_the_node(rig):
    take(rig, 'tk_full.launch.py')
    rest = next(t for t in rig.launcher.targets() if t['kind'] == 'launch')

    def rest_ready():
        cmds = _node_procs(next(t for t in rig.launcher.targets() if t['id'] == rest['id']))
        return cmds if any('tk_late' in c for c in cmds) and any('sleep 600' in c
                                                                  for c in cmds) else None
    cmds = wait_for(rest_ready, timeout=30)
    for name in ('tk_talker', 'tk_listener', 'tk_inner', 'tk_extra'):
        assert not any(f'__node:={name}' in c for c in cmds), (name, cmds)
    talker = next(t for t in rig.launcher.targets() if t['spec'].get('name') == 'tk_talker')

    def env_of_node():
        for pid in reversed(talker['pids']):
            try:
                env = psutil.Process(pid).environ()
            except psutil.Error:
                continue
            if 'TK_COLOR' in env:
                return env
        return None
    env = wait_for(env_of_node, timeout=10)
    assert env['TK_COLOR'] == 'blue' and env['TK_SHAPE'] == 'square'


def test_restart_reuses_targets_and_roles(rig):
    take(rig, 'tk_simple.launch.py', mine=['tk_b'])
    first = rig.targets()
    assert sorted(t['spec']['name'] for t in first.values()) == ['tk_a', 'tk_b']
    assert not any(t['kind'] == 'launch' for t in first.values())  # nothing left over
    rig.restart()
    take(rig, 'tk_simple.launch.py')  # same file + args: reuse, no duplicates
    second = rig.targets()
    assert sorted(second) == sorted(first)
    assert second[next(i for i in second if second[i]['spec']['name'] == 'tk_b')
                  ]['spec']['role'] == 'mine'
    assert rig.takeover.status()['pending'] is None
    wait_for(lambda: all(t['status'] == 'running' for t in rig.launcher.targets()), timeout=20)
    # other arguments: the same targets are updated in place (no second set)
    rig.restart(autostart=False)
    take(rig, 'tk_simple.launch.py', topic='other')
    third = rig.targets()
    assert sorted(third) == sorted(first)
    assert all(t['spec']['remaps'] == {'chatter': 'other'} for t in third.values())


def test_change_while_stopped_waits_for_the_user(rig, ws):
    take(rig, 'tk_simple.launch.py')
    rig.restart(autostart=False)
    launch = ws / 'install' / PACKAGE / 'share' / PACKAGE / 'launch' / 'tk_simple.launch.py'
    launch.write_text(launch.read_text().replace("name='tk_b'", "name='tk_c'"))
    status = take(rig, 'tk_simple.launch.py')
    pending = status['pending']
    assert pending['reason'] == 'changed_since_last'
    assert [a['label'] for a in pending['added']] == ['/tk_c']
    assert [r['label'] for r in pending['removed']] == ['/tk_b']
    assert sorted(t['spec']['name'] for t in rig.launcher.targets()) == ['tk_a', 'tk_b']
    result = rig.takeover.apply(pending['preview_id'])
    assert result['errors'] == []
    assert sorted(t['spec']['name'] for t in rig.launcher.targets()) == ['tk_a', 'tk_c']
    with pytest.raises(LauncherError) as err:
        rig.takeover.apply(pending['preview_id'])
    assert err.value.code == 'preview_expired'


def test_launch_file_change_is_detected_and_only_changed_nodes_restart(rig, ws):
    take(rig, 'tk_simple.launch.py')
    wait_for(lambda: all(t['status'] == 'running' for t in rig.launcher.targets()), timeout=20)
    before = {t['spec']['name']: t['pid'] for t in rig.launcher.targets()}
    launch = ws / 'install' / PACKAGE / 'share' / PACKAGE / 'launch' / 'tk_simple.launch.py'
    text = launch.read_text()
    text = text.replace("name='tk_a',", "name='tk_a', parameters=[{'x': 1}],")
    text = text.replace("    ])\n", "        Node(package='demo_nodes_cpp', executable='talker',"
                                   " name='tk_new'),\n    ])\n")
    time.sleep(0.05)
    launch.write_text(text)
    pending = wait_for(lambda: rig.takeover.status()['pending'], timeout=20)
    assert pending['reason'] == 'file_changed'
    assert pending['files'] == [str(launch.resolve())] or pending['files'] == [
        os.path.relpath(launch.resolve(), ws)]
    assert [a['label'] for a in pending['added']] == ['/tk_new']
    assert [(c['label'], c['fields']) for c in pending['changed']] == [('/tk_a', ['params'])]
    result = rig.takeover.apply(pending['preview_id'])
    assert result['restarted'] == [c['id'] for c in pending['changed']]
    after = {t['spec']['name']: t for t in rig.launcher.targets()}
    assert after['tk_a']['spec']['params'] == {'x': 1}
    assert after['tk_b']['pid'] == before['tk_b']  # unchanged: not restarted
    assert after['tk_a']['pid'] != before['tk_a']
    wait_for(lambda: next(t for t in rig.launcher.targets()
                          if t['spec']['name'] == 'tk_new')['status'] == 'running', timeout=20)


def test_touching_without_a_change_is_not_reported(rig, ws):
    take(rig, 'tk_simple.launch.py')
    launch = ws / 'install' / PACKAGE / 'share' / PACKAGE / 'launch' / 'tk_simple.launch.py'
    os.utime(launch, None)
    time.sleep(2.0)  # several polls: evaluated again, same result
    assert rig.takeover.status()['pending'] is None


def test_whole_mode_keeps_launch_behaviour(rig):
    status = take(rig, 'tk_exit.launch.py', mode='whole', mine=['tk_whole_talker'])
    assert status['report']['lost'] == [] and status['report']['suggest_whole'] is False
    (target,) = rig.launcher.targets()
    assert target['kind'] == 'launch' and target['spec']['launch_file'] == 'tk_exit.launch.py'
    assert target['spec']['role'] == 'mine'
    # OnProcessExit -> Shutdown works because ros2 launch runs the file as it is
    wait_for(lambda: rig.launcher.targets()[0]['status'] == 'exited', timeout=30)


def test_missing_args_and_bad_input(rig):
    with pytest.raises(LauncherError):
        rig.takeover.configure(PACKAGE, '../etc/passwd', {})
    with pytest.raises(LauncherError):
        rig.takeover.configure('no such', 'x.launch.py', {})
    rig.takeover.configure(PACKAGE, 'nope.launch.py', {}, wait=True)
    assert rig.takeover.status()['state'] == 'error'
    assert rig.takeover.status()['error']['code'] == 'unknown_launch_file'


def test_takeover_api(client, lab):
    resp = client.get('/api/takeover')
    assert resp.status_code == 200 and resp.json()['active'] is False
    bad = client.post('/api/takeover/start', json={'package': 'x', 'launch_file': 'a.py',
                                                   'extra': 1})
    assert bad.status_code in (400, 422)
    resp = client.post('/api/takeover/start', json={
        'package': 'roshanavi', 'launch_file': 'demo_system.launch.py', 'args': {'robot': 'tk'},
        'mode': 'node'})
    assert resp.status_code == 202, resp.text
    status = wait_for(lambda: (lambda s: s if s['state'] in ('ready', 'error') else None)(
        client.get('/api/takeover').json()), timeout=40)
    assert status['state'] == 'ready', status
    ids = status['targets']
    assert len(ids) == 3  # talker, listener + the rest (ExecuteProcess)
    assert client.post('/api/takeover/check').json()['pending'] is None
    assert client.post('/api/takeover/apply', json={'preview_id': '0' * 32}).status_code == 404
    for target_id in ids:
        client.delete(f'/api/targets/{target_id}')
