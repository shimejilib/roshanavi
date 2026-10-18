#!/usr/bin/env python3
"""How heavy a topic can roshanavi monitor (docs/design/measurement.md, 「重いデータの計測の限界」).

Runs inside the test image (needs the built workspace), like bench_pipeline.py:

    docker compose --profile test run --rm -v "$PWD/scripts:/scripts:ro" -v "$PWD/bench:/bench" test \
        python3 /scripts/bench_heavy.py --out /bench/heavy.json
    python3 scripts/bench_heavy.py --report bench/heavy.json          # markdown table (no ROS)

Image / PointCloud2 streams (heavy_source -> heavy_sink, C++) run next to a real roshanavi server.
Series: M = 1 KB messages at growing rate, R = 1 MB at growing rate, S = 30 Hz at growing size,
C = real-world checkpoints (1080p / 4K camera, 1M-point cloud, 2 and 4 streams). Run it once with
--transport shm (Fast DDS shared memory with a 256 MB segment) and once with --transport udp
(UDPv4 only); the report fits probe CPU = a * msgs/s + b * MB/s + c per transport. Heavy types are not monitored by default; each stream is measured twice:

  OFF  monitoring not enabled: the pair alone (plus the idle probe)
  ON   monitoring enabled with PUT /api/traffic/<topic>/monitor: the probe subscribes too

and the table shows what monitoring costs (probe CPU / RSS, server CPU, the Hz and drop ratio the
probe reports against the true rate) and the OBSERVER EFFECT on the pair (latency p50 / p95 and
sequence gaps at the real subscriber, OFF vs ON). Within a series the points
grow; without --keep-going a series stops at the first one that breaks: the subscriber loses > 5% or gets < 90% of the rate,
the latency p50 doubles, the probe reports < 90% of the true rate, or the probe uses a full core.
The transport is checked as UDP datagrams per second and /dev/shm usage during the measurement
(Fast DDS uses shared memory between processes of one host when /dev/shm is big enough).
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
from typing import Any, Dict, List, Optional

try:
    import psutil
except ImportError:  # --report works without it
    psutil = None

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

MB = 1_000_000
BREAK_LOSS = 0.05
BREAK_RATE = 0.90
BREAK_LATENCY_X = 2.0
BREAK_PROBE_CPU = 95.0


def payload(nbytes: int, hz: float) -> Dict[str, Any]:
    """A plain sensor_msgs/Image of about ``nbytes`` of data (1 row), so size and rate are free axes."""
    width = max(1, nbytes // 3)
    return {'kind': 'image', 'width': width, 'height': 1, 'rate_hz': hz, 'streams': 1,
            'bytes': width * 3, 'name': f'{human(nbytes)}'}


def human(nbytes: int) -> str:
    if nbytes >= 1_000_000:
        return f'{nbytes / 1_000_000:g} MB'
    return f'{nbytes / 1000:g} KB'


def image(width: int, height: int, hz: float, streams: int = 1) -> Dict[str, Any]:
    return {'kind': 'image', 'width': width, 'height': height, 'rate_hz': hz, 'streams': streams,
            'bytes': width * height * 3, 'name': f'Image {width}x{height}'}


def cloud(points: int, hz: float) -> Dict[str, Any]:
    return {'kind': 'pointcloud', 'points': points, 'rate_hz': hz, 'streams': 1,
            'bytes': points * 16, 'name': f'PointCloud2 {points // 1000}k points'}


# R: fixed size, growing message count.  S: fixed rate, growing size.  M: tiny messages, growing
# count (separates the per-message cost).  C: real-world checkpoints.
FAMILIES = {
    'R': [payload(1_000_000, hz) for hz in (10, 30, 100, 300, 1000)],
    'S': [payload(n, 30) for n in (1_000, 100_000, 1_000_000, 6_000_000, 24_000_000)],
    'M': [payload(1_000, hz) for hz in (100, 300, 1000, 3000)],
    'C': [image(1920, 1080, 30), cloud(1_000_000, 10), image(1920, 1080, 30, 2),
          image(1920, 1080, 30, 4), image(3840, 2160, 30)],
}


def rate_mb(config: Dict[str, Any]) -> float:
    return config['bytes'] * config['rate_hz'] * config['streams'] / MB


def msgs_per_s(config: Dict[str, Any]) -> float:
    return config['rate_hz'] * config['streams']


def label(config: Dict[str, Any]) -> str:
    n = f" × {config['streams']} 本" if config['streams'] > 1 else ''
    return f"{config['name']} × {config['rate_hz']:g} Hz{n}"


def exe(name: str) -> str:
    from ament_index_python.packages import get_package_prefix
    return os.path.join(get_package_prefix('roshanavi_examples'), 'lib', 'roshanavi_examples', name)


def udp_datagrams() -> int:
    with open('/proc/net/snmp', encoding='utf-8') as fh:
        lines = [ln.split() for ln in fh if ln.startswith('Udp:')]
    head, values = lines[0], lines[1]
    return int(values[head.index('InDatagrams')]) + int(values[head.index('OutDatagrams')])


def shm_bytes() -> int:
    total = 0
    for name in os.listdir('/dev/shm'):
        try:
            total += os.stat(os.path.join('/dev/shm', name)).st_size
        except OSError:
            continue
    return total


class Meter(threading.Thread):
    """CPU seconds and peak RSS per named process group, sampled twice a second."""

    def __init__(self, groups: Dict[str, Any]):
        super().__init__(daemon=True)
        self.groups = groups  # name -> callable returning a list of psutil.Process
        self.stop_flag = threading.Event()
        self.lock = threading.Lock()
        self.last: Dict[int, float] = {}
        self.cpu: Dict[str, float] = {}
        self.rss_peak: Dict[str, int] = {}
        self.started = time.monotonic()

    def run(self) -> None:
        while not self.stop_flag.wait(0.5):
            for name, find in self.groups.items():
                rss = 0
                for proc in find():
                    try:
                        times = proc.cpu_times()
                        used = times.user + times.system
                        rss += proc.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                    with self.lock:
                        self.cpu[name] = self.cpu.get(name, 0.0) + max(0.0, used - self.last.get(proc.pid, used))
                        self.last[proc.pid] = used
                with self.lock:
                    self.rss_peak[name] = max(self.rss_peak.get(name, 0), rss)

    def reset(self) -> None:
        with self.lock:
            self.cpu = {}
            self.rss_peak = {}
            self.started = time.monotonic()

    def result(self) -> Dict[str, Any]:
        with self.lock:
            elapsed = max(1e-6, time.monotonic() - self.started)
            return {'cpu_pct': {k: round(100.0 * v / elapsed, 1) for k, v in self.cpu.items()},
                    'rss_mb': {k: round(v / 2 ** 20) for k, v in self.rss_peak.items()}}


class Run:
    """One configuration: its sources and sinks, measured with monitoring OFF and ON."""

    def __init__(self, server: Any, ros: Any, args: argparse.Namespace, config: Dict[str, Any]):
        self.server, self.ros, self.args, self.config = server, ros, args, config
        self.procs: List[subprocess.Popen] = []
        self.topics = [f'/heavy/s{i}' for i in range(config['streams'])]
        self.sinks = [f'heavy_sink_{i}' for i in range(config['streams'])]

    def start(self) -> None:
        c = self.config
        for i, topic in enumerate(self.topics):
            qos = f"qos:={getattr(self.args, 'qos', 'reliable')}"
            params = ['-p', f"kind:={c['kind']}", '-p', f"rate_hz:={c['rate_hz']}", '-p', qos]
            params += (['-p', f"width:={c['width']}", '-p', f"height:={c['height']}"] if c['kind'] == 'image'
                       else ['-p', f"points:={c['points']}"])
            self.procs.append(self.spawn('heavy_source', f'heavy_source_{i}', params, [('out', topic)]))
            self.procs.append(self.spawn('heavy_sink', self.sinks[i], ['-p', f"kind:={c['kind']}", '-p', qos],
                                         [('in', topic)]))
        self.ros.watch_sinks(self.sinks)

    @staticmethod
    def spawn(executable: str, node: str, params: List[str], remaps: List[Any]) -> subprocess.Popen:
        argv = [exe(executable), '--ros-args', '-r', f'__node:={node}']
        for src, dst in remaps:
            argv += ['-r', f'{src}:={dst}']
        return subprocess.Popen(argv + params, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)

    def stop(self) -> None:
        for proc in self.procs:
            try:
                os.killpg(proc.pid, signal.SIGINT)
            except ProcessLookupError:
                pass
        for proc in self.procs:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    def sink_rows(self) -> List[Any]:
        return [self.ros.sinks[s][1].paths[0] for s in self.sinks
                if s in self.ros.sinks and self.ros.sinks[s][1].paths]

    def wait_flowing(self) -> None:
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            if len(self.sink_rows()) == len(self.sinks):
                return
            time.sleep(0.5)
        raise RuntimeError('no data reaches the sinks')

    def processes(self) -> Dict[str, Any]:
        def pids(procs: List[subprocess.Popen]) -> Any:
            return lambda: [psutil.Process(p.pid) for p in procs if p.poll() is None]
        return {'source': pids(self.procs[0::2]), 'sink': pids(self.procs[1::2]),
                'probe': lambda: self.server.processes().get('probe', []),
                'server': lambda: self.server.processes().get('roshanavi', [])}

    def phase(self, meter: Meter, warmup: float, duration: float) -> Dict[str, Any]:
        time.sleep(warmup)
        before = [(p.received, p.lost) for p in self.sink_rows()]
        meter.reset()
        udp0, t0 = udp_datagrams(), time.monotonic()
        time.sleep(duration)
        elapsed = time.monotonic() - t0
        rows = self.sink_rows()
        got = sum(r.received - b[0] for r, b in zip(rows, before))
        lost = sum(r.lost - b[1] for r, b in zip(rows, before))
        expected = self.config['rate_hz'] * self.config['streams'] * elapsed
        result = meter.result()
        result.update({
            'rate_hz': round(got / elapsed / len(rows), 2) if rows else 0.0,
            'lost_share': round(lost / (got + lost), 3) if got + lost else 1.0,
            'received_share': round(got / expected, 3) if expected else 0.0,
            'p50_ms': round(sum(r.latency_ms_p50 for r in rows) / len(rows), 2) if rows else None,
            'p95_ms': round(max(r.latency_ms_p95 for r in rows), 2) if rows else None,
            'udp_datagrams_per_s': round((udp_datagrams() - udp0) / elapsed),
            'shm_mb': round(shm_bytes() / 2 ** 20)})
        return result

    def monitor(self, enabled: bool) -> None:
        for topic in self.topics:
            self.server.api('PUT', f'/api/traffic{topic}/monitor', {'enabled': enabled})

    def probe_view(self) -> Dict[str, Any]:
        entries = {e['topic']: e for e in self.server.api('GET', '/api/traffic?window=5')['topics']}
        rows = [entries[t] for t in self.topics if t in entries]
        return {'monitored': all(e.get('monitored') for e in rows) if rows else None,
                'hz': round(sum(e['hz'] or 0 for e in rows) / len(rows), 2) if rows else None,
                'drop_ratio': max((e.get('drop_ratio') or 0 for e in rows), default=None),
                'status': sorted({e.get('status') for e in rows}),
                'avg_size_mb': round(sum(e.get('avg_size') or 0 for e in rows) / max(1, len(rows)) / MB, 2)}

    def measure(self) -> Dict[str, Any]:
        a = self.args
        meter = Meter(self.processes())
        meter.start()
        try:
            self.wait_flowing()
            off = {**self.phase(meter, a.warmup, a.duration), 'probe_view': self.probe_view()}
            self.monitor(True)
            on = {**self.phase(meter, a.warmup + 2, a.duration), 'probe_view': self.probe_view()}
            self.monitor(False)
        finally:
            meter.stop_flag.set()
        return {'off': off, 'on': on}


def verdict(config: Dict[str, Any], off: Dict[str, Any], on: Dict[str, Any]) -> List[str]:
    """Why the configuration counts as broken (empty list = fine)."""
    reasons = []
    if off['lost_share'] > BREAK_LOSS or off['received_share'] < BREAK_RATE:
        reasons.append('担い切れない (監視なしでも購読側が取りこぼす)')
    if on['lost_share'] > BREAK_LOSS or on['received_share'] < BREAK_RATE:
        reasons.append('監視中に購読側が取りこぼす')
    if on['p50_ms'] and off['p50_ms'] and on['p50_ms'] > BREAK_LATENCY_X * max(off['p50_ms'], 1.0):
        reasons.append('監視中に遅延が 2 倍超')
    view = on['probe_view']
    if view['hz'] is not None and view['hz'] < BREAK_RATE * config['rate_hz']:
        reasons.append('probe の計測 Hz が実際の 90% 未満')
    if on['cpu_pct'].get('probe', 0) >= BREAK_PROBE_CPU:
        reasons.append('probe が 1 コアを使い切る')
    return reasons


def solve(a: List[List[float]], b: List[float]) -> Optional[List[float]]:
    """Gaussian elimination for a small square system (None when singular)."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            return None
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(n):
            if r != col:
                f = m[r][col] / m[col][col]
                m[r] = [x - f * y for x, y in zip(m[r], m[col])]
    return [m[i][n] / m[i][i] for i in range(n)]


def lstsq(rows: List[Any], columns: List[int]) -> Optional[List[float]]:
    """Least squares of y on the chosen columns of x = [msgs/s, MB/s, 1]."""
    ata = [[sum(r[0][i] * r[0][j] for r in rows) for j in columns] for i in columns]
    atb = [sum(r[0][i] * r[1] for r in rows) for i in columns]
    return solve(ata, atb)


def probe_keeps_up(entry: Dict[str, Any]) -> bool:
    on = entry['on']
    return ((on['probe_view']['hz'] or 0) >= BREAK_RATE * entry['config']['rate_hz']
            and on['cpu_pct'].get('probe', 0) < BREAK_PROBE_CPU)


def fit_cost(points: List[Dict[str, Any]], key: str) -> Optional[Dict[str, Any]]:
    """extra CPU % = a * msgs/s + b * MB/s + c  (ON minus OFF), coefficients kept >= 0.

    Only points where the probe keeps up (it sees >= 90% of the rate and is below one core), so
    saturation does not bend the line. A coefficient that comes out negative is dropped and the
    rest refitted (the data cannot separate it from the others).
    """
    rows = [([p['msgs_per_s'], p['mb_per_s'], 1.0], p[key]) for p in points
            if p.get(key) is not None and 'error' not in p and probe_keeps_up(p)]
    columns = [0, 1, 2]
    coef = None
    while len(rows) >= 4 and columns:
        got = lstsq(rows, columns)
        if got is None:
            return None
        negative = [c for c, v in zip(columns, got) if v < 0 and c != 2]
        if not negative:
            coef = dict(zip(columns, got))
            break
        columns = [c for c in columns if c != negative[0]]
    if coef is None:
        return None
    full = [coef.get(0, 0.0), coef.get(1, 0.0), coef.get(2, 0.0)]
    mean = sum(r[1] for r in rows) / len(rows)
    ss_res = sum((r[1] - sum(c * x for c, x in zip(full, r[0]))) ** 2 for r in rows)
    ss_tot = sum((r[1] - mean) ** 2 for r in rows) or 1e-9
    return {'a_pct_per_kmsg': round(full[0] * 1000, 2), 'b_pct_per_100mb': round(full[1] * 100, 2),
            'c_pct': round(full[2], 2), 'r2': round(1 - ss_res / ss_tot, 3), 'n': len(rows)}


def apply_transport(name: str) -> str:
    """Set the environment every participant inherits; returns a description."""
    if name == 'udp':
        os.environ['FASTDDS_BUILTIN_TRANSPORTS'] = 'UDPv4'
        return 'UDPv4 only (FASTDDS_BUILTIN_TRANSPORTS=UDPv4)'
    profile = os.path.join(tempfile.mkdtemp(prefix='fastdds_'), 'shm.xml')
    with open(profile, 'w', encoding='utf-8') as fh:
        fh.write(SHM_PROFILE)
    os.environ['FASTRTPS_DEFAULT_PROFILES_FILE'] = profile
    return 'shared memory (256 MB segment) + UDP for discovery'


SHM_PROFILE = '''<?xml version="1.0" encoding="UTF-8" ?>
<profiles xmlns="http://www.eprosima.com/XMLSchemas/fastRTPS_Profiles">
  <transport_descriptors>
    <transport_descriptor><transport_id>shm_big</transport_id><type>SHM</type>
      <segment_size>268435456</segment_size></transport_descriptor>
    <transport_descriptor><transport_id>udp_t</transport_id><type>UDPv4</type></transport_descriptor>
  </transport_descriptors>
  <participant profile_name="shm_big_profile" is_default_profile="true"><rtps>
    <useBuiltinTransports>false</useBuiltinTransports>
    <userTransports><transport_id>shm_big</transport_id><transport_id>udp_t</transport_id></userTransports>
  </rtps></participant>
</profiles>
'''


def measure_one(server: Any, ros: Any, args: argparse.Namespace, config: Dict[str, Any]) -> Dict[str, Any]:
    run = Run(server, ros, args, config)
    entry: Dict[str, Any] = {'label': label(config), 'config': config, 'mb_per_s': round(rate_mb(config), 2),
                             'msgs_per_s': msgs_per_s(config)}
    try:
        run.start()
        entry.update(run.measure())
        entry['broken'] = verdict(config, entry['off'], entry['on'])
        entry['probe_extra_cpu'] = round(entry['on']['cpu_pct'].get('probe', 0) - entry['off']['cpu_pct'].get('probe', 0), 1)
        entry['server_extra_cpu'] = round(entry['on']['cpu_pct'].get('server', 0) - entry['off']['cpu_pct'].get('server', 0), 1)
    except Exception as exc:  # the configuration is part of the result
        entry['error'] = f'{type(exc).__name__}: {exc}'
        entry['broken'] = ['測定できなかった']
    finally:
        run.stop()
        time.sleep(2)
    return entry


def main_run(args: argparse.Namespace) -> Dict[str, Any]:
    transport = apply_transport(args.transport)
    from bench_pipeline import RosSide, Server, kill_leftovers
    server = Server(tempfile.mkdtemp(prefix='bench_heavy_'), 'version: 1\n')
    ros = RosSide()
    done: Dict[str, Dict[str, Any]] = {}
    results: List[Dict[str, Any]] = []
    try:
        server.wait_healthy()
        for family in args.families:
            for config in FAMILIES[family]:
                key = label(config)
                if key not in done:
                    done[key] = measure_one(server, ros, args, config)
                    print(describe(done[key]), flush=True)
                entry = {**done[key], 'family': family}
                results.append(entry)
                if entry['broken'] and not args.keep_going:
                    break
    finally:
        server.stop()
        ros.shutdown()
        kill_leftovers()
    good = [e for e in done.values() if 'error' not in e]
    model = {'probe': fit_cost(good, 'probe_extra_cpu'), 'server': fit_cost(good, 'server_extra_cpu')}
    return {'meta': {'ncpu': psutil.cpu_count(), 'loadavg_end': os.getloadavg(), 'date': time.strftime('%F %T'),
                     'transport': transport, 'qos': args.qos,
                     'shm_size_mb': round(psutil.disk_usage('/dev/shm').total / 2 ** 20)},
            'results': results, 'model': model}


def describe(entry: Dict[str, Any]) -> str:
    if 'error' in entry:
        return f"  {entry['label']}: {entry['error']}"
    off, on = entry['off'], entry['on']
    return (f"  {entry['label']} ({entry['mb_per_s']} MB/s, {entry['msgs_per_s']:g} msg/s): OFF p50 {off['p50_ms']} "
            f"p95 {off['p95_ms']} ms loss {off['lost_share']:.1%} | ON p50 {on['p50_ms']} p95 {on['p95_ms']} ms loss "
            f"{on['lost_share']:.1%} | probe +{entry['probe_extra_cpu']}% ({on['cpu_pct'].get('probe')}%) "
            f"{on['rss_mb'].get('probe')} MB server +{entry['server_extra_cpu']}% | probe sees "
            f"{on['probe_view']['hz']} Hz drop {on['probe_view']['drop_ratio']} | udp/s {on['udp_datagrams_per_s']} "
            f"shm {on['shm_mb']} MB{' BROKEN: ' + ', '.join(entry['broken']) if entry['broken'] else ''}")


FAMILY_TITLES = {'M': 'M: 小さい (1 KB) まま件数を増やす', 'R': 'R: 件数を増やす (1 MB 固定)', 'S': 'S: 大きさを増やす (30 Hz 固定)',
                 'C': 'C: 実物の目安 (カメラ・点群)'}


def report(data: Dict[str, Any]) -> str:
    meta = data['meta']
    lines = [f"#### 転送: {meta['transport']} (QoS {meta['qos']}、/dev/shm {meta['shm_size_mb']} MB、{meta['ncpu']} コア、"
             f"測定後の load average {meta['loadavg_end'][0]:.1f})\n"]
    for family in ('M', 'R', 'S', 'C'):
        rows = [e for e in data['results'] if e['family'] == family]
        if not rows:
            continue
        lines += [f'**{FAMILY_TITLES[family]}**\n',
                  '| ストリーム | 件/秒 | MB/秒 | 購読側 p50/p95 ms (なし → あり) | 購読側の欠落 (なし → あり) | probe 追加 CPU % (合計) / RSS MB | '
                  'server 追加 CPU % | source CPU % (なし → あり) | probe が見た Hz / 実際 | UDP 通/秒 | shm MB | 判定 |',
                  '|---|---|---|---|---|---|---|---|---|---|---|---|']
        for e in rows:
            if 'error' in e:
                lines.append(f"| {e['label']} | {e['msgs_per_s']:g} | {e['mb_per_s']} | " + ' | '.join(['-'] * 8) + f" | {e['error']} |")
                continue
            off, on, cfg = e['off'], e['on'], e['config']
            lines.append(
                f"| {e['label']} | {e['msgs_per_s']:g} | {e['mb_per_s']} | {off['p50_ms']}/{off['p95_ms']} → {on['p50_ms']}/{on['p95_ms']} | "
                f"{off['lost_share']:.1%} → {on['lost_share']:.1%} | +{e['probe_extra_cpu']} ({on['cpu_pct'].get('probe')}) / {on['rss_mb'].get('probe')} | "
                f"+{e['server_extra_cpu']} | {off['cpu_pct'].get('source')} → {on['cpu_pct'].get('source')} | "
                f"{on['probe_view']['hz']} / {cfg['rate_hz']:g} | {on['udp_datagrams_per_s']} | {on['shm_mb']} | "
                f"{'×: ' + '、'.join(e['broken']) if e['broken'] else '○'} |")
        lines.append('')
    good = [e for e in {e['label']: e for e in data['results']}.values() if 'error' not in e]
    probe = fit_cost(good, 'probe_extra_cpu')
    if probe:
        lines.append(f"**probe の追加 CPU の近似**: ≈ {probe['a_pct_per_kmsg']} % × (千件/秒) + {probe['b_pct_per_100mb']} % × (100 MB/秒) "
                     f"+ {probe['c_pct']} % (決定係数 R² = {probe['r2']}、{probe['n']} 点)\n")
    return '\n'.join(lines)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument('--out', help='write results as JSON')
    ap.add_argument('--report', nargs='+', metavar='JSON', help='print the tables of result files and exit')
    ap.add_argument('--transport', choices=['shm', 'udp'], default='shm',
                    help='shm: shared memory with a big segment; udp: UDPv4 only')
    ap.add_argument('--qos', choices=['reliable', 'best_effort'], default='reliable')
    ap.add_argument('--families', default='R,S,M,C', type=lambda s: s.split(','))
    ap.add_argument('--keep-going', action='store_true', help='do not stop a family at its first broken point')
    ap.add_argument('--warmup', type=float, default=6.0)
    ap.add_argument('--duration', type=float, default=10.0)
    return ap.parse_args(argv)


def main() -> int:
    args = parse_args()
    if args.report:
        merged: Dict[str, Dict[str, Any]] = {}
        for path in args.report:
            with open(path, encoding='utf-8') as fh:
                data = json.load(fh)
            known = merged.setdefault(data['meta']['transport'], data)
            if known is not data:
                known['results'] += data['results']
        for data in merged.values():
            print(report(data))
        return 0
    data = main_run(args)
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, indent=1)
    print(report(data))
    return 0


if __name__ == '__main__':
    sys.exit(main())
