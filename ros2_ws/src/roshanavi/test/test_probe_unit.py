"""Probe path without a running probe: message conversion, per-node split, process manager."""

import math
from types import SimpleNamespace

import pytest

from roshanavi.graph import Endpoint, RawGraph, build_snapshot, topic_is_live
from roshanavi.probe_process import ProbeProcess
from roshanavi.probe_traffic import gid_resolution, topic_stats_to_dict
from roshanavi.rates import KnownRate, annotate_traffic, measured_rates
from roshanavi.traffic_backend import TrafficService

QOS = {'reliability': 'reliable', 'durability': 'volatile', 'deadline_ms': None,
       'liveliness': 'automatic', 'lease_ms': None}


def stamp(sec=0, nanosec=0):
    return SimpleNamespace(sec=sec, nanosec=nanosec)


def endpoint_msg(gid, name, ns='/', hz=5.0, resolved=True):
    return SimpleNamespace(publisher_gid=bytes([gid] * 16), resolved=resolved, node_name=name,
                           node_namespace=ns, count=25, bytes=2500, hz=hz, bps=hz * 100,
                           dropped=-1, stale=False, rate_note='',
                           first_source_stamp=stamp(10), last_source_stamp=stamp(15, 5))


def topic_msg(**over):
    base = dict(topic='/t', type='std_msgs/msg/String', status='ok', error='', window_sec=5.0,
                rate_window_sec=5.0, rate_note='', stale=False, hz_basis='source', hz=7.0,
                hz_recv=6.9, hz_source=7.0, bytes_per_sec=700.0, avg_size=100.0, jitter_ms=1.0,
                jitter_recv_ms=2.0, dropped=0, drop_ratio=0.0, latency_ms=math.nan,
                total_count=100, recent_count=7, last_seen=stamp(1700000000, 500000000),
                endpoints=[endpoint_msg(1, 'a', hz=5.0), endpoint_msg(2, 'b', '/ns', hz=2.0)])
    base.update(over)
    return SimpleNamespace(**base)


def test_topic_stats_conversion_maps_nan_and_minus_one_to_none():
    d = topic_stats_to_dict(topic_msg(hz_source=math.nan, dropped=-1, rate_note='extended'))
    assert d['hz_source'] is None and d['dropped'] is None and d['latency_ms'] is None
    assert d['rate_note'] == 'extended' and d['error'] is None
    assert d['last_seen'] == pytest.approx(1700000000.5)
    ep = d['endpoints'][1]
    assert ep['node'] == '/ns/b' and ep['gid'] == '02' * 16 and ep['dropped'] is None
    assert ep['last_source_stamp'] == pytest.approx(15.000000005)


def test_never_seen_topic_has_no_last_seen():
    assert topic_stats_to_dict(topic_msg(last_seen=stamp()))['last_seen'] is None


def test_gid_resolution_reports_unmatched_rmw():
    matched = topic_stats_to_dict(topic_msg())
    unmatched = topic_stats_to_dict(topic_msg(endpoints=[endpoint_msg(1, '', resolved=False)]))
    assert gid_resolution([matched]) == 'matched'
    assert gid_resolution([unmatched]) == 'unmatched'
    assert gid_resolution([]) == 'unknown'


def probe_entry(endpoints):
    return {'topic': '/t', 'type': 'std_msgs/msg/String', 'status': 'ok', 'monitored': True,
            'measurement': 'probe', 'hz': 7.0, 'bytes_per_sec': 700.0, 'endpoints': endpoints}


def ep(node, hz, resolved=True):
    return {'node': node if resolved else None, 'resolved': resolved, 'hz': hz, 'bps': hz * 100}


def edges(*nodes, sub=('/listener',)):
    out = [{'node': n, 'topic': '/t', 'dir': 'pub', 'qos': QOS} for n in nodes]
    return out + [{'node': n, 'topic': '/t', 'dir': 'sub', 'qos': QOS} for n in sub]


def test_two_publishers_are_measured_per_node():
    entry = probe_entry([ep('/a', 5.0), ep('/ns/b', 2.0)])
    [out] = annotate_traffic([entry], edges('/a', '/ns/b'), {})
    pubs = {p['node']: p for p in out['publishers']}
    assert pubs['/a'] == {'node': '/a', 'hz': 5.0, 'bps': 500.0, 'basis': 'measured'}
    assert pubs['/ns/b']['hz'] == 2.0 and pubs['/ns/b']['basis'] == 'measured'
    assert out['subscribers'][0]['hz'] == 7.0  # sum of the measured publishers


def test_silent_publisher_is_measured_zero_and_job_keeps_exact():
    entry = probe_entry([ep('/a', 5.0), ep('/roshanavi', 9.0)])
    known = {'dummy:j1': KnownRate(10.0, 1000.0)}
    [out] = annotate_traffic([entry], edges('/a', '/quiet', 'dummy:j1'), known)
    pubs = {p['node']: p for p in out['publishers']}
    assert pubs['/quiet'] == {'node': '/quiet', 'hz': 0.0, 'bps': 0.0, 'basis': 'measured'}
    assert pubs['dummy:j1']['basis'] == 'exact' and pubs['dummy:j1']['hz'] == 10.0


def test_uncounted_job_takes_our_own_measured_rate():
    entry = probe_entry([ep('/roshanavi', 9.0)])
    [out] = annotate_traffic([entry], edges('dummy:j1'), {})
    assert out['publishers'][0] == {'node': 'dummy:j1', 'hz': 9.0, 'bps': 900.0,
                                    'basis': 'measured'}


def test_unmatched_gids_fall_back_to_topic_split():
    entry = probe_entry([ep('', 5.0, resolved=False), ep('', 2.0, resolved=False)])
    assert measured_rates(entry) is None
    [out] = annotate_traffic([entry], edges('/a', '/b'), {})
    assert {p['basis'] for p in out['publishers']} == {'unknown'}
    assert out['subscribers'][0]['hz'] == 7.0  # topic total


def test_python_entries_are_not_measured_per_node():
    entry = {**probe_entry([ep('/a', 5.0)]), 'measurement': 'python'}
    assert measured_rates(entry) is None


def test_probe_topics_are_hidden_from_the_map():
    raw = RawGraph(nodes=[('roshanavi_probe', '/'), ('roshanavi', '/')],
                   topics={'/roshanavi/_probe/stats': ['roshanavi_msgs/msg/ProbeStats'],
                           '/roshanavi/_probe/config': ['roshanavi_msgs/msg/ProbeConfig']},
                   publishers={'/roshanavi/_probe/stats': [Endpoint('/roshanavi_probe', QOS)],
                               '/roshanavi/_probe/config': [Endpoint('/roshanavi', QOS)]},
                   subscribers={'/roshanavi/_probe/config': [Endpoint('/roshanavi_probe', QOS)]})
    assert not topic_is_live(raw, '/roshanavi/_probe/stats')
    snap = build_snapshot(raw)
    assert snap['topics'] == [] and snap['nodes'] == [] and snap['diagnostics'] == []


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_process_restarts_with_backoff_then_gives_up():
    clock = FakeClock()
    proc = ProbeProcess('/bin/false', 'x', clock=clock, backoff=(1.0, 2.0), give_up_after=3)
    proc.start()
    proc._proc.wait(timeout=5)
    proc.poll()
    assert proc.state == 'restarting' and proc.last_exit == 1
    clock.now = 1.0
    proc.poll()  # restarts
    assert proc.restarts == 1
    proc._proc.wait(timeout=5)
    proc.poll()
    clock.now = 2.5
    proc.poll()  # back-off is 2 s now: not yet
    assert proc.restarts == 1
    clock.now = 3.0
    proc.poll()
    proc._proc.wait(timeout=5)
    proc.poll()
    assert proc.gave_up and proc.state == 'failed'


def test_healthy_probe_resets_the_crash_count_only_after_a_while():
    clock = FakeClock()
    proc = ProbeProcess('/bin/false', 'x', clock=clock, backoff=(1.0,), give_up_after=2)
    proc.start()
    proc._proc.wait(timeout=5)
    proc.poll()
    proc.mark_healthy()  # stats right after start do not count
    assert proc._crashes == 1
    clock.now = 31.0
    proc.mark_healthy()  # up (since t=0) for longer than HEALTHY_AFTER_SEC
    proc.poll()
    proc._proc.wait(timeout=5)
    proc.poll()
    assert not proc.gave_up


def test_hung_probe_is_killed_and_restarted(tmp_path):
    script = tmp_path / 'hang'
    script.write_text('#!/bin/sh\nexec sleep 30\n')
    script.chmod(0o755)
    clock = FakeClock()
    proc = ProbeProcess(str(script), 'x', clock=clock, backoff=(1.0,))
    proc.start()
    clock.now = 20.0
    assert proc.uptime() == 20.0
    proc.restart_hung()
    proc._proc.wait(timeout=5)
    proc.poll()
    assert proc.state == 'restarting' and proc.last_exit == -9
    proc.stop()


def test_missing_executable_counts_as_a_crash():
    proc = ProbeProcess('/nonexistent/probe', 'x', clock=FakeClock())
    proc.start()
    assert proc.state == 'restarting' and proc.last_exit == -1


class FakeRuntime:
    def create_subscription(self, *args, **kwargs):
        return object()

    def destroy_subscription(self, sub):
        pass


@pytest.mark.parametrize('mode,find,reason', [('auto', lambda: None, 'not_built'),
                                              ('off', lambda: '/x/probe', 'disabled')])
def test_service_falls_back_to_python(mode, find, reason):
    service = TrafficService(FakeRuntime(), probe=mode, find_executable=find)
    service.start()
    status = service.status()
    assert status['mode'] == 'python' and status['reason'] == reason
    service.sync(RawGraph(topics={'/c': ['std_msgs/msg/String']},
                          publishers={'/c': [Endpoint('/p', QOS)]}))
    assert service.snapshot()[0]['measurement'] == 'python'


def test_service_rejects_unknown_mode():
    with pytest.raises(ValueError):
        TrafficService(FakeRuntime(), probe='maybe')
