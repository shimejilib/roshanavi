"""Shared fixtures. Sets a per-session ROS_DOMAIN_ID before rclpy is imported."""

import os
import random
import threading
import time
import uuid
from typing import Any, Callable, List

os.environ.setdefault('ROS_AUTOMATIC_DISCOVERY_RANGE', 'LOCALHOST')
os.environ['ROS_DOMAIN_ID'] = os.environ.get('ROSHANAVI_TEST_DOMAIN_ID',
                                             str(random.randint(110, 200)))

import pytest  # noqa: E402
import rclpy  # noqa: E402
from rclpy.context import Context  # noqa: E402
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor  # noqa: E402
from rclpy.node import Node  # noqa: E402
from rclpy.signals import SignalHandlerOptions  # noqa: E402


def wait_for(predicate: Callable[[], Any], timeout: float = 10.0, interval: float = 0.05) -> Any:
    """Poll ``predicate`` until truthy; return its value or fail the test."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    pytest.fail(f'condition not met within {timeout}s')


class Helper:
    """An independent rclpy context/node used to publish/subscribe from tests."""

    def __init__(self) -> None:
        self.context = Context()
        rclpy.init(context=self.context, signal_handler_options=SignalHandlerOptions.NO)
        self.node = Node(f'tl_helper_{uuid.uuid4().hex[:6]}', context=self.context)
        self.executor = SingleThreadedExecutor(context=self.context)
        self.executor.add_node(self.node)
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def _spin(self) -> None:
        try:
            self.executor.spin()
        except ExternalShutdownException:
            pass

    def periodic_publisher(self, msg_type: type, topic: str, rate_hz: float,
                           make_msg: Callable[[int], Any], qos: Any = 10) -> Any:
        pub = self.node.create_publisher(msg_type, topic, qos)
        counter = {'i': 0}

        def tick() -> None:
            pub.publish(make_msg(counter['i']))
            counter['i'] += 1
        return self.node.create_timer(1.0 / rate_hz, tick)

    def collector(self, msg_type: type, topic: str, qos: Any = 10) -> List[Any]:
        received: List[Any] = []

        def cb(msg: Any) -> None:
            with self._lock:
                received.append(msg)
        self.node.create_subscription(msg_type, topic, cb, qos)
        return received

    def close(self) -> None:
        self.executor.shutdown(timeout_sec=2.0)
        self.node.destroy_node()
        self.context.try_shutdown()
        self._thread.join(timeout=5.0)


@pytest.fixture
def helper():
    h = Helper()
    yield h
    h.close()


@pytest.fixture
def data_dir(tmp_path):
    d = tmp_path / 'data'
    d.mkdir()
    return d


WS_ROOT = os.environ.get('ROSHANAVI_TEST_WS', '/ws')


@pytest.fixture
def lab(data_dir, tmp_path):
    from roshanavi.lab import Lab
    instance = Lab(data_dir=str(data_dir), period_sec=0.2, workspace=WS_ROOT,
                   project_path=str(tmp_path / 'project' / 'roshanavi.yaml'),
                   stop_timeouts=(3.0, 2.0)).start()
    yield instance
    instance.stop()


@pytest.fixture
def client(lab):
    from fastapi.testclient import TestClient
    from roshanavi.server import create_app
    with TestClient(create_app(lab, static_dir=None, live_period=0.2),
                    base_url='http://localhost') as c:
        yield c
