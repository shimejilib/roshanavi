"""Call another node's ROS services from the roshanavi node, with timeouts everywhere.

Shared by the parameter client (:mod:`params`) and the lifecycle client
(:mod:`lifecycle`). Clients live in a Reentrant callback group and are kept in a
small LRU cache keyed by service name. Waiting for the service and waiting for
the response each have a timeout, so an unresponsive node can never hang an API
request. Failures become :class:`ApiError` with domain-specific codes.
"""

import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Optional

from rclpy.callback_groups import ReentrantCallbackGroup

from .api_errors import ApiError
from .ros_runtime import RosRuntime

LOG = logging.getLogger(__name__)

MAX_CACHED_CLIENTS = 24


@dataclass(frozen=True)
class ServiceErrors:
    """Error codes (and the noun used in messages) of one service family."""
    unavailable: str
    timeout: str
    failed: str
    what: str


class ServiceCaller:
    """Thread-safe cached clients + ``call()`` with a timeout on every step."""

    def __init__(self, runtime: RosRuntime, errors: ServiceErrors, timeout_sec: float,
                 max_clients: int = MAX_CACHED_CLIENTS):
        self._runtime = runtime
        self._errors = errors
        self.timeout_sec = timeout_sec
        self._max = max_clients
        self._group = ReentrantCallbackGroup()
        self._lock = threading.Lock()
        self._clients: 'OrderedDict[str, Any]' = OrderedDict()

    def _client(self, srv_type: type, service: str) -> Any:
        with self._lock:
            client = self._clients.pop(service, None)
            if client is None:
                client = self._runtime.create_client(srv_type, service, group=self._group)
            self._clients[service] = client
            evicted = []
            while len(self._clients) > self._max:
                evicted.append(self._clients.popitem(last=False)[1])
        for old in evicted:
            self._runtime.destroy_client(old)
        return client

    def call(self, node: str, suffix: str, srv_type: type, request: Any,
             timeout_sec: Optional[float] = None, retries: int = 0) -> Any:
        """Call ``<node>/<suffix>``; ApiError 504 on timeouts, 502 on transport errors.

        ``retries`` extra attempts are made when the node did not answer in time. Use it only for
        reads: a timed-out write may still have been applied.
        """
        for attempt in range(retries + 1):
            try:
                return self._call_once(node, suffix, srv_type, request, timeout_sec)
            except ApiError as exc:
                if exc.code != self._errors.timeout or attempt == retries:
                    raise
                LOG.info('%s on %s timed out, retrying', suffix, node)
        raise AssertionError('unreachable')  # pragma: no cover

    def _call_once(self, node: str, suffix: str, srv_type: type, request: Any,
                   timeout_sec: Optional[float]) -> Any:
        timeout = self.timeout_sec if timeout_sec is None else timeout_sec
        errors = self._errors
        client = self._client(srv_type, f'{node}/{suffix}')
        if not client.wait_for_service(timeout_sec=timeout):
            raise ApiError(errors.unavailable,
                           f'{node} does not answer {errors.what} requests ({suffix})', 504)
        future = client.call_async(request)
        done = threading.Event()
        future.add_done_callback(lambda _f: done.set())
        if not done.wait(timeout):
            future.cancel()
            raise ApiError(errors.timeout, f'{node} did not answer within {timeout:g} s '
                           f'({suffix})', 504)
        try:
            result = future.result()
        except Exception as exc:  # rclpy surfaces transport failures here
            raise ApiError(errors.failed, f'{suffix} on {node} failed: {exc}', 502) from exc
        if result is None:
            raise ApiError(errors.failed, f'{suffix} on {node} returned nothing', 502)
        return result

    def close(self) -> None:
        with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for client in clients:
            self._runtime.destroy_client(client)
