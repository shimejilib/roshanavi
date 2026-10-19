#!/usr/bin/env python3
"""Churn harness: does the roshanavi server process leak memory under repeated UI-like operations?

Drives a RUNNING roshanavi server (use an isolated stack, never the user's lab) through repeated
operations of one type at a time and records the server's RSS, so that growth can be attributed
to an operation type ("bisect"). Python standard library + ``websockets`` only, so it runs inside
the roshanavi container next to the server:

    docker compose --profile e2e run -d --name wt-lab -e ROSHANAVI_DEBUG_TRACEMALLOC=1 \
        -v "$PWD/scripts:/scripts:ro" lab-e2e
    docker exec wt-lab python3 /scripts/churn_harness.py --ops input,echo --iterations 200

For every operation type (``--ops``, run one after the other, each *alone*):

  1. ``--warmup`` iterations that are not measured (imports, caches, allocator warm-up),
  2. ``--iterations`` measured iterations, RSS sampled every ``--sample-every`` iterations,
  3. a least-squares slope of RSS over the iteration count, reported as MB per 100 operations,
     plus (server started with ROSHANAVI_DEBUG_TRACEMALLOC=1) the growth of the Python heap seen by
     tracemalloc, the number of live objects, threads and file descriptors. RSS growing while the
     traced heap stays flat means allocator retention, not a Python-level leak. The last sample
     of a phase is taken after ``malloc_trim`` too, so the retained-but-free share is visible.

Operation types (``--list-ops``): input / transform / function / class (create + start + wait +
delete a node), echo / view / live / resources / logs (open + read + close a WebSocket),
scenario (run a bundled scenario), launcher (register + start + stop + delete a run target),
monitor (toggle traffic monitoring), params (read + write a node parameter), inject (one-shot
injection job), rest (poll the read-only endpoints the UI polls), idle (nothing: the baseline
drift of the server itself), mixed (every type above in turn).

The server's pid is found through ``/api/resources`` (group "self", process "server"); RSS is read
from /proc when the harness runs on the same host/container, else from the API sample (1 Hz).
Results go to stdout as a table and, with ``--out``, to a JSON file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

try:
    import websockets
except ImportError:  # pragma: no cover - the roshanavi image ships it
    websockets = None

KIB_PER_MB = 1024.0
IMAGE_TOPIC = '/churn_cam/image'
IMAGE_NODE = 'churn-cam'
TIMEOUT_SEC = 20.0


class Api:
    """Blocking JSON client; the harness is sequential so no thread pool is needed."""

    def __init__(self, base: str):
        self.base = base.rstrip('/')

    def call(self, method: str, path: str, body: Any = None, ok: Tuple[int, ...] = (200, 201, 202)
             ) -> Any:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
                raw = resp.read()
                status = resp.status
        except urllib.error.HTTPError as exc:
            raw, status = exc.read(), exc.code
        if status not in ok:
            raise RuntimeError(f'{method} {path} -> {status}: {raw[:300]!r}')
        return json.loads(raw) if raw else None

    def get(self, path: str) -> Any:
        return self.call('GET', path)

    def post(self, path: str, body: Any = None, ok: Tuple[int, ...] = (200, 201, 202)) -> Any:
        return self.call('POST', path, {} if body is None else body, ok)


# ---- memory probes --------------------------------------------------------------------------
def proc_status_kib(pid: int, field: str) -> Optional[int]:
    try:
        with open(f'/proc/{pid}/status', encoding='ascii') as handle:
            for line in handle:
                if line.startswith(field + ':'):
                    return int(line.split()[1])
    except (OSError, ValueError):
        pass
    return None


def find_server_pid(api: Api) -> Tuple[int, int]:
    """(pid, api rss in KiB) of the biggest 'self' process named server."""
    snap = api.get('/api/resources')
    rows = [p for p in snap.get('processes', [])
            if p.get('group') == 'self' and p.get('name') == 'server']
    if not rows:
        raise RuntimeError('no roshanavi server process in /api/resources (still starting?)')
    best = max(rows, key=lambda p: p.get('rss') or 0)
    return int(best['pid']), int((best.get('rss') or 0) // 1024)


class Sampler:
    def __init__(self, api: Api, pid: Optional[int]):
        self.api = api
        self.pid = pid
        self.debug_ok = True

    def rss_kib(self) -> int:
        pid = self.pid or find_server_pid(self.api)[0]
        value = proc_status_kib(pid, 'VmRSS')
        return value if value is not None else find_server_pid(self.api)[1]

    def sample(self, trim: bool = False, snapshot: bool = False) -> Dict[str, Any]:
        out: Dict[str, Any] = {'rss_kib': self.rss_kib(), 't': round(time.time(), 1)}
        if self.debug_ok:
            try:
                query = '?top=10' + ('&trim=true' if trim else '') + ('&snapshot=true' if snapshot else '')
                dbg = self.api.get('/api/_debug/memory' + query)
                out.update(py_kib=dbg['tracemalloc']['current_kib'], objects=dbg['gc_objects'],
                           threads=dbg['threads'], fds=dbg['fds'],
                           rss_after_trim_kib=dbg['rss_kib'] if trim else None,
                           diff=dbg['diff'])
            except RuntimeError:
                self.debug_ok = False  # the route only exists with ROSHANAVI_DEBUG_TRACEMALLOC=1
        return out


# ---- operations -----------------------------------------------------------------------------
Op = Callable[['Ctx', int], Awaitable[None]]


class Ctx:
    def __init__(self, api: Api, base: str, hold_sec: float):
        self.api, self.base, self.hold = api, base, hold_sec
        self.ws_base = base.replace('http://', 'ws://').replace('https://', 'wss://')
        self.tag = f'ch{os.getpid() % 10000}'

    def name(self, kind: str, i: int) -> str:
        return f'{self.tag}_{kind}_{i}'

    def delete_node(self, node_id: str) -> None:
        self.api.post('/api/registry/delete', {'ids': [node_id]})


async def op_input(ctx: Ctx, i: int) -> None:
    name = ctx.name('in', i)
    ctx.api.post('/api/dummies?start=true', {
        'id': name, 'name': name, 'topic': f'/{name}', 'type': 'std_msgs/msg/String',
        'kind': 'string', 'mode': 'periodic', 'rate_hz': 5, 'payload': {'data': 'x'}})
    await asyncio.sleep(ctx.hold)
    ctx.delete_node(name)


async def op_transform(ctx: Ctx, i: int) -> None:
    name = ctx.name('tf', i)
    ctx.api.post('/api/transforms?start=true', {
        'id': name, 'name': name, 'mode': 'relay',
        'inputs': [{'topic': '/chatter', 'type': 'std_msgs/msg/String'}],
        'output': {'topic': f'/{name}_out', 'type': 'std_msgs/msg/String'}})
    await asyncio.sleep(ctx.hold)
    ctx.delete_node(name)


async def op_function(ctx: Ctx, i: int) -> None:
    name = ctx.name('fn', i)
    ctx.api.post('/api/functions?start=true', {
        'id': name, 'name': name, 'module': 'roshanavi_examples.logic', 'function': 'shout',
        'inputs': [{'topic': '/chatter', 'kind': 'string'}],
        'output': {'topic': f'/{name}_out', 'kind': 'string'}})
    await asyncio.sleep(ctx.hold)
    ctx.delete_node(name)


async def op_class(ctx: Ctx, i: int) -> None:
    name = ctx.name('cl', i)
    ctx.api.post('/api/classes?start=true', {
        'id': name, 'name': name, 'module': 'roshanavi_examples.stateful',
        'class_name': 'MovingAverage', 'params': {'window': 3},
        'methods': [{'method': 'process', 'call': 'on_message',
                     'inputs': [{'topic': f'/{name}_in', 'kind': 'float'}],
                     'outputs': [{'topic': f'/{name}_out', 'kind': 'float'}]}],
        'actions': ['reset']})
    await asyncio.sleep(ctx.hold)
    ctx.api.post(f'/api/classes/{name}/call', {'method': 'reset'}, ok=(200, 201, 202, 404, 409))
    ctx.delete_node(name)


async def read_some(url: str, frames: int, timeout: float, binary_pairs: bool = False) -> int:
    got = 0
    async with websockets.connect(url, max_size=None, open_timeout=timeout) as ws:
        end = time.monotonic() + timeout
        while got < frames and time.monotonic() < end:
            try:
                await asyncio.wait_for(ws.recv(), timeout=max(0.1, end - time.monotonic()))
            except asyncio.TimeoutError:
                break
            got += 1
    return got


async def op_echo(ctx: Ctx, i: int) -> None:
    await read_some(f'{ctx.ws_base}/ws/echo/chatter', 2, 4.0)


async def op_view(ctx: Ctx, i: int) -> None:
    await read_some(f'{ctx.ws_base}/ws/view{IMAGE_TOPIC}', 4, 4.0)


async def op_live(ctx: Ctx, i: int) -> None:
    await read_some(f'{ctx.ws_base}/ws/live', 2, 4.0)


async def op_resources(ctx: Ctx, i: int) -> None:
    await read_some(f'{ctx.ws_base}/ws/resources', 2, 4.0)


async def op_logs(ctx: Ctx, i: int) -> None:
    await read_some(f'{ctx.ws_base}/ws/logs/talker', 1, 1.0)


async def op_scenario(ctx: Ctx, i: int) -> None:
    run = ctx.api.post('/api/scenarios/example:class_moving_average.yaml/run')
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        status = ctx.api.get(f'/api/scenario-runs/{run["run_id"]}')['status']
        if status not in ('pending', 'running'):
            return
        await asyncio.sleep(0.5)
    raise RuntimeError('scenario did not finish in 60 s')


async def op_launcher(ctx: Ctx, i: int) -> None:
    name = ctx.name('run', i)
    ctx.api.post('/api/targets?start=true', {
        'id': name, 'kind': 'run', 'package': 'demo_nodes_cpp', 'executable': 'talker',
        'name': name, 'remaps': {'chatter': f'/{name}_chatter'}})
    await asyncio.sleep(ctx.hold)
    ctx.api.post(f'/api/targets/{name}/stop')
    ctx.api.call('DELETE', f'/api/targets/{name}')


async def op_monitor(ctx: Ctx, i: int) -> None:
    for enabled in (False, True):
        ctx.api.call('PUT', '/api/traffic/chatter/monitor', {'enabled': enabled})
        await asyncio.sleep(0.3)


async def op_params(ctx: Ctx, i: int) -> None:
    params = ctx.api.get('/api/nodes/talker/parameters')
    if not params:
        raise RuntimeError('no parameter response')
    ctx.api.call('PUT', '/api/nodes/talker/parameters',
                 {'name': 'use_sim_time', 'type': 'bool', 'value': False}, ok=(200, 201, 400, 409, 422))


async def op_inject(ctx: Ctx, i: int) -> None:
    job = ctx.api.post('/api/inject', {'topic': f'/{ctx.name("inj", i)}', 'mode': 'periodic',
                                       'type': 'std_msgs/msg/String', 'rate_hz': 5,
                                       'payload': {'data': 'x'}})
    await asyncio.sleep(ctx.hold)
    ctx.api.call('DELETE', f'/api/inject/{job["id"]}')


async def op_rest(ctx: Ctx, i: int) -> None:
    for path in ('/api/graph', '/api/traffic', '/api/resources', '/api/node-list', '/api/targets',
                 '/api/project', '/api/tracing', '/api/resources/history', '/api/scenario-runs'):
        ctx.api.get(path)


async def op_idle(ctx: Ctx, i: int) -> None:
    await asyncio.sleep(ctx.hold)


OPS: Dict[str, Op] = {
    'input': op_input, 'transform': op_transform, 'function': op_function, 'class': op_class,
    'echo': op_echo, 'view': op_view, 'live': op_live, 'resources': op_resources,
    'logs': op_logs, 'scenario': op_scenario, 'launcher': op_launcher, 'monitor': op_monitor,
    'params': op_params, 'inject': op_inject, 'rest': op_rest, 'idle': op_idle}
SERIAL_OPS = {'scenario', 'mixed', 'monitor', 'params', 'rest', 'idle'}  # shared state: one at a time
MIXED_ORDER = ['input', 'transform', 'function', 'class', 'echo', 'view', 'live', 'scenario',
               'launcher', 'monitor', 'params', 'inject', 'rest']


async def op_mixed(ctx: Ctx, i: int) -> None:
    await OPS[MIXED_ORDER[i % len(MIXED_ORDER)]](ctx, i)


OPS['mixed'] = op_mixed


def setup_image_source(ctx: Ctx) -> bool:
    """A looping camera-like source for the viewer operation (persistent during the run)."""
    try:
        ctx.api.post('/api/dummies?start=true', {
            'id': IMAGE_NODE, 'name': IMAGE_NODE.replace('-', '_'), 'topic': IMAGE_TOPIC,
            'type': 'sensor_msgs/msg/Image', 'kind': 'image', 'mode': 'media',
            'source': 'samples/blobs.mp4', 'loop': True, 'rate_hz': 5})
        return True
    except RuntimeError as exc:
        print(f'note: no image source ({exc}); the view op will only open and close',
              file=sys.stderr)
        return False


# ---- running and statistics -----------------------------------------------------------------
def slope(xs: List[float], ys: List[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    var = sum((x - mx) ** 2 for x in xs)
    return 0.0 if var == 0 else sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var


async def run_batch(op: Op, ctx: Ctx, start: int, count: int, concurrency: int) -> int:
    errors = 0
    for first in range(start, start + count, concurrency):
        batch = range(first, min(first + concurrency, start + count))
        results = await asyncio.gather(*(op(ctx, i) for i in batch), return_exceptions=True)
        for res in results:
            if isinstance(res, Exception):
                errors += 1
                if errors <= 3:
                    print(f'  op error: {type(res).__name__}: {str(res)[:200]}', file=sys.stderr)
    return errors


async def run_phase(name: str, ctx: Ctx, sampler: Sampler, args: argparse.Namespace
                    ) -> Dict[str, Any]:
    op = OPS[name]
    conc = 1 if name in SERIAL_OPS else args.concurrency
    errors = await run_batch(op, ctx, 0, args.warmup, conc)
    await asyncio.sleep(args.settle)
    samples = [{'n': 0, **sampler.sample(snapshot=args.snapshots)}]
    done = 0
    while done < args.iterations:
        step = min(args.sample_every, args.iterations - done)
        errors += await run_batch(op, ctx, args.warmup + done, step, conc)
        done += step
        await asyncio.sleep(args.settle)
        last = done >= args.iterations
        samples.append({'n': done, **sampler.sample(trim=last, snapshot=last and args.snapshots)})
        print(f'  {name:9s} n={done:5d} rss={samples[-1]["rss_kib"] / KIB_PER_MB:8.2f} MB',
              file=sys.stderr)
    xs = [float(s['n']) for s in samples]
    result: Dict[str, Any] = {
        'op': name, 'iterations': args.iterations, 'errors': errors,
        'rss_start_mb': round(samples[0]['rss_kib'] / KIB_PER_MB, 2),
        'rss_end_mb': round(samples[-1]['rss_kib'] / KIB_PER_MB, 2),
        'rss_mb_per_100': round(slope(xs, [s['rss_kib'] / KIB_PER_MB for s in samples]) * 100, 3),
        'samples': samples}
    if 'py_kib' in samples[0]:
        result['py_start_mb'] = round(samples[0]['py_kib'] / KIB_PER_MB, 2)
        result['py_end_mb'] = round(samples[-1]['py_kib'] / KIB_PER_MB, 2)
        result['py_mb_per_100'] = round(slope(xs, [s['py_kib'] / KIB_PER_MB for s in samples]) * 100, 3)
        result['objects_per_100'] = round(slope(xs, [float(s['objects']) for s in samples]) * 100, 1)
        result['threads_end'] = samples[-1]['threads']
        result['fds_start'], result['fds_end'] = samples[0]['fds'], samples[-1]['fds']
        trimmed = samples[-1].get('rss_after_trim_kib')
        result['rss_after_trim_mb'] = (None if trimmed is None
                                       else round(trimmed / KIB_PER_MB, 2))
        result['top_growth'] = samples[-1].get('diff', [])[:5]
    return result


def print_table(results: List[Dict[str, Any]]) -> None:
    head = (f'{"op":10s} {"errs":>4s} {"rss start":>10s} {"rss end":>9s} {"MB/100 ops":>11s}'
            f' {"py MB/100":>10s} {"obj/100":>8s} {"fds":>9s} {"thr":>4s} {"after trim":>10s}')
    print(head)
    for r in results:
        py = r.get('py_mb_per_100')
        print(f'{r["op"]:10s} {r["errors"]:4d} {r["rss_start_mb"]:10.2f} {r["rss_end_mb"]:9.2f}'
              f' {r["rss_mb_per_100"]:11.3f} {"-" if py is None else f"{py:10.3f}":>10s}'
              f' {"-" if py is None else f"{r["objects_per_100"]:8.1f}":>8s}'
              f' {"-" if py is None else f"{r["fds_start"]}->{r["fds_end"]}":>9s}'
              f' {"-" if py is None else f"{r["threads_end"]:4d}":>4s}'
              f' {"-" if py is None or r["rss_after_trim_mb"] is None else f"{r["rss_after_trim_mb"]:10.2f}":>10s}')


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument('--base', default='http://localhost:6871', help='server URL (default %(default)s)')
    p.add_argument('--ops', default='idle,rest', help='comma separated operation types, each run alone')
    p.add_argument('--list-ops', action='store_true')
    p.add_argument('--iterations', type=int, default=100, help='measured iterations per op')
    p.add_argument('--warmup', type=int, default=10, help='unmeasured iterations before')
    p.add_argument('--sample-every', type=int, default=20)
    p.add_argument('--concurrency', type=int, default=4,
                   help='iterations running at once (shared-state ops always run one at a time)')
    p.add_argument('--hold', type=float, default=1.5, help='seconds a created node lives')
    p.add_argument('--settle', type=float, default=2.0, help='seconds to wait before a sample')
    p.add_argument('--snapshots', action='store_true',
                   help='take tracemalloc snapshots at the start and end of each phase (slow; the '
                        'allocation sites that grew most are listed as top_growth in --out)')
    p.add_argument('--pid', type=int, default=None, help='server pid (default: from /api/resources)')
    p.add_argument('--out', default=None, help='write the full result JSON here')
    return p.parse_args(argv)


async def main_async(args: argparse.Namespace) -> int:
    if websockets is None:
        print('the websockets package is required (run inside the roshanavi container)',
              file=sys.stderr)
        return 2
    api = Api(args.base)
    ctx = Ctx(api, args.base, args.hold)
    sampler = Sampler(api, args.pid)
    names = [n.strip() for n in args.ops.split(',') if n.strip()]
    unknown = [n for n in names if n not in OPS]
    if unknown:
        print(f'unknown ops: {unknown}; see --list-ops', file=sys.stderr)
        return 2
    if any(n in ('view', 'mixed') for n in names):
        setup_image_source(ctx)
        await asyncio.sleep(3.0)
    results = []
    for name in names:
        print(f'== {name}', file=sys.stderr)
        results.append(await run_phase(name, ctx, sampler, args))
    print_table(results)
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as handle:
            json.dump({'args': vars(args), 'results': results}, handle, indent=1)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if args.list_ops:
        print('\n'.join(OPS))
        return 0
    return asyncio.run(main_async(args))


if __name__ == '__main__':
    sys.exit(main())
