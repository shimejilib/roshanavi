"""Memory stays bounded under connection churn (the "server leaks" investigation).

Findings these tests pin (docs/design/resources.md, メモリの増え方):
* every WebSocket connection of the ASGI server is a reference cycle that only a *full* GC frees,
  and with permessage-deflate each one also holds a ~150 KB zlib compressor -> hundreds of closed
  connections piled up as tens of MB the process never gave back. Fix: deflate off
  (``WS_PER_MESSAGE_DEFLATE``) + a periodic full GC (``GcJanitor``).
* the debug memory route exists only with ROSHANAVI_DEBUG_TRACEMALLOC set.
"""

import asyncio
import gc
import socket
import threading
import time
import weakref

import pytest
import uvicorn
import websockets
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient

from roshanavi import main as server_main
from roshanavi import server_debug
from roshanavi.gc_janitor import INTERVAL_SEC, GcJanitor, freeze_startup_objects
from roshanavi.ros_runtime import RosRuntime, make_qos
from roshanavi.malloc_tuning import DEFAULT_ARENAS, ENV_VAR, M_ARENA_MAX, limit_malloc_arenas
from roshanavi.server import create_app
from conftest import wait_for


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


# ---- GcJanitor ------------------------------------------------------------------------------
def test_janitor_waits_for_the_interval_then_collects_once_per_interval():
    clock, calls = Clock(), []
    janitor = GcJanitor(interval_sec=60.0, collect=lambda: calls.append(1) or 7, clock=clock)

    assert janitor.tick() is None
    clock.now += 59.0
    assert janitor.tick() is None and not calls

    clock.now += 1.0
    assert janitor.tick() == 7 and len(calls) == 1
    clock.now += 30.0
    assert janitor.tick() is None  # not due again yet
    clock.now += 30.0
    assert janitor.tick() == 7 and len(calls) == 2
    assert janitor.runs == 2 and janitor.last_ms is not None


def test_janitor_survives_a_failing_collector():
    clock = Clock()

    def boom():
        raise RuntimeError('gc broke')

    janitor = GcJanitor(interval_sec=1.0, collect=boom, clock=clock)
    clock.now += 2.0
    assert janitor.tick() is None  # swallowed (and logged), the housekeeping loop goes on
    assert janitor.runs == 0
    clock.now += 2.0
    assert janitor.tick() is None


class Garbage:
    """A reference cycle that owns a big buffer, like a closed connection object."""

    def __init__(self):
        self.me = self
        self.buffer = bytearray(64 * 1024)


def test_closed_connection_garbage_is_bounded_by_the_janitor():
    """Garbage that automatic GC never reaches (gen 2 waits for 25 % growth) is freed on a tick."""
    clock = Clock()
    janitor = GcJanitor(interval_sec=60.0, clock=clock)
    was_enabled = gc.isenabled()
    gc.collect()
    gc.disable()  # what a long-lived 100 k-object heap does in effect: no full pass for a long time
    try:
        refs = [weakref.ref(Garbage()) for _ in range(200)]  # 200 "closed connections", 12 MB
        assert sum(1 for r in refs if r() is not None) == 200

        clock.now += INTERVAL_SEC
        assert janitor.tick() >= 200
        assert sum(1 for r in refs if r() is not None) == 0
    finally:
        if was_enabled:
            gc.enable()


def test_freezing_startup_objects_shrinks_what_a_full_pass_walks():
    before = len(gc.get_objects())
    try:
        frozen = freeze_startup_objects()
        assert frozen > 1000 and gc.get_freeze_count() == frozen
        assert len(gc.get_objects()) < before / 10  # a full pass now only walks what is new
        fresh = weakref.ref(Garbage())
        assert gc.collect() >= 1 and fresh() is None  # new garbage is still collected
    finally:
        gc.unfreeze()


def test_lab_housekeeping_runs_the_janitor(lab):
    ticks = []

    class Stub:
        def tick(self):
            ticks.append(1)

    lab._gc_janitor = Stub()
    before = len(ticks)
    lab.housekeeping()
    assert len(ticks) == before + 1


# ---- rclpy callback group ---------------------------------------------------------------------
def test_destroyed_ros_entities_do_not_pile_up_in_the_callback_group(helper):
    """rclpy never removes the weakref of a destroyed entity from its callback group."""
    from std_msgs.msg import String
    from std_srvs.srv import Empty
    runtime = RosRuntime('roshanavi_prune_test')
    runtime.start()
    try:
        group = runtime.node.default_callback_group
        received = []
        keep = runtime.create_subscription(String, '/prune_live', lambda m: received.append(m),
                                           make_qos())
        before = len(group.entities)
        for _ in range(200):
            sub = runtime.create_subscription(String, '/prune_t', lambda m: None, make_qos())
            runtime.destroy_subscription(sub)
            client = runtime.create_client(Empty, '/prune_srv')
            runtime.destroy_client(client)
            timer = runtime.create_timer(30.0, lambda: None)
            runtime.destroy_timer(timer)
            pub = runtime.create_publisher(String, '/prune_p', make_qos())
            runtime.destroy_publisher(pub)
            del sub, client, timer, pub
        gc.collect()
        runtime.destroy_subscription(runtime.create_subscription(
            String, '/prune_t', lambda m: None, make_qos()))
        assert len(group.entities) - before < 30  # unpruned: ~ +1000 (5 weakrefs per cycle)

        # the surviving subscription still works after all that pruning
        helper.periodic_publisher(String, '/prune_live', 20.0, lambda i: String(data=str(i)))
        wait_for(lambda: received, timeout=30)
        assert group.has_entity(keep)
    finally:
        runtime.stop()


def test_prune_leaves_entities_that_are_still_alive_alone():
    from std_msgs.msg import String
    runtime = RosRuntime('roshanavi_prune_test2')
    runtime.start()
    try:
        subs = [runtime.create_subscription(String, f'/prune_alive_{i}', lambda m: None,
                                            make_qos()) for i in range(5)]
        group = runtime.node.default_callback_group
        with runtime._lock:
            assert runtime.prune_dead_entities() == 0
        assert all(group.has_entity(sub) for sub in subs)
    finally:
        runtime.stop()


# ---- lifecycle state cache ----------------------------------------------------------------
def test_lifecycle_cache_forgets_nodes_that_are_gone():
    from roshanavi.lifecycle import STATE_CACHE_SEC, LifecycleService
    clock = Clock()
    service = LifecycleService(object(), clock=clock)
    try:
        def poll(node):
            service._remember(node, 'active')
            return 'active'
        service._poll = poll
        for wave in range(5):  # nodes with fresh names every wave (create / delete churn)
            names = [f'/wave{wave}_node{i}' for i in range(50)]
            assert set(service.states(names).values()) == {'active'}
            clock.now += STATE_CACHE_SEC + 0.1
        assert len(service._cache) <= 50  # only the last wave can still be there
    finally:
        service.close()


# ---- reverse DNS cache --------------------------------------------------------------------
def test_reverse_dns_cache_is_capped():
    from roshanavi.resources.connections import MAX_RDNS_CACHE, ReverseDns
    assert MAX_RDNS_CACHE >= 256  # the production cap is comfortably above any normal host count
    clock, cap = Clock(), 40
    rdns = ReverseDns(resolve=lambda ip: 'h-' + ip, workers=1, max_pending=4096, clock=clock,
                      ttl_sec=600.0, max_cache=cap)
    try:
        total = cap + 60
        for i in range(total):  # a scan of many remote addresses, one lookup finishing at a time
            ip = f'203.0.{i // 250}.{i % 250 + 1}'
            rdns.name(ip)
            wait_for(lambda ip=ip: rdns._cache.get(ip), timeout=5)
            clock.now += 0.01
        assert len(rdns._cache) <= cap
        last = f'203.0.{(total - 1) // 250}.{(total - 1) % 250 + 1}'
        assert rdns.name(last) == 'h-' + last  # the newest entries survive
    finally:
        rdns.close()


# ---- malloc arenas --------------------------------------------------------------------------
class FakeLibc:
    def __init__(self, result=1):
        self.calls, self.result = [], result

    def mallopt(self, option, value):
        self.calls.append((option, value))
        return self.result


def test_malloc_arenas_are_capped_with_mallopt():
    libc = FakeLibc()
    assert limit_malloc_arenas(libc=libc, environ={}) is True
    assert libc.calls == [(M_ARENA_MAX, DEFAULT_ARENAS)] and M_ARENA_MAX == -8


def test_malloc_arenas_respect_the_users_environment_variable():
    libc = FakeLibc()
    assert limit_malloc_arenas(libc=libc, environ={ENV_VAR: '8'}) is False
    assert libc.calls == []


def test_malloc_arenas_report_failure_and_a_foreign_libc():
    assert limit_malloc_arenas(libc=FakeLibc(result=0), environ={}) is False
    assert limit_malloc_arenas(libc=object(), environ={}) is False  # not glibc: no mallopt


def test_malloc_arenas_with_the_real_libc_in_a_child_process():
    """mallopt is process-global, so prove it on the real glibc in a throw-away interpreter."""
    import subprocess
    import sys
    code = ('from roshanavi.malloc_tuning import limit_malloc_arenas; '
            'print(limit_malloc_arenas(environ={}))')
    out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=30)
    assert out.stdout.strip() == 'True', out.stderr


# ---- WebSocket compression ------------------------------------------------------------------
def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def _extensions_negotiated(deflate: bool) -> bool:
    """Real uvicorn + real WebSocket client: did the handshake agree on permessage-deflate?"""
    app = FastAPI()

    @app.websocket('/ws')
    async def ws(sock: WebSocket) -> None:
        await sock.accept()
        await sock.send_text('hi')
        await sock.close()

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error',
                                           ws_per_message_deflate=deflate))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started

    async def connect() -> bool:
        async with websockets.connect(f'ws://127.0.0.1:{port}/ws') as sock:  # offers deflate
            if hasattr(sock, 'response'):  # websockets >= 14 (new asyncio client)
                headers = sock.response.headers
            else:  # websockets 10 (legacy client)
                headers = sock.response_headers
            return headers.get('Sec-WebSocket-Extensions') is not None

    try:
        return asyncio.run(connect())
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_server_does_not_negotiate_websocket_compression():
    assert server_main.WS_PER_MESSAGE_DEFLATE is False
    assert _extensions_negotiated(deflate=True) is True  # the probe can tell the difference
    assert _extensions_negotiated(deflate=server_main.WS_PER_MESSAGE_DEFLATE) is False


# ---- debug route ----------------------------------------------------------------------------
def make_client(lab):
    return TestClient(create_app(lab, static_dir=None, live_period=0.2),
                      base_url='http://localhost')


def test_debug_memory_route_is_absent_by_default(lab, monkeypatch):
    monkeypatch.delenv(server_debug.ENV_VAR, raising=False)
    with make_client(lab) as client:
        assert client.get('/api/_debug/memory').status_code == 404


def test_debug_memory_route_with_the_env_var(lab, monkeypatch):
    monkeypatch.setenv(server_debug.ENV_VAR, server_debug.ROUTE_ONLY)
    with make_client(lab) as client:
        body = client.get('/api/_debug/memory?collect=true&find=Garbage').json()
        assert body['rss_kib'] > 0 and body['threads'] >= 1 and body['fds'] >= 1
        assert body['tracemalloc']['tracing'] is False  # route only: no tracing cost
        assert body['collected'] is not None and body['found']['count'] == 0
        # the Host / Origin middleware covers it like every other route
        assert client.get('/api/_debug/memory', headers={'Host': 'evil.example'}).status_code in (
            400, 403)
        assert client.get('/api/_debug/memory?top=0').status_code == 422


def test_debug_find_reports_what_holds_an_object():
    held = [Garbage()]
    found = server_debug.find_objects('Garbage')
    assert found['count'] >= 1 and found['referrers']
    del held


@pytest.mark.parametrize('value, tracing', [('1', True), ('route', False), (None, False)])
def test_start_if_enabled_only_traces_with_1(monkeypatch, value, tracing):
    import tracemalloc
    if value is None:
        monkeypatch.delenv(server_debug.ENV_VAR, raising=False)
    else:
        monkeypatch.setenv(server_debug.ENV_VAR, value)
    was_tracing = tracemalloc.is_tracing()
    try:
        assert server_debug.start_if_enabled() is tracing
    finally:
        if tracing and not was_tracing:
            tracemalloc.stop()
