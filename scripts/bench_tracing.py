#!/usr/bin/env python3
"""Benchmark 詳細計測モード: tracing off vs on (DESIGN §4.3.2 "性能").

Runs inside the test image (needs the built workspace):

    docker compose --profile test run --rm -v "$PWD/scripts:/scripts:ro" test \
        python3 /scripts/bench_tracing.py

Scenarios: (a) 10 topics x 100 Hz String 64 B, (b) Image 1280x720 rgb8 x 30 Hz; C++
publishers (rate_talker) and subscribers (slow_listener, no sleep) started after a real
``roshanavi server --probe auto --tracing auto``. For each round: tracing off, then on;
CPU from psutil over MEASURE_SEC (children included for the worker: its lttng CLI calls),
latency = receive - source timestamp printed once a second by the listeners.
"""

import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from typing import Dict, List

import psutil

PORT = 6990
WARM_SEC = 8.0
MEASURE_SEC = 20.0
ROUNDS = 2
BASE = f'http://127.0.0.1:{PORT}'


def exe(package: str, name: str) -> str:
    from ament_index_python.packages import get_package_prefix
    return os.path.join(get_package_prefix(package), 'lib', package, name)


def http(method: str, path: str, body=None) -> Dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={'Content-Type': 'application/json'} if data else {})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


class Listener:
    def __init__(self, argv: List[str]):
        self.proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     text=True)
        self.samples: List[tuple] = []
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self.proc.stdout:
            try:
                value = json.loads(line)['latency_us_avg']
            except (ValueError, KeyError):
                continue
            if value >= 0:
                self.samples.append((time.monotonic(), value))

    def latency(self, start: float, end: float) -> List[float]:
        return [v for t, v in self.samples if start <= t <= end]


def cpu_seconds(proc: psutil.Process, children: bool = False) -> float:
    try:
        t = proc.cpu_times()
    except psutil.Error:
        return 0.0
    total = t.user + t.system
    if children:
        total += t.children_user + t.children_system
    return total


def groups(server: subprocess.Popen, targets: List[subprocess.Popen]) -> Dict[str, List]:
    wrapper = psutil.Process(server.pid)  # `ros2 run` starts the real server as a child
    kids = wrapper.children(recursive=True)
    srv = next((p for p in kids if 'lib/roshanavi/server' in ' '.join(p.cmdline())), wrapper)
    probe = [p for p in kids if p.name() == 'probe']
    worker = [p for p in kids if 'tracing.worker' in ' '.join(p.cmdline())]
    lttng = [p for p in psutil.process_iter(['name'])
             if (p.info['name'] or '').startswith('lttng-')]
    return {'target': [psutil.Process(t.pid) for t in targets], 'server': [srv],
            'probe': probe, 'worker': worker, 'lttng': lttng}


def measure(server, targets, listeners) -> Dict[str, float]:
    procs = groups(server, targets)
    before = {k: sum(cpu_seconds(p, k == 'worker') for p in v) for k, v in procs.items()}
    start = time.monotonic()
    disk_max = 0
    while time.monotonic() - start < MEASURE_SEC:
        time.sleep(1.0)
        status = http('GET', '/api/tracing')
        disk_max = max(disk_max, status.get('disk_bytes') or 0)
    end = time.monotonic()
    after = {k: sum(cpu_seconds(p, k == 'worker') for p in v) for k, v in procs.items()}
    span = end - start
    result = {f'cpu_{k}': round((after[k] - before[k]) / span * 100, 2) for k in procs}
    lat = [v for lst in listeners for v in lst.latency(start, end)]
    result['latency_us'] = round(statistics.mean(lat), 1) if lat else None
    status = http('GET', '/api/tracing')
    result.update({'events_per_sec': status.get('events_per_sec'),
                   'discarded': status.get('discarded'), 'disk_max_bytes': disk_max,
                   'buffer_per_cpu': status.get('buffer_per_cpu')})
    return result


def scenario(name: str, talkers: List[List[str]], listeners: List[List[str]]) -> Dict:
    data = tempfile.mkdtemp(prefix='bench-')
    server = subprocess.Popen(
        ['ros2', 'run', 'roshanavi', 'server', '--port', str(PORT), '--data-dir', data,
         '--project', os.path.join(data, 'p.yaml'), '--no-autostart', '--probe', 'auto',
         '--tracing', 'auto', '--log-level', 'warning'], cwd='/ws')
    for _ in range(60):
        try:
            if http('GET', '/api/tracing').get('available'):
                break
        except OSError:
            pass
        time.sleep(0.5)
    targets = [subprocess.Popen(t, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
               for t in talkers]
    subs = [Listener(argv) for argv in listeners]
    rounds = []
    try:
        for _ in range(ROUNDS):
            http('PUT', '/api/tracing', {'enabled': False})
            time.sleep(WARM_SEC)
            off = measure(server, targets + [s.proc for s in subs], subs)
            http('PUT', '/api/tracing', {'enabled': True})
            time.sleep(WARM_SEC)
            on = measure(server, targets + [s.proc for s in subs], subs)
            rounds.append({'off': off, 'on': on})
            print(name, json.dumps(rounds[-1]), flush=True)
    finally:
        for p in targets + [s.proc for s in subs]:
            p.terminate()
        # SIGTERM to the `ros2 run` wrapper does not reach the server: stop the tree.
        tree = psutil.Process(server.pid).children(recursive=True)
        for p in [x for x in tree if 'lib/roshanavi/server' in ' '.join(x.cmdline())]:
            p.terminate()
        psutil.wait_procs(tree, timeout=30)
        server.terminate()
        server.wait(timeout=30)
    return {'scenario': name, 'rounds': rounds}


def main() -> int:
    talker, listener = exe('roshanavi_test_nodes', 'rate_talker'), \
        exe('roshanavi_test_nodes', 'slow_listener')
    small_t = [[talker, '--ros-args', '-r', f'__node:=bt{i}', '-p', f'topic:=/bench{i}',
                '-p', 'rate_hz:=100.0', '-p', 'size:=64'] for i in range(10)]
    small_l = [[listener, '--ros-args', '-r', f'__node:=bl{i}', '-p', f'topic:=/bench{i}']
               for i in range(10)]
    image_t = [[talker, '--ros-args', '-r', '__node:=bimg', '-p', 'topic:=/bench_img',
                '-p', 'rate_hz:=30.0', '-p', 'type:=image']]
    image_l = [[listener, '--ros-args', '-r', '__node:=bimgl', '-p', 'topic:=/bench_img',
                '-p', 'type:=image']]
    only = os.environ.get('BENCH_ONLY', 'ab')
    results = []
    if 'a' in only:
        results.append(scenario('a_10x100Hz', small_t, small_l))
    if 'b' in only:
        results.append(scenario('b_image_30Hz', image_t, image_l))
    print('RESULT', json.dumps(results))
    return 0


if __name__ == '__main__':
    sys.exit(main())
