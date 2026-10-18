"""Resource monitoring: pure parts (leak diagnostics, attribution, breakdown, /proc parsers,
disk / UDP diagnostics, GPU degradation, connection events). No ROS, no real processes."""

import os
import socket
import threading
import time
from collections import namedtuple

import pytest

from roshanavi.media.diskguard import DiskGuard, DiskThresholds
from roshanavi.process_map import CONFIDENCE_EXACT, CONFIDENCE_HEURISTIC, NodeMapping
from roshanavi.resources import diagnose
from roshanavi.resources.attribution import (GROUP_OTHER, GROUP_ROS, GROUP_SELF, SelfPids,
                                             attribute)
from roshanavi.resources.connections import (Conn, ConnectionTracker, ReverseDns, collect,
                                             decode_address, parse_table)
from roshanavi.resources.gpu import GpuReader
from roshanavi.resources.host import HostSampler, cpu_percents, volume_device
from roshanavi.resources.procs import (ProcessTable, ProcRow, RawProc, parse_stat, read_cmdline,
                                       read_io, read_procs, read_uss)
from roshanavi.resources.snmp import parse_snmp, read_udp
from roshanavi.resources.summary import breakdown, node_dict


# ---- /proc/net/snmp ----------------------------------------------------------------------------

SNMP = """Ip: Forwarding DefaultTTL InReceives
Ip: 1 64 12345
Udp: InDatagrams NoPorts InErrors OutDatagrams RcvbufErrors SndbufErrors InCsumErrors IgnoredMulti MemErrors
Udp: 1000 3 17 900 15 2 0 4 0
UdpLite: InDatagrams NoPorts InErrors OutDatagrams RcvbufErrors SndbufErrors InCsumErrors IgnoredMulti MemErrors
UdpLite: 0 0 0 0 0 0 0 0 0
"""


def test_parse_snmp_udp_counters():
    udp = parse_snmp(SNMP)
    assert udp['RcvbufErrors'] == 15 and udp['SndbufErrors'] == 2 and udp['InErrors'] == 17
    assert parse_snmp(SNMP, 'UdpLite')['RcvbufErrors'] == 0


@pytest.mark.parametrize('text', ['', 'Udp: InDatagrams NoPorts\n', 'Udp: A B\nUdp: 1\n'])
def test_parse_snmp_malformed_is_empty(text):
    assert parse_snmp(text) == {}


def test_read_udp_from_file_and_missing_file(tmp_path):
    path = tmp_path / 'snmp'
    path.write_text(SNMP)
    assert read_udp(str(path))['RcvbufErrors'] == 15
    assert read_udp(str(tmp_path / 'missing')) is None


# ---- host -------------------------------------------------------------------------------------

CpuT = namedtuple('CpuT', 'user nice system idle iowait irq softirq steal')


def test_cpu_percents_from_time_deltas():
    prev = [CpuT(10, 0, 10, 80, 0, 0, 0, 0), CpuT(0, 0, 0, 100, 0, 0, 0, 0)]
    cur = [CpuT(40, 0, 20, 140, 0, 0, 0, 0), CpuT(0, 0, 0, 200, 0, 0, 0, 0)]
    assert cpu_percents(prev, cur) == [pytest.approx(40.0), 0.0]


Part = namedtuple('Part', 'device mountpoint fstype opts')


def test_volume_device_longest_mount_prefix(tmp_path):
    parts = [Part('/dev/sda1', '/', 'ext4', ''), Part('/dev/sdb2', str(tmp_path), 'ext4', ''),
             Part('tmpfs', str(tmp_path / 'x'), 'tmpfs', '')]
    assert volume_device(str(tmp_path / 'data'), parts) == 'sdb2'
    assert volume_device('/usr', parts) == 'sda1'
    assert volume_device(str(tmp_path / 'x' / 'y'), parts) is None  # not a block device


class FakePs:
    """Minimal psutil stand-in whose counters advance between calls."""

    def __init__(self):
        self.n = 0
        Nic = namedtuple('Nic', 'bytes_sent bytes_recv packets_sent packets_recv errin errout '
                                'dropin dropout')
        self.Nic = Nic

    def cpu_count(self):
        return 2

    def cpu_times(self, percpu=True):
        self.n += 1
        return [CpuT(10 * self.n, 0, 0, 100 * self.n, 0, 0, 0, 0)] * 2

    def virtual_memory(self):
        return namedtuple('VM', 'total available')(8 * 1024 ** 3, 6 * 1024 ** 3)

    def swap_memory(self):
        return namedtuple('SW', 'total used percent')(0, 0, 0.0)

    def disk_partitions(self, all=False):
        return [Part('/dev/sdz1', '/', 'ext4', '')]

    def disk_io_counters(self, perdisk=True):
        IO = namedtuple('IO', 'read_bytes write_bytes')
        return {'sdz1': IO(1000 * self.n, 5000 * self.n)}

    def net_io_counters(self, pernic=True):
        k = self.n
        return {'lo': self.Nic(10 ** 9 * k, 10 ** 9 * k, 1, 1, 0, 0, 0, 0),
                'eth0': self.Nic(100 * k, 300 * k, k, 3 * k, 0, 0, k, 0)}


def test_host_sampler_rates_and_loopback_excluded(tmp_path):
    udp_values = iter([{'RcvbufErrors': 5, 'SndbufErrors': 0}, {'RcvbufErrors': 9,
                                                                'SndbufErrors': 1}])
    guard = DiskGuard(str(tmp_path), usage=lambda _p: (50 * 1024 ** 3, 100 * 1024 ** 3))
    host = HostSampler(str(tmp_path), guard, ps=FakePs(), udp=lambda: next(udp_values))
    first = host.sample(0.0)
    assert first['cpu']['total_pct'] is None and first['nics'][0]['rx_bps'] is None
    second = host.sample(1.0)
    assert [n['name'] for n in second['nics']] == ['eth0']
    assert second['nics'][0]['rx_bps'] == pytest.approx(300.0)
    assert second['nics'][0]['drop_per_sec'] == pytest.approx(1.0)
    assert second['cpu']['total_pct'] == pytest.approx(100 * 10 / 110, abs=0.1)
    assert second['mem']['pct'] == pytest.approx(25.0)
    assert second['disk']['level'] == 'ok' and second['disk']['device'] == 'sdz1'
    assert second['disk']['write_bps'] == pytest.approx(5000.0)
    assert second['udp']['rcvbuf_recent'] == 4 and second['udp']['rcvbuf_per_sec'] == 4.0


# ---- disk / UDP diagnostics -------------------------------------------------------------------

def disk_level(free_mb, total_mb=20_000):
    guard = DiskGuard('/x', DiskThresholds(), usage=lambda _p: (free_mb * 1024 ** 2,
                                                              total_mb * 1024 ** 2))
    return {**guard.check(), 'level': guard.check()['level'], 'path': '/x'}


@pytest.mark.parametrize('free_mb,expected', [(15_000, []), (900, ['warning']),
                                              (200, ['error'])])
def test_disk_diag_uses_the_recording_thresholds(free_mb, expected):
    diags = diagnose.disk_diags(disk_level(free_mb), recording=True)
    assert [d['severity'] for d in diags] == expected
    if diags:
        assert diags[0]['code'] == 'disk_low' and diags[0]['detail']['recording'] is True


def test_disk_diag_percentage_threshold():
    # 2 GB free of 100 GB = 2 % < 5 % -> warn even though more than 1 GB is free
    assert diagnose.disk_diags(disk_level(2_000, 100_000), False)[0]['severity'] == 'warning'


BIG = {'topic': '/camera/image', 'avg_size': 900_000, 'dropped': 12, 'drop_ratio': 0.1}
SMALL = {'topic': '/chatter', 'avg_size': 20, 'dropped': 5, 'drop_ratio': 0.2}


def test_udp_diag_needs_rcvbuf_errors_and_large_drops():
    calls = []

    def traffic():
        calls.append(1)
        return [BIG, SMALL]
    assert diagnose.udp_diags({'rcvbuf_recent': 0}, traffic) == [] and not calls
    diags = diagnose.udp_diags({'rcvbuf_recent': 7, 'recent_sec': 60}, traffic)
    assert diags[0]['code'] == 'udp_rcvbuf' and diags[0]['topic'] == '/camera/image'
    assert [t['topic'] for t in diags[0]['detail']['topics']] == ['/camera/image']


def test_udp_errors_without_large_drops_are_not_a_diagnostic():
    diags = diagnose.udp_diags({'rcvbuf_recent': 3}, lambda: [SMALL, {**BIG, 'dropped': 0,
                                                                     'drop_ratio': 0}])
    assert diags == []  # the counter is shown on the resources tab only


def test_leak_diag_entries():
    suspect = {'suspect': True, 'rate_mb_per_min': 3.2, 'duration_sec': 1200, 'scale_min': 10}
    procs = [{'pid': 5, 'name': 'leaky', 'label': 't', 'group': 'ros', 'nodes': ['/leaky'],
              'rss': 10, 'leak': suspect, 'gpu_leak': None},
             {'pid': 6, 'name': 'ok', 'nodes': [], 'rss': 1, 'leak': {'suspect': False}},
             # growing but levelling off: resources tab only, never a diagnostic
             {'pid': 7, 'name': 'filling', 'nodes': ['/f'], 'rss': 1,
              'leak': {'suspect': False, 'watch': True, 'rate_mb_per_min': 1.0}},
             # roshanavi's own processes are judged like any other
             {'pid': 8, 'name': 'python3', 'label': 'server', 'group': 'self', 'nodes': [],
              'rss': 99, 'leak': {**suspect, 'rate_mb_per_min': 0.4, 'duration_sec': 7200,
                                  'scale_min': 360}}]
    diags = diagnose.leak_diags(procs)
    assert [(d['code'], d['nodes'], d['detail']['rate_mb_per_min']) for d in diags] == [
        ('mem_leak', ['/leaky'], 3.2), ('mem_leak', [], 0.4)]
    assert diags[0]['detail']['duration_sec'] == 1200 and diags[0]['detail']['scale_min'] == 10
    assert diags[1]['detail']['group'] == 'self' and diags[1]['detail']['label'] == 'server'
    assert all(d['severity'] == 'warning' for d in diags)


# ---- attribution -----------------------------------------------------------------------------

def row(pid, ppid, name, cmdline=(), cpu=None, rss=10 * 1024 ** 2):
    return ProcRow(pid=pid, ppid=ppid, name=name, cmdline=tuple(cmdline), create_time=1.0,
                   cpu_seconds=0.0, rss=rss, cpu_pct=cpu)


SERVER = 100
ROS2_RUN = ('/usr/bin/python3', '/opt/ros/jazzy/bin/ros2', 'run')


def table():
    rows = [
        row(1, 0, 'init'),
        row(SERVER, 1, 'ros2', ('/usr/bin/python3', '/opt/ros/jazzy/bin/ros2', 'run',
                                'roshanavi', 'server'), cpu=12.0),
        row(101, SERVER, 'roshanavi_probe', ('/ws/install/lib/roshanavi_probe/probe',), cpu=3.0),
        # target "talk": ros2 run wrapper + the node program (both carry __node)
        row(110, SERVER, 'ros2', (*ROS2_RUN, 'demo_nodes_cpp', 'talker', '--ros-args', '-r',
                                  '__node:=my_talker')),
        row(111, 110, 'talker', ('/opt/ros/jazzy/lib/demo_nodes_cpp/talker', '--ros-args', '-r',
                                 '__node:=my_talker'), cpu=40.0),
        # target "cont": a container with two composable nodes (Launcher heuristic)
        row(120, SERVER, 'component_conta', ('/opt/ros/jazzy/lib/rclcpp_components/'
                                             'component_container',), cpu=20.0),
        # input node made by roshanavi (role dummy)
        row(130, SERVER, 'python3', ('/usr/bin/python3', '-m', 'roshanavi.dummy_node'), cpu=1.0),
        row(140, SERVER, 'colcon', ('/usr/bin/python3', '/usr/bin/colcon', 'build'), cpu=90.0),
        row(150, SERVER, 'ffmpeg', ('ffmpeg', '-i', 'x')),
        # nodes started elsewhere (same user): by __node and by program name
        row(200, 1, 'ros2', (*ROS2_RUN, 'pkg', 'exe', '--ros-args', '-r', '__node:=ext',
                             '-r', '__ns:=/ns')),
        row(201, 200, 'exe', ('/x/lib/pkg/exe', '--ros-args', '-r', '__node:=ext', '-r',
                              '__ns:=/ns'), cpu=5.0),
        row(300, 1, 'listener', ('/opt/ros/jazzy/lib/demo_nodes_cpp/listener',), cpu=2.0),
        row(400, 1, 'firefox', ('/usr/lib/firefox/firefox',), cpu=150.0, rss=900 * 1024 ** 2),
        row(401, 1, 'firefox', ('/usr/lib/firefox/firefox', '-contentproc'), cpu=50.0),
        row(500, 1, 'listener', ('/opt/ros/jazzy/lib/demo_nodes_cpp/listener',)),  # 2nd copy
    ]
    return {r.pid: r for r in rows}


TARGETS = (('talk', 1.0, 110), ('cont', 1.0, 120), ('dummy1', 1.0, 130))
ROLES = {'talk': 'mine', 'cont': 'dependency', 'dummy1': 'dummy'}
LAUNCHER = {
    '/my_talker': NodeMapping('/my_talker', 'talk', 111, CONFIDENCE_EXACT),
    '/comp_a': NodeMapping('/comp_a', 'cont', 120, CONFIDENCE_HEURISTIC),
    '/comp_b': NodeMapping('/comp_b', 'cont', 120, CONFIDENCE_HEURISTIC),
    '/input1': NodeMapping('/input1', 'dummy1', 130, CONFIDENCE_EXACT),
}
NODES = ('/my_talker', '/comp_a', '/comp_b', '/input1', '/ns/ext', '/listener', '/talker',
         '/remote_node')


def attr():
    return attribute(table(), NODES, LAUNCHER, TARGETS, ROLES,
                     SelfPids(server=SERVER, probe=101))


def test_launcher_targets_are_exact_and_take_the_deepest_process():
    a = attr().nodes['/my_talker']
    assert (a.pid, a.confidence, a.source, a.target_id) == (111, CONFIDENCE_EXACT, 'launcher', 'talk')


def test_composable_nodes_share_their_container_process():
    a = attr()
    assert a.nodes['/comp_a'].pid == 120 and a.nodes['/comp_a'].shared == ('/comp_b',)
    assert a.nodes['/comp_a'].confidence == CONFIDENCE_HEURISTIC
    assert a.procs[120].nodes == ('/comp_a', '/comp_b')


def test_other_local_nodes_by_cmdline_are_heuristic_and_skip_the_wrapper():
    a = attr().nodes['/ns/ext']
    assert (a.pid, a.confidence, a.source) == (201, CONFIDENCE_HEURISTIC, 'cmdline')


def test_program_name_match_only_when_unique():
    a = attr()
    assert '/listener' not in a.nodes  # two "listener" processes: ambiguous -> unknown
    assert '/talker' not in a.nodes  # the only "talker" program is already /my_talker's
    assert '/remote_node' not in a.nodes  # another PC / container: never guessed


def test_program_name_match_single_process():
    rows = table()
    del rows[500]
    a = attribute(rows, NODES, LAUNCHER, TARGETS, ROLES, SelfPids(server=SERVER))
    assert (a.nodes['/listener'].pid, a.nodes['/listener'].source) == (300, 'exe')


def test_groups_ros_self_other():
    a = attr()
    groups = {pid: (a.procs[pid].group, a.procs[pid].label) if pid in a.procs else None
              for pid in table()}
    assert groups[SERVER] == (GROUP_SELF, 'server')
    assert groups[101] == (GROUP_SELF, 'probe')
    assert groups[110] == (GROUP_ROS, 'talk') and groups[111] == (GROUP_ROS, 'talk')
    assert groups[120] == (GROUP_ROS, 'cont')
    assert groups[130] == (GROUP_SELF, 'child_nodes')  # roshanavi-made input node
    assert groups[140] == (GROUP_SELF, 'build')
    assert groups[150] == (GROUP_SELF, 'helper')
    assert groups[201][0] == GROUP_ROS  # hosts /ns/ext
    assert groups[400] is None and a.group_of(400) == GROUP_OTHER
    assert a.procs[130].role == 'dummy' and a.procs[130].nodes == ('/input1',)


def test_cmdline_identity_beats_the_launcher_timing_guess():
    # /ns/ext appeared right after target "talk" started, so the Launcher guessed "talk";
    # its own argv says otherwise.
    launcher = {**LAUNCHER, '/ns/ext': NodeMapping('/ns/ext', 'talk', 111, CONFIDENCE_HEURISTIC)}
    a = attribute(table(), NODES, launcher, TARGETS, ROLES, SelfPids(server=SERVER))
    assert (a.nodes['/ns/ext'].pid, a.nodes['/ns/ext'].source) == (201, 'cmdline')
    assert a.nodes['/my_talker'].pid == 111 and a.nodes['/my_talker'].shared == ()


def test_the_ros2_run_wrapper_of_the_server_is_roshanavi_itself():
    rows = {**table(), SERVER: row(SERVER, 90, 'python3', ('/usr/bin/python3', '-m', 'x')),
            90: row(90, 1, 'ros2', ('/usr/bin/python3', '/opt/ros/jazzy/bin/ros2', 'run',
                                    'roshanavi', 'server'))}
    a = attribute(rows, (), {}, (), {}, SelfPids(server=SERVER))
    assert a.procs[90].label == 'server' and a.group_of(1) == GROUP_OTHER


def test_launcher_mapping_without_pid_uses_the_whole_target_tree():
    launcher = {**LAUNCHER, '/guessed': NodeMapping('/guessed', 'talk', None, CONFIDENCE_HEURISTIC)}
    a = attribute(table(), (*NODES, '/guessed'), launcher, TARGETS, ROLES, SelfPids(server=SERVER))
    assert a.nodes['/guessed'].pids == (110, 111) and a.nodes['/guessed'].pid is None
    assert a.nodes['/guessed'].source == 'launcher'


def test_lttng_daemons_count_as_self_only_when_named():
    rows = {**table(), 600: row(600, 1, 'lttng-sessiond', ('lttng-sessiond',))}
    off = attribute(rows, (), {}, (), {}, SelfPids(server=SERVER))
    on = attribute(rows, (), {}, (), {}, SelfPids(server=SERVER, lttng_names=('lttng-sessiond',)))
    assert off.group_of(600) == GROUP_OTHER and on.procs[600].label == 'lttng'


# ---- breakdown / node figures ------------------------------------------------------------------

def test_breakdown_splits_the_machine_into_ros_self_other_with_top_names():
    rows, a = table(), attr()
    out = breakdown(rows, a, ncpu=4, host_cpu_pct=100.0, mem_used=4 * 1024 ** 3, top_n=2)
    ros = (40 + 20 + 5) / 4  # talker, container, ext
    own = (12 + 3 + 1 + 90) / 4
    assert out['cpu']['ros'] == pytest.approx(ros) and out['cpu']['self'] == pytest.approx(own)
    assert out['cpu']['other'] == pytest.approx(100 - ros - own)
    assert out['cpu']['other_top'][0] == {'name': 'firefox', 'cpu_norm_pct': 50.0,
                                          'rss': 910 * 1024 ** 2, 'count': 2}
    assert out['mem']['other_top'][0]['name'] == 'firefox'
    assert out['counts'][GROUP_OTHER] == 5


def test_breakdown_other_never_negative_and_unknown_total():
    out = breakdown(table(), attr(), ncpu=4, host_cpu_pct=1.0, mem_used=None)
    assert out['cpu']['other'] == 0.0 and out['mem']['other'] is None


def test_node_dict_sums_a_target_tree_and_reports_scope():
    a = attribute(table(), ('/guessed',), {'/guessed': NodeMapping('/guessed', 'talk', None, 'heuristic')},
                  TARGETS, ROLES, SelfPids(server=SERVER))
    procs = {110: {'cpu_pct': 1.0, 'cpu_norm_pct': 0.25, 'rss': 5, 'uss': None, 'threads': 2,
                   'fds': 3, 'read_bps': 0, 'write_bps': 0, 'connections': [], 'name': 'ros2'},
             111: {'cpu_pct': 40.0, 'cpu_norm_pct': 10.0, 'rss': 7, 'uss': 4, 'threads': 5,
                   'fds': 9, 'read_bps': 10, 'write_bps': 0, 'connections': [{}], 'name': 'talker'}}
    out = node_dict(a.nodes['/guessed'], procs)
    assert out['scope'] == 'target' and out['cpu_pct'] == 41.0 and out['rss'] == 12
    assert out['uss'] == 4 and out['connections'] == 1 and out['leak'] is None


# ---- process table ------------------------------------------------------------------------------

def test_process_table_cpu_from_deltas_and_user_filter():
    state = {'cpu': 1.0}
    seen_uid = []

    def reader(uid):
        seen_uid.append(uid)
        yield RawProc(10, 1, 'a', state['cpu'], 4, 3.0, 5)
        if uid is None:
            yield RawProc(11, 1, 'b', 9.0, 1, 3.0, 5)
    tbl = ProcessTable(own_uid=1000, see_all=False, reader=reader, cmdline=lambda pid: ('a',))
    first = tbl.scan(100.0)
    assert list(first) == [10] and first[10].cpu_pct is None and first[10].threads == 4
    state['cpu'] = 1.5
    second = tbl.scan(101.0)
    assert second[10].cpu_pct == pytest.approx(50.0) and seen_uid == [1000, 1000]
    everyone = ProcessTable(own_uid=1000, see_all=True, reader=reader, cmdline=lambda pid: ())
    assert list(everyone.scan(0.0)) == [10, 11]


STAT = ('4242 (my (odd) node) S 1 4242 4242 0 -1 4194560 100 0 0 0 250 50 0 0 20 0 7 0 '
        '1000 123456789 2048 18446744073709551615 0 0 0 0 0 0 0 0 0 0 0 0 17 3 0 0 0 0 0')


def test_parse_stat_handles_names_with_spaces_and_parens():
    raw = parse_stat(4242, STAT, boot_time=1000.0)
    tck = os.sysconf('SC_CLK_TCK')
    assert raw.comm == 'my (odd) node' and raw.ppid == 1 and raw.threads == 7
    assert raw.cpu_seconds == pytest.approx(300 / tck)
    assert raw.create_time == pytest.approx(1000.0 + 1000 / tck)
    assert raw.rss == 2048 * os.sysconf('SC_PAGE_SIZE')
    assert parse_stat(1, 'garbage', 0.0) is None


def test_read_procs_io_uss_cmdline_from_a_fake_proc(tmp_path):
    proc = tmp_path / '4242'
    proc.mkdir()
    (proc / 'stat').write_text(STAT)
    (proc / 'cmdline').write_bytes(b'/opt/ros/jazzy/lib/rclcpp_components/component_container\0'
                                   b'--ros-args\0')
    (proc / 'io').write_text('rchar: 1\nwchar: 2\nread_bytes: 4096\nwrite_bytes: 8192\n')
    (proc / 'smaps_rollup').write_text('Rss: 100 kB\nPrivate_Clean: 10 kB\nPrivate_Dirty: 30 kB\n')
    (tmp_path / 'self').mkdir()
    (tmp_path / 'net').mkdir()
    raws = list(read_procs(str(tmp_path), boot_time=0.0))
    assert [r.pid for r in raws] == [4242]
    assert read_cmdline(4242, str(tmp_path))[1] == '--ros-args'
    assert read_io(4242, str(tmp_path)) == (4096, 8192) and read_io(1, str(tmp_path)) is None
    assert read_uss(4242, str(tmp_path)) == 40 * 1024
    table = ProcessTable(see_all=True, root=str(tmp_path),
                         reader=lambda uid: read_procs(str(tmp_path), uid, 0.0))
    rows = table.scan(0.0)
    assert rows[4242].name == 'my (odd) node'
    (proc / 'io').write_text('read_bytes: 6144\nwrite_bytes: 8192\n')
    detailed = table.detail(table.scan(2.0)[4242], 2.0)
    assert detailed.uss == 40 * 1024


@pytest.mark.parametrize('comm,cmdline,expected', [
    ('python3', ('/usr/bin/python3', '/x/lib/pkg/executor_busy_demo', '--ros-args'),
     'executor_busy_demo'),
    ('python3', ('python3', '-m', 'roshanavi.dummy_node'), 'roshanavi.dummy_node'),
    ('python3', ('python3', '-c', 'print(1)'), 'python3'),
    ('talker', ('/opt/ros/jazzy/lib/demo_nodes_cpp/talker',), 'talker')])
def test_display_name_of_scripts(comm, cmdline, expected):
    table = ProcessTable(see_all=True, reader=lambda uid: iter([RawProc(5, 1, comm, 0.0, 1, 0.0, 0)]),
                         cmdline=lambda pid: cmdline)
    assert table.scan(0.0)[5].name == expected


def test_display_name_untruncates_long_program_names():
    raw = RawProc(5, 1, 'component_conta', 0.0, 1, 0.0, 0)
    table = ProcessTable(see_all=True, reader=lambda uid: iter([raw]),
                         cmdline=lambda pid: ('/opt/ros/jazzy/lib/rclcpp_components/'
                                              'component_container',))
    assert table.scan(0.0)[5].name == 'component_container'


def test_process_table_io_rate(tmp_path):
    proc = tmp_path / '7'
    proc.mkdir()
    (proc / 'io').write_text('read_bytes: 0\nwrite_bytes: 0\n')
    raw = RawProc(7, 1, 'w', 0.0, 1, 5.0, 0)
    table = ProcessTable(see_all=True, root=str(tmp_path), reader=lambda uid: iter([raw]),
                         cmdline=lambda pid: ())
    table.detail(table.scan(0.0)[7], 0.0)
    (proc / 'io').write_text('read_bytes: 1000\nwrite_bytes: 4000\n')
    row = table.detail(table.scan(2.0)[7], 2.0)
    assert (row.read_bps, row.write_bps) == (500.0, 2000.0) and row.uss is None


# ---- connections --------------------------------------------------------------------------------

TCP = """  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 0100007F:1F90 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000        0 111 1 0 100 0 0 10 0
   1: 0F02000A:C350 22D8B85D:01BB 01 00000000:00000000 00:00000000 00000000  1000        0 222 1 0 20 4 30 10 -1
"""
UDP = """  sl  local_address rem_address   st tx_queue rx_queue ref pointer drops
  10: 00000000:1CE8 00000000:0000 07 00000000:00000000 00:00000000 00000000  1000        0 333 2 0 0
  11: 0F02000A:D431 0101A8C0:0035 01 00000000:00000000 00:00000000 00000000  1000        0 444 2 0 0
"""
TCP6 = """  sl  local_address                         remote_address                        st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 00000000000000000000000001000000:9C40 00000000000000000000000001000000:1F90 01 00000000:00000000 00:00000000 00000000  1000        0 555 1 0 20 4 30 10 -1
"""


def test_decode_addresses():
    assert decode_address('0100007F:1F90', socket.AF_INET) == ('127.0.0.1', 8080)
    assert decode_address('22D8B85D:01BB', socket.AF_INET) == ('93.184.216.34', 443)
    assert decode_address('00000000000000000000000001000000:1F90', socket.AF_INET6) == ('::1', 8080)


def test_parse_tables_states_and_unconnected():
    tcp = parse_table(TCP, 'tcp', socket.AF_INET)
    assert [(e.inode, e.status, e.raddr) for e in tcp] == [
        (111, 'LISTEN', None), (222, 'ESTABLISHED', ('93.184.216.34', 443))]
    udp = parse_table(UDP, 'udp', socket.AF_INET)
    assert [(e.inode, e.status, e.raddr) for e in udp] == [
        (333, 'NONE', None), (444, 'CONNECTED', ('192.168.1.1', 53))]


def fake_proc_root(tmp_path, pid=4242, inodes=(111, 222, 333, 444, 555, 999)):
    (tmp_path / 'net').mkdir()
    (tmp_path / 'net' / 'tcp').write_text(TCP)
    (tmp_path / 'net' / 'udp').write_text(UDP)
    (tmp_path / 'net' / 'tcp6').write_text(TCP6)
    fd_dir = tmp_path / str(pid) / 'fd'
    fd_dir.mkdir(parents=True)
    for i, inode in enumerate(inodes):
        os.symlink(f'socket:[{inode}]', fd_dir / str(i + 3))
    os.symlink('/dev/null', fd_dir / '0')
    return str(tmp_path)


def test_collect_joins_fds_with_socket_tables(tmp_path):
    root = fake_proc_root(tmp_path)
    out = collect([4242, 777], root)
    assert list(out) == [4242]  # 777: no such process
    socks = out[4242]
    assert socks.fds == 7 and socks.listening == 1 and socks.udp_open == 1
    assert sorted((c.proto, c.raddr) for c in socks.conns) == [
        ('tcp', ('93.184.216.34', 443)), ('tcp', ('::1', 8080)), ('udp', ('192.168.1.1', 53))]


def test_socket_collector_rereads_tables_only_when_sockets_change(tmp_path, monkeypatch):
    from roshanavi.resources import connections
    root = fake_proc_root(tmp_path)
    reads = []
    real = connections.read_tables
    monkeypatch.setattr(connections, 'read_tables', lambda r: reads.append(1) or real(r))
    collector = connections.SocketCollector(root, refresh_sec=5.0)
    assert len(collector.collect([4242], 0.0)[4242].conns) == 3 and len(reads) == 1
    collector.collect([4242], 1.0)
    assert len(reads) == 1  # same sockets: cached tables
    os.unlink(os.path.join(root, '4242', 'fd', '4'))  # inode 222 closed
    out = collector.collect([4242], 2.0)
    assert len(reads) == 2 and len(out[4242].conns) == 2 and out[4242].fds == 6
    collector.collect([4242], 7.5)
    assert len(reads) == 3  # periodic refresh (TCP state changes)


def test_socket_collector_reads_fd_links_only_when_the_fds_change(tmp_path, monkeypatch):
    from roshanavi.resources import connections
    root = fake_proc_root(tmp_path)
    links = []
    real = connections.socket_inodes
    monkeypatch.setattr(connections, 'socket_inodes', lambda pid, r: links.append(pid) or real(pid, r))
    collector = connections.SocketCollector(root, refresh_sec=5.0)
    collector.collect([4242], 0.0)
    collector.collect([4242], 1.0)
    assert links == [4242]  # same fd numbers: cached inodes
    os.symlink('socket:[444]', os.path.join(root, '4242', 'fd', '20'))
    assert collector.collect([4242], 2.0)[4242].fds == 8 and links == [4242, 4242]
    collector.collect([4242], 7.1)
    assert links == [4242, 4242, 4242]  # periodic refresh
    assert collector.collect([999], 8.0) == {}


def conn(raddr, pid=1):
    return Conn(pid, 'tcp', ('10.0.0.2', 5000), raddr, 'ESTABLISHED')


def test_tracker_emits_open_and_close_after_the_first_sample():
    tracker = ConnectionTracker()
    label = lambda pid: {'label': f'p{pid}', 'nodes': ['/n']}  # noqa: E731
    assert tracker.update([conn(('1.1.1.1', 443))], 1.0, label) == []  # baseline
    events = tracker.update([conn(('1.1.1.1', 443)), conn(('8.8.8.8', 53))], 2.0, label)
    assert [(e['kind'], e['raddr'], e['label']) for e in events] == [('open', '8.8.8.8:53', 'p1')]
    events = tracker.update([conn(('8.8.8.8', 53))], 3.0, label)
    assert [(e['kind'], e['raddr']) for e in events] == [('close', '1.1.1.1:443')]
    assert [e['seq'] for e in tracker.events] == [1, 2] and 'payload' not in tracker.events[0]


def test_reverse_dns_is_cached_and_never_blocks():
    gate = threading.Event()
    calls = []

    def resolve(ip):
        calls.append(ip)
        gate.wait(5)
        if ip == '8.8.8.8':
            return 'dns.google'
        raise socket.herror('unknown')
    rdns = ReverseDns(resolve=resolve, workers=1)
    started = time.monotonic()
    assert rdns.name('8.8.8.8') is None  # queued; returns immediately
    assert time.monotonic() - started < 0.5
    assert rdns.name('127.0.0.1') == 'localhost' and '127.0.0.1' not in calls
    rdns.name('10.9.9.9')
    gate.set()
    deadline = time.monotonic() + 5
    while rdns.name('8.8.8.8') is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert rdns.name('8.8.8.8') == 'dns.google'
    while len(calls) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    time.sleep(0.05)
    assert rdns.name('10.9.9.9') is None and calls.count('8.8.8.8') == 1  # negative cache
    rdns.close()


def test_reverse_dns_disabled():
    rdns = ReverseDns(resolve=lambda ip: 'x', enabled=False)
    assert rdns.name('8.8.8.8') is None and rdns.name('::1') == 'localhost'


# ---- GPU ----------------------------------------------------------------------------------------

def test_gpu_without_pynvml_degrades():
    def loader():
        raise ImportError('No module named pynvml')
    reader = GpuReader(loader=loader, wsl=True)
    out = reader.read()
    assert out == {'available': False, 'reason': 'not_installed', 'wsl': True, 'devices': [],
                   'procs': {}, 'per_process': False}


def test_gpu_init_failure_degrades():
    class Broken:
        def nvmlInit(self):
            raise RuntimeError('NVML Shared Library Not Found')
    assert GpuReader(loader=lambda: Broken(), wsl=False).read()['reason'] == 'no_driver'


class FakeNvml:
    NVML_TEMPERATURE_GPU = 0
    procs = [namedtuple('P', 'pid usedGpuMemory')(4242, 300 * 1024 ** 2)]

    def nvmlInit(self):
        pass

    def nvmlShutdown(self):
        pass

    def nvmlDeviceGetCount(self):
        return 1

    def nvmlDeviceGetHandleByIndex(self, i):
        return f'h{i}'

    def nvmlDeviceGetName(self, h):
        return b'Fake GPU'

    def nvmlDeviceGetUtilizationRates(self, h):
        return namedtuple('U', 'gpu memory')(37, 10)

    def nvmlDeviceGetMemoryInfo(self, h):
        return namedtuple('M', 'total used free')(16 * 1024 ** 3, 2 * 1024 ** 3, 14 * 1024 ** 3)

    def nvmlDeviceGetTemperature(self, h, sensor):
        return 55

    def nvmlDeviceGetComputeRunningProcesses(self, h):
        return self.procs

    def nvmlDeviceGetGraphicsRunningProcesses(self, h):
        raise RuntimeError('Not Supported')


def test_gpu_reads_devices_and_per_process_memory():
    out = GpuReader(loader=lambda: FakeNvml(), wsl=False).read()
    assert out['available'] and out['per_process']
    assert out['devices'][0] == {'index': 0, 'name': 'Fake GPU', 'util_pct': 37,
                                 'mem_used': 2 * 1024 ** 3, 'mem_total': 16 * 1024 ** 3,
                                 'temp_c': 55}
    assert out['procs'] == {4242: 300 * 1024 ** 2}


def test_gpu_without_per_process_list_wsl2():
    class Wsl(FakeNvml):
        procs = []
    out = GpuReader(loader=lambda: Wsl(), wsl=True).read()
    assert out['available'] and not out['per_process'] and out['wsl']
