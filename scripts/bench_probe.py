#!/usr/bin/env python3
"""Benchmark the C++ probe's own CPU (docs/design/measurement.md, "性能").

Runs inside the test image (needs the built workspace):

    docker compose --profile test run --rm -v "$PWD/scripts:/scripts:ro" test \
        python3 /scripts/bench_probe.py

Starts the real ``probe`` executable, publishes a ``ProbeConfig`` for N std_msgs/String
topics and one rclpy process publishing 64 B messages on all of them at a fixed rate
(scheduled by one loop, so the publisher itself stays cheap). After WARM_SEC the CPU of the
probe process is measured with psutil over MEASURE_SEC (100% = one core), next to the CPU
the probe reports about itself and the Hz it measured (sanity check: must equal the rate).

Scenarios (topics x Hz): a = 10 x 100, c = 100 x 10, d = 200 x 1, g = 2 x 500 (BENCH_ONLY selects, e.g. "ac").
"""

import json
import os
import statistics
import subprocess
import sys
import threading
import time
from typing import Dict, List

import psutil
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSDurabilityPolicy, QoSReliabilityPolicy
from roshanavi_msgs.msg import ProbeConfig, ProbeStats, ProbeTopic
from std_msgs.msg import String

WARM_SEC = 15.0
MEASURE_SEC = 20.0
ROUNDS = 2
PAYLOAD = 'x' * 64
SCENARIOS = {'a': (10, 100.0), 'c': (100, 10.0), 'd': (200, 1.0), 'g': (2, 500.0)}


def probe_exe() -> str:
    from ament_index_python.packages import get_package_prefix
    return os.path.join(get_package_prefix('roshanavi_probe'), 'lib', 'roshanavi_probe', 'probe')


class Publisher(threading.Thread):
    """Publishes on every topic at ``hz`` from one loop (evenly staggered start)."""

    def __init__(self, node: Node, topics: List[str], hz: float):
        super().__init__(daemon=True)
        self.pubs = [node.create_publisher(String, t, 10) for t in topics]
        self.period = 1.0 / hz
        self.stop_flag = threading.Event()
        self.msg = String(data=PAYLOAD)

    def run(self) -> None:
        t0 = time.monotonic()
        n = len(self.pubs)
        due = [t0 + self.period * i / n for i in range(n)]
        while not self.stop_flag.is_set():
            for k in range(n):  # every topic is due once per period, evenly staggered
                self._wait_until(due[k])
                self.pubs[k].publish(self.msg)
                due[k] += self.period

    def _wait_until(self, when: float) -> None:
        delay = when - time.monotonic()
        if delay > 0:
            time.sleep(delay)


def scenario(node: Node, name: str, n_topics: int, hz: float, config_pub, latest: Dict) -> Dict:
    topics = [f'/bench/t{i:03d}' for i in range(n_topics)]
    pub = Publisher(node, topics, hz)
    pub.start()
    probe = subprocess.Popen([probe_exe(), '--ros-args', '-p', 'exit_with_parent:=false'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2.0)
    cfg = ProbeConfig()
    cfg.instance = ''
    cfg.windows_sec = [1.0, 5.0, 10.0]
    cfg.topics = [ProbeTopic(topic=t, type='std_msgs/msg/String', best_effort=False)
                  for t in topics]
    config_pub.publish(cfg)
    rounds = []
    try:
        time.sleep(WARM_SEC)
        for _ in range(ROUNDS):
            proc = psutil.Process(probe.pid)
            before = sum(proc.cpu_times()[:2])
            reported: List[float] = []
            start = time.monotonic()
            while time.monotonic() - start < MEASURE_SEC:
                time.sleep(1.0)
                if 'cpu' in latest:
                    reported.append(latest['cpu'])
            span = time.monotonic() - start
            cpu = (sum(proc.cpu_times()[:2]) - before) / span * 100
            hz5 = latest.get('hz5', [])
            result = {'cpu_probe': round(cpu, 2),
                      'cpu_reported': round(statistics.mean(reported), 2) if reported else None,
                      'hz5_min': round(min(hz5), 2) if hz5 else None,
                      'hz5_max': round(max(hz5), 2) if hz5 else None,
                      'topics_seen': len(hz5), 'rss_mb': round(proc.memory_info().rss / 1e6, 1)}
            rounds.append(result)
            print(name, json.dumps(result), flush=True)
    finally:
        pub.stop_flag.set()
        probe.terminate()
        probe.wait(timeout=10)
        pub.join(timeout=5)
        for p in pub.pubs:
            node.destroy_publisher(p)
        latest.clear()
    return {'scenario': name, 'n_topics': n_topics, 'hz': hz, 'rounds': rounds}


def main() -> int:
    rclpy.init()
    node = Node('bench_probe_driver')
    latest: Dict = {}

    def on_stats(msg: ProbeStats) -> None:
        latest['cpu'] = msg.cpu_percent
        latest['hz5'] = [t.hz for t in msg.topics if t.window_sec == 5.0]

    node.create_subscription(ProbeStats, '/roshanavi/_probe/stats', on_stats,
                             QoSProfile(depth=2, reliability=QoSReliabilityPolicy.RELIABLE))
    config_pub = node.create_publisher(
        ProbeConfig, '/roshanavi/_probe/config',
        QoSProfile(depth=1, reliability=QoSReliabilityPolicy.RELIABLE,
                   durability=QoSDurabilityPolicy.TRANSIENT_LOCAL))
    threading.Thread(target=rclpy.spin, args=(node,), daemon=True).start()
    only = os.environ.get('BENCH_ONLY', ''.join(SCENARIOS))
    results = []
    for key, (n_topics, hz) in SCENARIOS.items():
        if key in only:
            results.append(scenario(node, f'{key}_{n_topics}x{hz:g}Hz', n_topics, hz,
                                    config_pub, latest))
    print('RESULT', json.dumps(results))
    return 0


if __name__ == '__main__':
    sys.exit(main())
