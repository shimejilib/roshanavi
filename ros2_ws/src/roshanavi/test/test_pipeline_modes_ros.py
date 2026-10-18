"""The small relay pipeline (source -> relay -> sink) started by roshanavi in both modes.

One process per node (exact mapping, three pids) and one composable container (one shared pid)
must carry the same traffic: the sink measures the rate, the processing time and no loss, and
roshanavi's traffic table shows the same rate on every topic.
"""

import time

import pytest

from conftest import wait_for
from pipeline_fixtures import launch_target, write_spec
from roshanavi_examples import pipeline_gen as gen

SinkStats = pytest.importorskip('roshanavi_examples_msgs.msg').SinkStats
PARAMS = gen.preset_params('small', rate_hz=20.0, payload_bytes=2048, process_ms=4.0)
NODES = ['/src', '/relay_1', '/sink']


@pytest.mark.parametrize('mode', ['process', 'container'])
def test_small_pipeline_carries_traffic_in_both_modes(client, helper, tmp_path, mode):
    spec_path, _ = write_spec(str(tmp_path / 'pipe'), PARAMS)
    stats = helper.collector(SinkStats, '/sink/stats')
    assert client.post('/api/targets', json=launch_target('pipe', spec_path, mode)).status_code == 201
    assert client.post('/api/targets/pipe/start').status_code == 200

    def settled():
        last = stats[-1] if stats else None
        return last and last.paths and last.paths[0].rate_hz > 15 and last.paths[0].received > 60
    wait_for(settled, timeout=60)
    time.sleep(5.0)  # a full statistics window of 5 s
    path = stats[-1].paths[0]
    assert path.path == 'src' and path.lost == 0
    assert path.rate_hz == pytest.approx(20.0, rel=0.2)
    assert 4.0 <= path.latency_ms_p50 < 80.0 and path.latency_ms_p95 >= path.latency_ms_p50
    traffic = {e['topic']: e for e in client.get('/api/traffic').json()['topics']}
    for topic in ('/pipe/src', '/pipe/relay_1'):
        assert traffic[topic]['hz'] == pytest.approx(20.0, rel=0.2)
        assert traffic[topic]['avg_size'] == pytest.approx(2048 + 24, abs=64)  # payload + header
    rows = {r['node']: r for r in client.get('/api/node-list').json()['rows']}
    pids = {rows[n]['pid'] for n in NODES}
    if mode == 'container':
        assert len(pids) == 1 and rows['/pipeline_container']['pid'] in pids
        assert {rows[n]['confidence'] for n in NODES} == {'heuristic'}
    else:
        assert len(pids) == 3  # one process each, found by their __node argument
        assert {rows[n]['confidence'] for n in NODES} == {'exact'}
    assert {rows[n]['group'] for n in NODES} == {'pipe'}  # one launch target either way
