"""Recording: ros2 bag record start/stop -> valid bag playable by bag mode; disk guard."""

import os
import time

import pytest
from std_msgs.msg import String

from conftest import wait_for
from roshanavi.jobs import InjectSpec
from roshanavi.media.diskguard import MIB, DiskGuard, DiskThresholds
from roshanavi.media.errors import MediaError
from roshanavi.media.recorder import Recorder

GIB = 1024 * MIB


@pytest.mark.parametrize('free,total,level', [
    (50 * GIB, 100 * GIB, 'ok'),
    (900 * MIB, 50 * GIB, 'warn'),      # below 1 GiB
    (4 * GIB, 100 * GIB, 'warn'),       # below 5 %
    (200 * MIB, 100 * GIB, 'stop'),     # below 256 MiB
    (500 * MIB, 40 * GIB, 'warn'),
    (300 * MIB, 40 * GIB, 'stop'),      # below 1 %
])
def test_disk_guard_levels(free, total, level):
    guard = DiskGuard('/x', usage=lambda _p: (free, total))
    assert guard.check()['level'] == level


def test_disk_guard_thresholds_are_configurable():
    guard = DiskGuard('/x', DiskThresholds(warn_mb=10, warn_pct=0, stop_mb=5, stop_pct=0),
                      usage=lambda _p: (8 * MIB, 100 * GIB))
    assert guard.check()['level'] == 'warn'


def test_refuses_to_start_on_a_full_disk(tmp_path):
    rec = Recorder(str(tmp_path), DiskGuard(str(tmp_path), usage=lambda _p: (MIB, 100 * GIB)))
    with pytest.raises(MediaError) as err:
        rec.start(['/a'])
    assert err.value.code == 'disk_full'


def test_validation(tmp_path):
    rec = Recorder(str(tmp_path))
    for topics, name in (([], ''), (['bad topic'], ''), (['/a'], '../x')):
        with pytest.raises(Exception):
            rec.start(topics, name)
    with pytest.raises(MediaError):
        rec.delete('../etc')
    with pytest.raises(MediaError):
        rec.stop()


def test_record_stop_list_play_delete(client, lab, helper, data_dir):
    helper.periodic_publisher(String, '/tl_rec', 20.0, lambda i: String(data=f'rec {i}'))
    wait_for(lambda: lab.runtime.publishers_info('/tl_rec'), timeout=10)
    resp = client.post('/api/recordings', json={'topics': ['/tl_rec'], 'name': 'demo'})
    assert resp.status_code == 201, resp.text
    started = resp.json()
    assert started['path'].startswith('recordings/') and started['path'].endswith('_demo')
    assert client.post('/api/recordings', json={'topics': ['/tl_rec']}).status_code == 409
    active = client.get('/api/recordings').json()['active']
    assert active['topics'] == ['/tl_rec'] and active['elapsed_sec'] >= 0
    time.sleep(2.5)
    stopped = client.post('/api/recordings/stop').json()
    assert stopped['stop_reason'] == 'user' and 'error' not in stopped
    listing = client.get('/api/recordings').json()
    [item] = listing['recordings']
    assert item['finalized'] and item['message_count'] > 10 and item['duration_sec'] > 1
    assert item['topics'][0]['name'] == '/tl_rec' and item['size'] > 0
    files = client.get('/api/files').json()['files']
    assert {'path': item['path'], 'kind': 'bag'}.items() <= next(
        f for f in files if f['path'] == item['path']).items()

    job = lab.injector.start(InjectSpec(mode='bag', source=item['path'],
                                        bag_topics=('/tl_rec',)))
    wait_for(lambda: lab.injector.get(job['id'])['state'] != 'running', timeout=30)
    assert lab.injector.get(job['id'])['state'] == 'done'
    assert client.delete(f"/api/recordings/{item['name']}").json() == {'deleted': item['name']}
    assert not os.path.exists(data_dir / item['path'])


def test_bag_mode_replays_recording_messages(lab, helper, data_dir):
    helper.periodic_publisher(String, '/tl_rec2', 20.0, lambda i: String(data=f'r {i}'))
    wait_for(lambda: lab.runtime.publishers_info('/tl_rec2'), timeout=10)
    lab.recorder.start(['/tl_rec2'])
    time.sleep(2.0)
    info = lab.recorder.stop()
    assert info['exit_code'] == 0
    received = helper.collector(String, '/tl_rec2')  # bag replays on the original topic
    job = lab.injector.start(InjectSpec(mode='bag', source=info['path']))
    wait_for(lambda: lab.injector.get(job['id'])['state'] == 'done', timeout=30)
    assert any(m.data.startswith('r ') for m in received)


def test_disk_full_stops_recording(lab, data_dir, helper):
    helper.periodic_publisher(String, '/tl_rec3', 20.0, lambda i: String(data='x'))
    free = {'bytes': 50 * GIB}
    rec = Recorder(str(data_dir), DiskGuard(str(data_dir),
                                            usage=lambda _p: (free['bytes'], 100 * GIB)),
                   monitor_period=0.2)
    rec.start(['/tl_rec3'], 'full')
    free['bytes'] = 4 * GIB
    wait_for(lambda: (rec.status()['active'] or {}).get('warning'), timeout=5)
    free['bytes'] = 100 * MIB
    wait_for(lambda: rec.status()['active'] is None, timeout=20)
    assert rec.status()['last']['stop_reason'] == 'disk_full'
