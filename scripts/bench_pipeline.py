#!/usr/bin/env python3
"""Scale and load limits of roshanavi with a relay pipeline (docs/design/measurement.md, 「規模と負荷の限界」).

Runs inside the test image (needs the built workspace), e.g. one series per call:

    docker compose --profile test run --rm -v "$PWD/scripts:/scripts:ro" test \
        python3 /scripts/bench_pipeline.py --presets medium --modes process,container --out /tmp/r.json
    python3 scripts/bench_pipeline.py --report r.json        # markdown tables (no ROS needed)

For every series (preset x mode) it starts a real roshanavi server with a project that launches the
generated pipeline (scripts/gen_pipeline.py), then raises the load in steps (source rate, payload
size, per-relay processing time) by setting node parameters at run time. Per step it records

  * roshanavi: CPU of the server / probe / tracing (100% = one core), how fresh the live map data
    is (/ws/live frame interval, frame age, frame size), and how long a new node takes to appear
  * ROS: end to end latency p50 / p95 (sink statistics), the age of the messages after each stage
    of one lane (each stage's share), drop rate (sinks vs the expected rate), and with the detailed
    tracing mode on: the first stage whose processed Hz is below its input (roshanavi's own
    "processing behind" diagnostic)
  * the machine: CPU of the pipeline processes, host CPU and load average (the numbers are only
    valid for a quiet machine; the host load is recorded so a busy run can be recognised)

A step that is clearly broken (more than half of the messages lost, p95 above 2 s, or nothing
arriving) ends its axis. Results are written as JSON; ``--report`` turns them into tables.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Tuple

try:
    import psutil
except ImportError:  # --report works without it
    psutil = None

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'ros2_ws', 'src', 'roshanavi_examples'))

BASE_RATE_HZ = 10.0
BASE_PAYLOAD = 1024
BROKEN_DROP = 0.5
BROKEN_P95_MS = 2000.0
EXTRA_NODE = 'bench_extra'
AXES = {
    'rate': [{'rate_hz': r, 'payload_bytes': BASE_PAYLOAD, 'process_ms': 0.0}
             for r in (10, 30, 100, 300, 1000)],
    'payload': [{'rate_hz': 30.0, 'payload_bytes': b, 'process_ms': 0.0}
                for b in (1024, 65536, 262144, 1048576, 4194304)],
    'process': [{'rate_hz': 20.0, 'payload_bytes': BASE_PAYLOAD, 'process_ms': p}
                for p in (2.0, 10.0, 30.0)],
}
LARGE_RATES = (10, 30, 100)  # the large preset only climbs the rate axis, with fewer steps


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def percentile(values: List[float], q: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))]


# ---- roshanavi server under test --------------------------------------------------------------

class Server:
    """A real roshanavi server whose project launches the pipeline."""

    def __init__(self, workdir: str, project_text: str):
        self.port = free_port()
        self.base = f'http://127.0.0.1:{self.port}'
        project = os.path.join(workdir, 'roshanavi.yaml')
        with open(project, 'w', encoding='utf-8') as fh:
            fh.write(project_text)
        data_dir = os.path.join(workdir, 'data')
        os.makedirs(data_dir, exist_ok=True)
        self.proc = subprocess.Popen(
            ['ros2', 'run', 'roshanavi', 'server', '--host', '127.0.0.1', '--port', str(self.port),
             '--data-dir', data_dir, '--project', project, '--no-sample-media', '--no-reverse-dns',
             '--log-level', 'warning'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    def api(self, method: str, path: str, body: Optional[dict] = None, timeout: float = 20.0) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method,
                                         headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return json.loads(resp.read() or b'null')

    def wait_healthy(self, timeout: float = 60.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                self.api('GET', '/api/health', timeout=2.0)
                return
            except (urllib.error.URLError, OSError, ValueError):
                time.sleep(0.5)
        raise RuntimeError('roshanavi server did not become healthy')

    def processes(self) -> Dict[str, List[psutil.Process]]:
        """Descendants of the server, sorted into roshanavi / probe / tracing / pipeline."""
        groups: Dict[str, List[psutil.Process]] = defaultdict(list)
        try:
            root = psutil.Process(self.proc.pid)
            family = [root, *root.children(recursive=True)]
        except psutil.NoSuchProcess:
            return groups
        for proc in family:
            try:
                groups[classify(proc)].append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        for proc in psutil.process_iter(['name']):  # lttng daemons are not descendants
            if (proc.info.get('name') or '').startswith('lttng-'):
                groups['tracing'].append(proc)
        return groups

    def stop(self) -> None:
        try:
            os.killpg(self.proc.pid, signal.SIGINT)
            self.proc.wait(timeout=30)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            pass
        kill_leftovers()


PIPELINE_NAMES = ('pipeline_source', 'pipeline_relay', 'pipeline_sink', 'component_container')


def classify(proc: psutil.Process) -> str:
    cmd = ' '.join(proc.cmdline())
    name = proc.name()
    if 'pipeline.launch.py' in cmd or name.startswith(PIPELINE_NAMES) or 'component_conta' in name:
        return 'pipeline'
    if name == 'probe' or 'roshanavi_probe' in cmd:
        return 'probe'
    if 'roshanavi.tracing' in cmd:
        return 'tracing'
    return 'roshanavi'


def kill_leftovers() -> None:
    """Only processes this benchmark started: the pipeline executables (never anything else)."""
    for proc in psutil.process_iter(['name']):
        name = proc.info.get('name') or ''
        if name.startswith(PIPELINE_NAMES) or name.startswith('component_conta'):
            try:
                proc.kill()
            except psutil.NoSuchProcess:
                pass


class CpuSampler(threading.Thread):
    """Per category CPU seconds, accumulated from per process deltas once a second."""

    def __init__(self, server: Server):
        super().__init__(daemon=True)
        self.server = server
        self.stop_flag = threading.Event()
        self.lock = threading.Lock()
        self.last: Dict[int, float] = {}
        self.total: Dict[str, float] = defaultdict(float)
        self.started = time.monotonic()
        self.rss: Dict[str, int] = {}

    def run(self) -> None:
        while not self.stop_flag.wait(1.0):
            rss: Dict[str, int] = defaultdict(int)
            for category, procs in self.server.processes().items():
                for proc in procs:
                    try:
                        times = proc.cpu_times()
                        used = times.user + times.system
                        rss[category] += proc.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                    with self.lock:
                        self.total[category] += max(0.0, used - self.last.get(proc.pid, used))
                        self.last[proc.pid] = used
            self.rss = dict(rss)

    def reset(self) -> None:
        with self.lock:
            self.total = defaultdict(float)
            self.started = time.monotonic()

    def percent(self) -> Dict[str, float]:
        with self.lock:
            elapsed = max(1e-6, time.monotonic() - self.started)
            return {k: round(100.0 * v / elapsed, 1) for k, v in self.total.items()}


# ---- /ws/live client ------------------------------------------------------------------------

class LiveClient(threading.Thread):
    """Records frames of /ws/live: arrival time, server time, size, and the node ids on the map."""

    def __init__(self, port: int):
        super().__init__(daemon=True)
        self.url = f'ws://127.0.0.1:{port}/ws/live?window=5'
        self.lock = threading.Lock()
        self.frames: List[Tuple[float, float, int]] = []
        self.nodes: set = set()
        self.node_log: List[Tuple[float, frozenset]] = []
        self.loop = asyncio.new_event_loop()
        self.stop_flag = False

    def run(self) -> None:
        try:
            self.loop.run_until_complete(self.read())
        except Exception as exc:  # the server went away (end of a series): nothing more to record
            print(f'  (live client ended: {type(exc).__name__})', flush=True)

    async def read(self) -> None:
        import websockets
        async with websockets.connect(self.url, max_size=None) as ws:
            while not self.stop_flag:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                received = time.time()
                frame = json.loads(raw)
                with self.lock:
                    self.frames.append((received, float(frame.get('server_time') or received),
                                        len(raw)))
                    if 'graph' in frame:
                        self.nodes = {n['id'] for n in frame['graph']['nodes']}
                        self.node_log.append((received, frozenset(self.nodes)))

    def mark(self) -> int:
        with self.lock:
            return len(self.frames)

    def summary(self, since: int) -> Dict[str, Any]:
        with self.lock:
            frames = self.frames[since:]
        if len(frames) < 3:
            return {'frames': len(frames)}
        gaps = [b[0] - a[0] for a, b in zip(frames, frames[1:])]
        ages = [(r - s) * 1000.0 for r, s, _ in frames]
        return {'frames': len(frames), 'interval_p50_s': round(percentile(gaps, 0.5), 3),
                'interval_p95_s': round(percentile(gaps, 0.95), 3),
                'age_p50_ms': round(percentile(ages, 0.5), 1),
                'age_p95_ms': round(percentile(ages, 0.95), 1),
                'kib_avg': round(statistics.mean(f[2] for f in frames) / 1024.0, 1)}

    def has_node(self, node: str) -> bool:
        with self.lock:
            return node in self.nodes


# ---- ROS side of the benchmark -------------------------------------------------------------

class RosSide:
    """One rclpy node: sink statistics, the age of messages along one lane, parameter changes."""

    def __init__(self) -> None:
        import rclpy
        from rclpy.executors import MultiThreadedExecutor
        from rclpy.node import Node
        rclpy.init()
        self.rclpy = rclpy
        self.node = Node('bench_pipeline_ctl')
        self.executor = MultiThreadedExecutor(num_threads=2)
        self.executor.add_node(self.node)
        self.thread = threading.Thread(target=self.executor.spin, daemon=True)
        self.thread.start()
        self.sinks: Dict[str, Any] = {}
        self.ages: Dict[str, deque] = defaultdict(lambda: deque(maxlen=5000))
        self.keep: List[Any] = []

    def watch_sinks(self, names: List[str]) -> None:
        from roshanavi_examples_msgs.msg import SinkStats
        for name in names:
            self.keep.append(self.node.create_subscription(
                SinkStats, f'/{name}/stats', lambda m, n=name: self.sinks.__setitem__(n, (time.time(), m)), 10))

    def watch_ages(self, topics: List[str]) -> None:
        from roshanavi_examples_msgs.msg import Payload
        for topic in topics:
            def callback(msg: Any, topic: str = topic) -> None:
                stamp = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
                self.ages[topic].append((time.time(), (time.time() - stamp) * 1000.0))
            self.keep.append(self.node.create_subscription(Payload, topic, callback, 10))

    def set_parameters(self, assignments: Dict[str, Dict[str, float]], timeout: float = 60.0) -> int:
        """``{node: {param: value}}`` through the nodes' set_parameters services; returns failures."""
        from rcl_interfaces.msg import Parameter, ParameterType, ParameterValue
        from rcl_interfaces.srv import SetParameters
        pending = []
        for node, values in assignments.items():
            client = self.clients().setdefault(node, self.node.create_client(
                SetParameters, f'{node}/set_parameters'))
            request = SetParameters.Request()
            for name, value in values.items():
                request.parameters.append(Parameter(name=name, value=ParameterValue(
                    type=ParameterType.PARAMETER_DOUBLE, double_value=float(value))))
            if client.wait_for_service(timeout_sec=5.0):
                pending.append(client.call_async(request))
            else:
                pending.append(None)
        deadline = time.monotonic() + timeout
        failures = 0
        for future in pending:
            while future is not None and not future.done() and time.monotonic() < deadline:
                time.sleep(0.01)
            if future is None or not future.done() or not all(r.successful for r in future.result().results):
                failures += 1
        return failures

    def clients(self) -> Dict[str, Any]:
        if not hasattr(self, '_clients'):
            self._clients: Dict[str, Any] = {}
        return self._clients

    def shutdown(self) -> None:
        self.executor.shutdown(timeout_sec=2.0)
        self.node.destroy_node()
        self.rclpy.try_shutdown()


# ---- one step ---------------------------------------------------------------------------------

class Series:
    def __init__(self, preset: str, mode: str, args: argparse.Namespace):
        from roshanavi_examples import pipeline_gen as gen
        self.gen = gen
        self.preset, self.mode, self.args = preset, mode, args
        self.api_timeouts = 0
        common = {'rate_hz': BASE_RATE_HZ, 'payload_bytes': BASE_PAYLOAD, 'mode': mode, 'containers': 1}
        if preset.startswith('grid:'):  # a size of its own, e.g. grid:5x16 (80 nodes)
            stages, width = preset[len('grid:'):].split('x')
            params = gen.PipelineParams(shape='grid', stages=int(stages), width=int(width), **common)
        else:
            params = gen.preset_params(preset, **common)
        self.pipe = gen.build_pipeline(params, 'bench_' + preset.replace(':', '_'))
        self.workdir = tempfile.mkdtemp(prefix='bench_pipeline_')
        self.spec_path = os.path.join(self.workdir, 'pipeline.json')
        with open(self.spec_path, 'w', encoding='utf-8') as fh:
            fh.write(gen.spec_json(self.pipe))
        self.stage_of = {'/' + n.name: n.stage for n in self.pipe.nodes}
        self.sources = ['/' + n.name for n in self.pipe.by_kind(gen.SOURCE)]
        self.relays = ['/' + n.name for n in self.pipe.by_kind(gen.RELAY)]
        self.sinks = [n.name for n in self.pipe.by_kind(gen.SINK)]
        self.lane = sorted((n for n in self.pipe.nodes if n.lane == 0 and n.outputs),
                           key=lambda n: n.stage)

    def project_text(self) -> str:
        args = [f'spec:={self.spec_path}', f'mode:={self.mode}', 'containers:=1',
                f'container_type:={self.args.container_type}']
        return ('version: 1\ntargets:\n- id: bench\n  kind: launch\n  package: roshanavi_examples\n'
                '  launch_file: pipeline.launch.py\n  args: ' + json.dumps(args) +
                '\n  role: mine\n  autostart: true\n')

    def expected_hz(self, rate_hz: float) -> float:
        return sum(self.pipe.expected_sink_hz.values()) * rate_hz / BASE_RATE_HZ

    def run(self, ros: RosSide) -> Dict[str, Any]:
        server = Server(self.workdir, self.project_text())
        sampler = CpuSampler(server)
        live = LiveClient(server.port)
        result: Dict[str, Any] = {'preset': self.preset, 'mode': self.mode,
                                  'container_type': (self.args.container_type
                                                     if self.mode == 'container' else None),
                                  'nodes': len(self.pipe.nodes), 'topics': len(self.pipe.topics),
                                  'steps': []}
        try:
            server.wait_healthy()
            started = time.monotonic()
            live.start()
            sampler.start()
            ros.watch_sinks(self.sinks)
            ros.watch_ages([self.lane[i].outputs[0] for i in range(len(self.lane))])
            self.wait_running(server, ros, live)
            result['startup_s'] = round(time.monotonic() - started, 1)
            result['startup_api_timeouts'] = self.api_timeouts
            result['startup_cpu_pct'] = sampler.percent()
            for axis, steps in self.axes():
                for load in steps:
                    step = self.step(server, ros, sampler, live, axis, load)
                    result['steps'].append(step)
                    print(self.describe(step), flush=True)
                    if step['broken']:
                        break
        finally:
            live.stop_flag = True
            sampler.stop_flag.set()
            server.stop()
        return result

    def axes(self) -> List[Tuple[str, List[Dict[str, float]]]]:
        if len(self.pipe.nodes) > 60:
            return [('rate', [s for s in AXES['rate'] if s['rate_hz'] in LARGE_RATES])]
        return [(name, steps) for name, steps in AXES.items() if name in self.args.axes]

    def wait_running(self, server: Server, ros: RosSide, live: LiveClient) -> None:
        wanted = {'/' + n.name for n in self.pipe.nodes}
        deadline = time.monotonic() + self.args.startup_timeout
        while time.monotonic() < deadline:
            try:
                seen = {n['id'] for n in server.api('GET', '/api/graph', timeout=60.0)['nodes']}
            except (urllib.error.URLError, OSError):  # the server is busy taking in the new nodes
                self.api_timeouts += 1
                continue
            flowing = sum(1 for s in self.sinks if s in ros.sinks and ros.sinks[s][1].paths)
            if wanted <= seen and flowing == len(self.sinks):
                return
            time.sleep(1.0)
        raise RuntimeError(f'pipeline did not come up: {len(wanted & seen)}/{len(wanted)} nodes on '
                           f'the map, data reaches {flowing}/{len(self.sinks)} sinks')

    def apply(self, ros: RosSide, load: Dict[str, float]) -> int:
        failed = ros.set_parameters({n: {'rate_hz': load['rate_hz'], 'payload_bytes': load['payload_bytes']}
                                     for n in self.sources})
        return failed + ros.set_parameters({n: {'process_ms': load['process_ms']} for n in self.relays})

    def step(self, server: Server, ros: RosSide, sampler: CpuSampler, live: LiveClient,
             axis: str, load: Dict[str, float]) -> Dict[str, Any]:
        a = self.args
        step: Dict[str, Any] = {'axis': axis, **load, 'broken': False,
                                'param_failures': self.apply(ros, load)}
        time.sleep(a.warmup)
        for q in ros.ages.values():
            q.clear()
        sampler.reset()
        psutil.cpu_percent(None)
        mark = live.mark()
        time.sleep(a.duration)
        step.update(self.measure(server, ros, sampler, live, mark, load))
        step['event_lag'] = self.event_lag(live)
        if a.tracing:
            step['tracing'] = self.trace_phase(server, sampler)
        step['broken'] = (step['sinks'] == 0 or step['drop'] > BROKEN_DROP or
                          (step['e2e_p95_ms'] or 0) > BROKEN_P95_MS)
        return step

    def measure(self, server: Server, ros: RosSide, sampler: CpuSampler, live: LiveClient,
                mark: int, load: Dict[str, float]) -> Dict[str, Any]:
        cpu = sampler.percent()
        host = psutil.cpu_percent(None)
        rows = [(m, t) for t, m in ros.sinks.values() if time.time() - t < 5.0 and m.paths]
        paths = [p for m, _ in rows for p in m.paths]
        observed = sum(p.rate_hz for p in paths)
        expected = self.expected_hz(load['rate_hz'])
        weights = [p.rate_hz for p in paths]
        p50 = (sum(p.latency_ms_p50 * w for p, w in zip(paths, weights)) / sum(weights)) if sum(weights) else None
        stages = {}
        for node in self.lane:
            ages = [age for t, age in ros.ages[node.outputs[0]]]
            stages[node.name] = round(percentile(ages, 0.5), 1) if ages else None
        return {
            'sinks': len(rows), 'observed_hz': round(observed, 1), 'expected_hz': round(expected, 1),
            'drop': round(max(0.0, 1.0 - observed / expected), 3) if expected else 0.0,
            'e2e_p50_ms': round(p50, 1) if p50 is not None else None,
            'e2e_p95_ms': round(max((p.latency_ms_p95 for p in paths), default=0.0), 1) if paths else None,
            'stage_age_p50_ms': stages, 'cpu_pct': cpu, 'rss_mb': {k: round(v / 2 ** 20) for k, v in sampler.rss.items()},
            'host_cpu_pct': host, 'loadavg1': round(os.getloadavg()[0], 1), 'live': live.summary(mark)}

    def event_lag(self, live: LiveClient) -> Dict[str, Optional[float]]:
        """Seconds until a node started (and stopped) outside roshanavi shows up on (leaves) the map."""
        env = dict(os.environ)
        argv = ['ros2', 'run', 'roshanavi_examples', 'pipeline_sink', '--ros-args', '-r',
                f'__node:={EXTRA_NODE}', '-p', 'stats_period_s:=0.0']
        proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
                                start_new_session=True)
        appear = vanish = None
        try:
            start = time.monotonic()
            while time.monotonic() - start < self.args.event_timeout:
                if live.has_node('/' + EXTRA_NODE):
                    appear = round(time.monotonic() - start, 1)
                    break
                time.sleep(0.1)
        finally:
            stop = time.monotonic()
            try:
                os.killpg(proc.pid, signal.SIGINT)
                proc.wait(timeout=15)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                kill_leftovers()
        while appear is not None and time.monotonic() - stop < self.args.event_timeout:
            if not live.has_node('/' + EXTRA_NODE):
                vanish = round(time.monotonic() - stop, 1)
                break
            time.sleep(0.1)
        return {'appear_s': appear, 'vanish_s': vanish}

    def trace_phase(self, server: Server, sampler: CpuSampler) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        try:
            server.api('PUT', '/api/tracing', {'enabled': True}, timeout=60)
            time.sleep(self.args.trace_wait)
            sampler.reset()
            time.sleep(self.args.trace_sample)
            out['cpu_pct'] = sampler.percent()
            status = server.api('GET', '/api/tracing')
            out['events_per_sec'] = status.get('events_per_sec')
            out['discarded'] = status.get('discarded')
            traffic = server.api('GET', '/api/traffic?window=5')['topics']
            behind, measured = [], 0
            for entry in traffic:
                for sub in entry.get('subscribers') or []:
                    if sub.get('basis') != 'measured' or not sub['node'].lstrip('/').startswith(('relay', 'sink')):
                        continue
                    measured += 1
                    recv, done = sub.get('hz_recv'), sub.get('hz_processed')
                    if sub.get('behind') or (recv and done is not None and done < 0.9 * recv):
                        behind.append(sub['node'])
            out['measured_subscribers'] = measured
            out['behind_nodes'] = len(set(behind))
            if behind:
                first = min(set(behind), key=lambda n: (self.stage_of.get(n, 99), n))
                out['first_behind'] = first
                out['first_behind_stage'] = self.stage_of.get(first)
        except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
            out['error'] = f'{type(exc).__name__}: {exc}'
        finally:
            try:
                server.api('PUT', '/api/tracing', {'enabled': False}, timeout=60)
            except (urllib.error.URLError, OSError, ValueError):
                pass
        return out

    @staticmethod
    def describe(step: Dict[str, Any]) -> str:
        cpu = step['cpu_pct']
        return (f"  {step['axis']:8} rate {step['rate_hz']:g} Hz  {step['payload_bytes'] / 1024:g} KiB  "
                f"proc {step['process_ms']:g} ms: sink {step['observed_hz']}/{step['expected_hz']} Hz "
                f"drop {step['drop']:.0%} p50 {step['e2e_p50_ms']} p95 {step['e2e_p95_ms']} ms | "
                f"cpu server {cpu.get('roshanavi', 0)}% probe {cpu.get('probe', 0)}% "
                f"pipeline {cpu.get('pipeline', 0)}% | live {step['live']} | event {step['event_lag']} "
                f"| trace {step.get('tracing', {}).get('first_behind')}"
                f"{' BROKEN' if step['broken'] else ''}")


# ---- report -----------------------------------------------------------------------------------

def table(headers: List[str], rows: List[List[Any]]) -> str:
    def cell(value: Any) -> str:
        return '-' if value is None else str(value)
    lines = ['| ' + ' | '.join(headers) + ' |', '|' + '|'.join('---' for _ in headers) + '|']
    lines += ['| ' + ' | '.join(cell(v) for v in row) + ' |' for row in rows]
    return '\n'.join(lines)


def lane_text(ages: Dict[str, Optional[float]]) -> str:
    """Median age of the messages after each stage of one lane, e.g. ``src 0.2 > relay_1 0.9 > ...``."""
    return ' > '.join(f'{name} {value:g}' if value is not None else f'{name} -' for name, value in ages.items())


def compact_rows(series: Dict[str, Any]) -> List[List[Any]]:
    rows = []
    for s in series['steps']:
        cpu, live, trace = s['cpu_pct'], s['live'], s.get('tracing') or {}
        rows.append([s['axis'], f"{s['rate_hz']:g}", f"{s['payload_bytes'] / 1024:g}", f"{s['process_ms']:g}",
                     f"{s['drop']:.0%}", s['e2e_p50_ms'], s['e2e_p95_ms'], cpu.get('pipeline', 0),
                     cpu.get('roshanavi', 0), cpu.get('probe', 0), live.get('interval_p95_s'),
                     live.get('age_p95_ms'), trace.get('first_behind') or ('なし' if trace else '-'),
                     '×' if s['broken'] else ''])
    return rows


def report(results: List[Dict[str, Any]], compact: bool = False) -> str:
    out = []
    for series in results:
        out.append(f"### {series['preset']} ({series['nodes']} ノード, {series['topics']} トピック) / "
                   f"{series['mode']}{' mt' if series.get('container_type') == 'mt' else ''} "
                   f"(起動 {series.get('startup_s', '-')} 秒)\n")
        if compact:
            out.append(table(['軸', 'Hz/送信元', 'KiB', '処理 ms', '欠落', 'p50 ms', 'p95 ms', 'ノード %',
                              'server %', 'probe %', '更新間隔 p95 s', '更新遅れ p95 ms',
                              '最初に遅れた段', '限界'], compact_rows(series)))
            out.append('')
            continue
        ros_rows, app_rows = [], []
        for s in series['steps']:
            cpu, live, trace = s['cpu_pct'], s['live'], s.get('tracing') or {}
            key = [s['axis'], f"{s['rate_hz']:g}", f"{s['payload_bytes'] / 1024:g}", f"{s['process_ms']:g}"]
            tcpu = trace.get('cpu_pct') or {}
            ros_rows.append(key + [
                f"{s['drop']:.0%}", s['e2e_p50_ms'], s['e2e_p95_ms'], cpu.get('pipeline', 0),
                trace.get('first_behind') or ('なし' if trace else '-'),
                f"{s['host_cpu_pct']:g} / {s['loadavg1']:g}", '×' if s['broken'] else ''])
            app_rows.append(key + [
                cpu.get('roshanavi', 0), cpu.get('probe', 0),
                round(tcpu.get('roshanavi', 0) + tcpu.get('tracing', 0), 1) if tcpu else '-',
                live.get('interval_p95_s'), live.get('age_p95_ms'), live.get('kib_avg'),
                s['event_lag'].get('appear_s'), s['event_lag'].get('vanish_s')])
        head = ['軸', 'Hz/送信元', 'KiB', '処理 ms']
        out.append(table(head + ['欠落', 'p50 ms', 'p95 ms', 'ノード CPU %', '最初に遅れた段',
                                 'host CPU % / load', '限界'], ros_rows))
        out.append('')
        out.append(table(head + ['server %', 'probe %', 'server+トレース %', '更新間隔 p95 s',
                                 '更新遅れ p95 ms', 'フレーム KiB', '新ノード出現 s', '消滅 s'], app_rows))
        out.append('')
        for s in (series['steps'][i] for i in range(len(series['steps']))):
            if s['broken'] or s is series['steps'][-1]:
                out.append(f"- 段ごとの遅れ ({s['axis']} {s['rate_hz']:g} Hz, {s['payload_bytes'] / 1024:g} KiB, "
                           f"{s['process_ms']:g} ms) 中央値 ms: {lane_text(s['stage_age_p50_ms'])}")
        out.append('')
    return '\n'.join(out)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument('--presets', default='small,medium', help='comma separated: small,medium,large')
    ap.add_argument('--modes', default='process,container')
    ap.add_argument('--container-type', choices=['st', 'mt'], default='st',
                    help='component_container (st) or component_container_mt (mt) in container mode')
    ap.add_argument('--axes', default='rate,payload,process', type=lambda s: s.split(','))
    ap.add_argument('--out', help='write results as JSON')
    ap.add_argument('--report', nargs='+', metavar='JSON', help='print tables of result files and exit')
    ap.add_argument('--compact', action='store_true', help='with --report: one table per series')
    ap.add_argument('--warmup', type=float, default=7.0, help='seconds after a load change; must exceed the sink window (5 s)')
    ap.add_argument('--duration', type=float, default=10.0, help='measurement seconds per step')
    ap.add_argument('--no-tracing', dest='tracing', action='store_false')
    ap.add_argument('--trace-wait', type=float, default=8.0, help='seconds before sampling with tracing on')
    ap.add_argument('--trace-sample', type=float, default=6.0)
    ap.add_argument('--startup-timeout', type=float, default=240.0)
    ap.add_argument('--event-timeout', type=float, default=20.0)
    return ap.parse_args(argv)


def main() -> int:
    args = parse_args()
    if args.report:
        series = []
        for path in args.report:
            with open(path, encoding='utf-8') as fh:
                series += json.load(fh)['series']
        print(report([r for r in series if r['steps']], args.compact))
        return 0
    ros = RosSide()
    results: List[Dict[str, Any]] = []
    meta = {'ncpu': psutil.cpu_count(), 'loadavg_start': os.getloadavg(), 'date': time.strftime('%F %T')}
    try:
        for preset in args.presets.split(','):
            for mode in args.modes.split(','):
                print(f'== {preset} / {mode}', flush=True)
                try:
                    results.append(Series(preset, mode, args).run(ros))
                except Exception as exc:  # keep the other series; the error is part of the result
                    print(f'  FAILED: {type(exc).__name__}: {exc}', flush=True)
                    results.append({'preset': preset, 'mode': mode, 'error': str(exc), 'steps': [],
                                    'nodes': 0, 'topics': 0})
                if args.out:
                    with open(args.out, 'w', encoding='utf-8') as fh:
                        json.dump({'meta': meta, 'series': results}, fh, indent=1)
    finally:
        ros.shutdown()
        kill_leftovers()
    meta['loadavg_end'] = os.getloadavg()
    print(report([r for r in results if r['steps']]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
