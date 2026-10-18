"""Relay pipeline sample nodes (roshanavi_examples) as standalone processes: what each parameter does.

source -> relay -> sink are started with `ros2`-less direct executables (like the tracing tests do)
and observed from a test node, so the semantics documented in docs/design/nodes.md are checked
against the real C++ nodes: payload size, rate limit, random drops, fan-out, stamp handling,
processing time, runtime parameter changes and the sink statistics.
"""

import os
import subprocess
import time

import pytest

from conftest import wait_for

Payload = pytest.importorskip('roshanavi_examples_msgs.msg').Payload
SinkStats = pytest.importorskip('roshanavi_examples_msgs.msg').SinkStats


def _executable(name):
    from ament_index_python.packages import get_package_prefix
    return os.path.join(get_package_prefix('roshanavi_examples'), 'lib', 'roshanavi_examples', name)


class Procs:
    def __init__(self):
        self.procs = []

    def start(self, executable, node, *params, remaps=()):
        argv = [_executable(executable), '--ros-args', '-r', f'__node:={node}']
        for src, dst in remaps:
            argv += ['-r', f'{src}:={dst}']
        for param in params:
            argv += ['-p', param]
        proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        self.procs.append(proc)
        return proc

    def close(self):
        for proc in self.procs:
            proc.terminate()
        for proc in self.procs:
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5.0)


@pytest.fixture
def procs():
    group = Procs()
    yield group
    group.close()


def count_after(received, seconds):
    """Messages that arrive during the next ``seconds``."""
    start = len(received)
    time.sleep(seconds)
    return len(received) - start


def test_chain_passes_messages_with_stamp_payload_and_sequence(helper, procs):
    seen = helper.collector(Payload, '/t1/b')
    procs.start('pipeline_source', 'src', 'rate_hz:=20.0', 'payload_bytes:=300',
                remaps=[('out', '/t1/a')])
    procs.start('pipeline_relay', 'rel', remaps=[('in', '/t1/a'), ('out', '/t1/b')])
    wait_for(lambda: len(seen) >= 10, timeout=20)
    msg = seen[5]
    assert msg.header.frame_id == 'src' and len(msg.data) == 300  # -1: input passed through
    assert [m.seq for m in seen[:10]] == sorted(m.seq for m in seen[:10])
    assert msg.header.stamp.sec > 1_000_000_000  # stamped with the wall clock


def test_payload_bytes_resizes_and_minus_one_keeps(helper, procs):
    small = helper.collector(Payload, '/t2/small')
    big = helper.collector(Payload, '/t2/big')
    procs.start('pipeline_source', 'src2', 'rate_hz:=20.0', 'payload_bytes:=64',
                remaps=[('out', '/t2/a')])
    procs.start('pipeline_relay', 'rel_big', 'payload_bytes:=5000',
                remaps=[('in', '/t2/a'), ('out', '/t2/big')])
    procs.start('pipeline_relay', 'rel_small', 'payload_bytes:=10',
                remaps=[('in', '/t2/a'), ('out', '/t2/small')])
    wait_for(lambda: len(big) >= 3 and len(small) >= 3, timeout=20)
    assert {len(m.data) for m in big} == {5000} and {len(m.data) for m in small} == {10}


def test_rate_limit_caps_the_output(helper, procs):
    out = helper.collector(Payload, '/t3/b')
    procs.start('pipeline_source', 'src3', 'rate_hz:=100.0', remaps=[('out', '/t3/a')])
    procs.start('pipeline_relay', 'rel3', 'rate_limit_hz:=10.0',
                remaps=[('in', '/t3/a'), ('out', '/t3/b')])
    wait_for(lambda: len(out) >= 3, timeout=20)
    n = count_after(out, 4.0)
    assert 30 <= n <= 42, n  # about 10 Hz for 4 s, never the 100 Hz of the input


def test_drop_ratio_drops_a_share_and_one_drops_everything(helper, procs):
    half = helper.collector(Payload, '/t4/half')
    none = helper.collector(Payload, '/t4/none')
    procs.start('pipeline_source', 'src4', 'rate_hz:=50.0', remaps=[('out', '/t4/a')])
    procs.start('pipeline_relay', 'rel_half', 'drop_ratio:=0.5', 'seed:=7',
                remaps=[('in', '/t4/a'), ('out', '/t4/half')])
    procs.start('pipeline_relay', 'rel_none', 'drop_ratio:=1.0',
                remaps=[('in', '/t4/a'), ('out', '/t4/none')])
    wait_for(lambda: len(half) >= 3, timeout=20)
    n = count_after(half, 6.0)
    assert 90 <= n <= 210, n  # 50 Hz * 6 s * 0.5 = 150
    assert len(none) == 0


def test_fanout_all_and_round_robin(helper, procs):
    all_a, all_b = helper.collector(Payload, '/t5/all_a'), helper.collector(Payload, '/t5/all_b')
    rr_a, rr_b = helper.collector(Payload, '/t5/rr_a'), helper.collector(Payload, '/t5/rr_b')
    procs.start('pipeline_source', 'src5', 'rate_hz:=20.0', remaps=[('out', '/t5/a')])
    procs.start('pipeline_relay', 'rel_all', 'num_outputs:=2', remaps=[
        ('in', '/t5/a'), ('out', '/t5/all_a'), ('out_1', '/t5/all_b')])
    procs.start('pipeline_relay', 'rel_rr', 'num_outputs:=2', 'fanout:=round_robin', remaps=[
        ('in', '/t5/a'), ('out', '/t5/rr_a'), ('out_1', '/t5/rr_b')])
    wait_for(lambda: len(all_a) >= 10 and len(rr_a) >= 5, timeout=20)
    time.sleep(2.0)
    assert abs(len(all_a) - len(all_b)) <= 2  # every message goes to both
    assert abs(len(rr_a) - len(rr_b)) <= 2    # they take turns ...
    assert len(rr_a) + len(rr_b) <= len(all_a) + 3  # ... so together they carry what one 'all' output does
    seqs = {m.seq for m in rr_a} & {m.seq for m in rr_b}
    assert not seqs  # no message went out twice


def test_fanin_two_inputs_into_one_relay(helper, procs):
    out = helper.collector(Payload, '/t6/out')
    procs.start('pipeline_source', 'src6a', 'rate_hz:=10.0', remaps=[('out', '/t6/a')])
    procs.start('pipeline_source', 'src6b', 'rate_hz:=10.0', remaps=[('out', '/t6/b')])
    procs.start('pipeline_relay', 'rel6', 'num_inputs:=2', remaps=[
        ('in', '/t6/a'), ('in_1', '/t6/b'), ('out', '/t6/out')])
    wait_for(lambda: {m.header.frame_id for m in out} == {'src6a', 'src6b'}, timeout=20)
    n = count_after(out, 3.0)
    assert 45 <= n <= 70, n  # both sources: about 20 Hz


def test_keep_stamp_true_copies_and_false_restamps(helper, procs):
    kept = helper.collector(Payload, '/t7/kept')
    fresh = helper.collector(Payload, '/t7/fresh')
    raw = helper.collector(Payload, '/t7/a')
    procs.start('pipeline_source', 'src7', 'rate_hz:=20.0', remaps=[('out', '/t7/a')])
    procs.start('pipeline_relay', 'rel_kept', 'process_ms:=30.0', remaps=[
        ('in', '/t7/a'), ('out', '/t7/kept')])
    procs.start('pipeline_relay', 'rel_fresh', 'process_ms:=30.0', 'keep_stamp:=false', remaps=[
        ('in', '/t7/a'), ('out', '/t7/fresh')])
    wait_for(lambda: len(kept) >= 5 and len(fresh) >= 5 and len(raw) >= 5, timeout=20)
    stamp_of = {m.seq: (m.header.stamp.sec, m.header.stamp.nanosec) for m in raw}
    first = min(stamp_of)  # the helper may discover the source later than the relays do
    checked_kept = [m for m in kept if m.seq in stamp_of and m.seq >= first]
    checked_fresh = [m for m in fresh if m.seq in stamp_of and m.seq >= first]
    assert len(checked_kept) >= 3 and len(checked_fresh) >= 3
    assert all((m.header.stamp.sec, m.header.stamp.nanosec) == stamp_of[m.seq] for m in checked_kept)
    # re-stamped: the relay's own time, later than the source's (it also worked 30 ms)
    for m in checked_fresh:
        delta = (m.header.stamp.sec - stamp_of[m.seq][0]) + \
            (m.header.stamp.nanosec - stamp_of[m.seq][1]) * 1e-9
        assert 0.025 <= delta < 1.0, delta
    assert all(m.header.frame_id == 'src7' for m in fresh)  # the path is kept either way


def test_sink_reports_latency_rate_and_loss_per_path(helper, procs):
    stats = helper.collector(SinkStats, '/snk8/stats')
    procs.start('pipeline_source', 'src8a', 'rate_hz:=20.0', remaps=[('out', '/t8/a')])
    procs.start('pipeline_source', 'src8b', 'rate_hz:=10.0', remaps=[('out', '/t8/b')])
    procs.start('pipeline_relay', 'rel8', 'process_ms:=20.0', 'process_mode:=sleep',
                'num_inputs:=2', remaps=[('in', '/t8/a'), ('in_1', '/t8/b'), ('out', '/t8/c')])
    procs.start('pipeline_sink', 'snk8', 'window_s:=4.0', 'stats_period_s:=0.5',
                remaps=[('in', '/t8/c')])
    both = lambda: [s for s in stats if len(s.paths) == 2 and all(p.rate_hz > 3 for p in s.paths)]  # noqa: E731
    wait_for(both, timeout=30)
    time.sleep(5.0)  # a full window
    last = {p.path: p for p in stats[-1].paths}
    assert stats[-1].sink == 'snk8' and stats[-1].window_sec == pytest.approx(4.0)
    assert set(last) == {'src8a', 'src8b'}
    assert last['src8a'].rate_hz == pytest.approx(20.0, rel=0.25)
    assert last['src8b'].rate_hz == pytest.approx(10.0, rel=0.25)
    for path in last.values():
        assert path.latency_ms_p50 >= 20.0 and path.latency_ms_p95 >= path.latency_ms_p50
        assert path.latency_ms_max >= path.latency_ms_p95 and path.latency_ms_mean >= 20.0
        assert path.lost == 0 and path.received > 20


def test_sink_counts_lost_messages_by_sequence_gaps(helper, procs):
    stats = helper.collector(SinkStats, '/snk9/stats')
    procs.start('pipeline_source', 'src9', 'rate_hz:=50.0', remaps=[('out', '/t9/a')])
    procs.start('pipeline_relay', 'rel9', 'drop_ratio:=0.5', 'seed:=3',
                remaps=[('in', '/t9/a'), ('out', '/t9/b')])
    procs.start('pipeline_sink', 'snk9', 'stats_period_s:=0.5', remaps=[('in', '/t9/b')])
    wait_for(lambda: stats and stats[-1].paths and stats[-1].paths[0].received > 100, timeout=30)
    path = stats[-1].paths[0]
    share = path.lost / (path.lost + path.received)
    assert 0.3 <= share <= 0.7, (path.received, path.lost)


def _set_param(node, assignment):
    """`ros2 param set` (output as text), retried while the CLI daemon has not found the node."""
    for _ in range(15):
        done = subprocess.run(['ros2', 'param', 'set', node, *assignment.split(' ', 1)],
                              capture_output=True, text=True, timeout=30)
        if 'Node not found' not in done.stderr:
            break
        time.sleep(1.0)
    return done.stdout + done.stderr


def test_parameters_change_while_running_and_bad_values_are_refused(helper, procs):
    out = helper.collector(Payload, '/t10/b')
    procs.start('pipeline_source', 'src10', 'rate_hz:=10.0', remaps=[('out', '/t10/a')])
    procs.start('pipeline_relay', 'rel10', remaps=[('in', '/t10/a'), ('out', '/t10/b')])
    wait_for(lambda: len(out) >= 3, timeout=20)
    assert len(out[-1].data) == 64
    ok = _set_param('/rel10', 'payload_bytes 777')
    assert 'successful' in ok, ok
    wait_for(lambda: len(out[-1].data) == 777, timeout=10)
    assert 'successful' in _set_param('/src10', 'rate_hz 40.0')
    time.sleep(1.5)
    n = count_after(out, 3.0)
    assert 90 <= n <= 140, n  # 40 Hz now
    assert 'drop_ratio must be between 0 and 1' in _set_param('/rel10', 'drop_ratio 1.5')
    assert 'process_ms must be 0 or more' in _set_param('/rel10', 'process_ms -1.0')
    assert 'rate_hz must be positive' in _set_param('/src10', 'rate_hz 0.0')
    assert 'successful' in _set_param('/src10', 'enabled false')
    time.sleep(1.0)
    assert count_after(out, 2.0) <= 1  # paused
    readonly = _set_param('/rel10', 'num_inputs 3').lower()
    assert 'read-only' in readonly or 'read only' in readonly, readonly


def test_invalid_start_parameters_stop_the_node_with_an_error(procs):
    bad = procs.start('pipeline_relay', 'rel_bad', 'fanout:=random')
    assert wait_for(lambda: bad.poll() is not None, timeout=20) is True
    assert bad.returncode != 0 and b'fanout must be' in bad.stderr.read()


def test_source_count_stops_after_n_messages(helper, procs):
    out = helper.collector(Payload, '/t11/a')
    procs.start('pipeline_source', 'src11', 'rate_hz:=4.0', 'count:=8', remaps=[('out', '/t11/a')])
    wait_for(lambda: out and out[-1].seq == 7, timeout=20)  # the first ones may precede discovery
    time.sleep(2.0)
    assert out[-1].seq == 7 and max(m.seq for m in out) == 7  # nothing after the 8th message


@pytest.mark.parametrize('kind,params,size', [
    ('image', ['width:=64', 'height:=48'], 64 * 48 * 3),
    ('pointcloud', ['points:=1000'], 1000 * 16)])
def test_heavy_source_and_sink_carry_big_messages(helper, procs, kind, params, size):
    """heavy_source / heavy_sink (bench_heavy.py): the right type and size, sink statistics, no loss."""
    from sensor_msgs.msg import Image, PointCloud2
    seen = helper.collector(Image if kind == 'image' else PointCloud2, f'/th_{kind}/a', qos=10)
    stats = helper.collector(SinkStats, f'/th_snk_{kind}/stats')
    procs.start('heavy_source', f'th_src_{kind}', f'kind:={kind}', 'rate_hz:=20.0', 'qos:=reliable',
                *params, remaps=[('out', f'/th_{kind}/a')])
    procs.start('heavy_sink', f'th_snk_{kind}', f'kind:={kind}', 'qos:=reliable',
                remaps=[('in', f'/th_{kind}/a')])
    wait_for(lambda: stats and stats[-1].paths and stats[-1].paths[0].received > 30, timeout=40)
    msg = seen[-1]
    assert len(msg.data) == size and msg.header.frame_id.isdigit()
    if kind == 'image':
        assert (msg.width, msg.height, msg.encoding) == (64, 48, 'rgb8')
    else:
        assert (msg.width, msg.point_step, [f.name for f in msg.fields]) == (1000, 16, ['x', 'y', 'z', 'intensity'])
    path = stats[-1].paths[0]
    assert path.path == 'heavy' and path.lost == 0 and path.rate_hz > 10
    assert 0.0 <= path.latency_ms_p50 < 200.0


def test_heavy_source_rejects_an_unknown_kind(procs):
    bad = procs.start('heavy_source', 'th_bad', 'kind:=video')
    assert wait_for(lambda: bad.poll() is not None, timeout=20) is True
    assert bad.returncode != 0 and b'kind must be' in bad.stderr.read()
