"""rclpy runtime: one ``roshanavi`` node spun by a MultiThreadedExecutor thread.

Thread-safety model
-------------------
Two worlds touch ROS:

1. **Executor thread** (daemon, owned by :class:`RosRuntime`): runs every rclpy
   callback — the 1 s housekeeping timer (graph refresh, traffic discovery,
   hz-history tick), raw traffic subscriptions, echo subscriptions and
   injector timers.
2. **asyncio / FastAPI threads**: request handlers and WebSocket loops.

Rules that keep this safe:

- All rclpy entity creation/destruction and graph queries go through the
  facade methods of :class:`RosRuntime`, which serialize on one ``RLock``.
  rclpy itself tolerates entity creation while the executor waits (the wait
  set is rebuilt every iteration and destruction is deferred with
  ``destroy_when_not_in_use``), the lock just keeps *our* callers from
  interleaving create/destroy on the same node.
- Subscription callbacks only update small in-memory state objects
  (traffic stats, echo latest message) that have their **own** locks and
  never call back into rclpy. They therefore stay cheap and never block.
- The asyncio side never waits on the executor: it reads cached snapshots
  (graph, traffic, jobs) that the executor thread publishes under those
  module locks. Facade calls are short and non-blocking.
- Lock ordering: the runtime lock is a *leaf* lock. Code holding it only
  calls rclpy, never module code, so module locks may be held while calling
  the facade without risk of deadlock. Conversely, job locks are released
  before tearing down entities so teardown never blocks a running callback.

Each runtime owns its own ``rclpy.Context``, so several runtimes (e.g. in tests)
can live in one process and be shut down independently.
"""

import logging
import threading
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import rclpy
from rclpy.callback_groups import CallbackGroup
from rclpy.context import Context
from rclpy.event_handler import SubscriptionEventCallbacks
from rclpy.executors import ExternalShutdownException, MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from rclpy.signals import SignalHandlerOptions

LOG = logging.getLogger(__name__)

SELF_NODE_PREFIX = 'roshanavi'
DEFAULT_DEPTH = 10
# Jazzy registers a default incompatible-QoS event handler per subscription. Observed with
# it: when this node's raw traffic subscription and one of its own publishers (injected
# media, dummy nodes) share a topic, the executor's wait() keeps returning at once with
# nothing to take, so the executor thread busy-loops in Python (3000+ wait-set rebuilds per
# second) and holds the GIL, delaying every other thread's wake-up by 50-250 ms
# (docs/design/input-and-media.md, pacing). We register no event handlers.
NO_SUBSCRIPTION_EVENTS = SubscriptionEventCallbacks(use_default_callbacks=False)


# Internal topics between the server and its measurement probe (never shown or measured).
SELF_TOPIC_PREFIX = '/roshanavi/_probe/'


def is_self_node(name: str) -> bool:
    return name.lstrip('/').split('/')[-1].startswith(SELF_NODE_PREFIX)


def is_self_topic(topic: str) -> bool:
    return topic.startswith(SELF_TOPIC_PREFIX)


# rmw_fastrtps_cpp on Lyrical (rosidl_buffer backends) adds a hidden companion topic
# ``<topic>/_buf_<backend>`` (endpoint node ``_NODE_NAME_UNKNOWN_``) next to a C++ subscription
# of a type with byte arrays. Subscribing to the companion makes another one
# (``/a/_buf_cpu/_buf_cpu`` ...), one level per probe update, until the name is too long for
# rclpy. They are transport internals: never listed, shown or subscribed.
RMW_COMPANION_TOKEN_PREFIX = '_buf_'


def is_rmw_internal_topic(topic: str) -> bool:
    return any(token.startswith(RMW_COMPANION_TOKEN_PREFIX) for token in topic.split('/'))


def make_qos(reliability: str = 'reliable', durability: str = 'volatile',
             depth: int = DEFAULT_DEPTH) -> QoSProfile:
    """Build a QoSProfile from lowercase policy names."""
    rel = {'reliable': ReliabilityPolicy.RELIABLE,
           'best_effort': ReliabilityPolicy.BEST_EFFORT}.get(reliability)
    dur = {'volatile': DurabilityPolicy.VOLATILE,
           'transient_local': DurabilityPolicy.TRANSIENT_LOCAL}.get(durability)
    if rel is None or dur is None:
        raise ValueError(f'unsupported qos: reliability={reliability} durability={durability}')
    return QoSProfile(history=HistoryPolicy.KEEP_LAST, depth=int(depth),
                      reliability=rel, durability=dur)


def compatible_sub_qos(publisher_reliabilities: Iterable[ReliabilityPolicy]) -> QoSProfile:
    """BEST_EFFORT if any publisher is best-effort, else RELIABLE; VOLATILE, depth 10."""
    best_effort = any(r == ReliabilityPolicy.BEST_EFFORT for r in publisher_reliabilities)
    return make_qos('best_effort' if best_effort else 'reliable', 'volatile', DEFAULT_DEPTH)


def qos_to_dict(qos: QoSProfile) -> Dict[str, Any]:
    def name(policy: Any) -> str:
        return policy.name.lower() if hasattr(policy, 'name') else str(policy)
    return {'reliability': name(qos.reliability), 'durability': name(qos.durability),
            'history': name(qos.history), 'depth': int(qos.depth),
            'deadline_ms': duration_ms(getattr(qos, 'deadline', None)),
            'liveliness': name(getattr(qos, 'liveliness', 'unknown')),
            'lease_ms': duration_ms(getattr(qos, 'liveliness_lease_duration', None))}


INFINITE_NS = 2 ** 31 * 10 ** 9  # RMW reports "infinite" as huge values (~68 years+)


def duration_ms(duration: Any) -> Optional[float]:
    """rclpy Duration -> milliseconds; None when unset (0) or infinite."""
    ns = getattr(duration, 'nanoseconds', None)
    if not isinstance(ns, int) or ns <= 0 or ns >= INFINITE_NS:
        return None
    return ns / 1e6


class RosRuntime:
    """Owns the rclpy context, the ``roshanavi`` node and the executor thread."""

    def __init__(self, node_name: str = 'roshanavi', num_threads: int = 4,
                 require_self_name: bool = True):
        # The server's own node must be recognisable (hidden from the graph);
        # persistent dummy nodes (dummy_node.py) are meant to be seen.
        if require_self_name and not is_self_node(node_name):
            raise ValueError(f'node name must start with {SELF_NODE_PREFIX!r}')
        self._node_name = node_name
        self._num_threads = num_threads
        self._lock = threading.RLock()
        self._context: Optional[Context] = None
        self._node: Optional[Node] = None
        self._executor: Optional[MultiThreadedExecutor] = None
        self._thread: Optional[threading.Thread] = None

    # ---- lifecycle -------------------------------------------------------
    def start(self) -> None:
        with self._lock:
            if self._node is not None:
                return
            self._context = Context()
            # The host process (uvicorn / pytest) owns signal handling.
            rclpy.init(context=self._context, signal_handler_options=SignalHandlerOptions.NO)
            self._node = Node(self._node_name, context=self._context)
            self._executor = MultiThreadedExecutor(num_threads=self._num_threads,
                                                   context=self._context)
            self._executor.add_node(self._node)
            self._thread = threading.Thread(target=self._spin, name='roshanavi-executor',
                                            daemon=True)
            self._thread.start()
            LOG.info('ROS runtime started (node=%s)', self._node_name)

    def _spin(self) -> None:
        executor = self._executor
        try:
            executor.spin()
        except ExternalShutdownException:
            LOG.debug('executor stopped by context shutdown')
        except Exception:  # keep the reason visible; the thread dies otherwise
            LOG.exception('executor thread crashed')

    def stop(self) -> None:
        with self._lock:
            if self._node is None:
                return
            node, executor = self._node, self._executor
            context, thread = self._context, self._thread
            self._node = self._executor = self._context = self._thread = None
        executor.shutdown(timeout_sec=2.0)
        node.destroy_node()
        if context.ok():
            context.try_shutdown()
        thread.join(timeout=5.0)
        LOG.info('ROS runtime stopped')

    @property
    def node(self) -> Node:
        if self._node is None:
            raise RuntimeError('ROS runtime is not started')
        return self._node

    @property
    def running(self) -> bool:
        return self._node is not None

    # ---- entity facade ---------------------------------------------------
    def create_timer(self, period_sec: float, callback: Callable[[], None],
                     group: Optional[CallbackGroup] = None) -> Any:
        with self._lock:
            return self.node.create_timer(period_sec, callback, callback_group=group)

    def destroy_timer(self, timer: Any) -> None:
        with self._lock:
            if self._node is not None:
                timer.cancel()
                self._node.destroy_timer(timer)

    def create_publisher(self, msg_type: type, topic: str, qos: QoSProfile) -> Any:
        with self._lock:
            return self.node.create_publisher(msg_type, topic, qos)

    def destroy_publisher(self, publisher: Any) -> None:
        with self._lock:
            if self._node is not None:
                self._node.destroy_publisher(publisher)

    def create_subscription(self, msg_type: type, topic: str, callback: Callable[[Any], None],
                            qos: QoSProfile, raw: bool = False,
                            group: Optional[CallbackGroup] = None) -> Any:
        with self._lock:
            return self.node.create_subscription(msg_type, topic, callback, qos, raw=raw,
                                                 callback_group=group,
                                                 event_callbacks=NO_SUBSCRIPTION_EVENTS)

    def destroy_subscription(self, subscription: Any) -> None:
        with self._lock:
            if self._node is not None:
                self._node.destroy_subscription(subscription)

    def create_client(self, srv_type: type, service: str,
                      group: Optional[CallbackGroup] = None) -> Any:
        with self._lock:
            return self.node.create_client(srv_type, service, callback_group=group)

    def destroy_client(self, client: Any) -> None:
        with self._lock:
            if self._node is not None:
                self._node.destroy_client(client)

    # ---- graph queries ---------------------------------------------------
    def node_names_and_namespaces(self) -> List[Tuple[str, str]]:
        with self._lock:
            return self.node.get_node_names_and_namespaces()

    def service_names_and_types(self) -> List[Tuple[str, List[str]]]:
        with self._lock:
            return self.node.get_service_names_and_types()

    def topic_names_and_types(self) -> List[Tuple[str, List[str]]]:
        """All topics except rmw-internal companions (:func:`is_rmw_internal_topic`)."""
        with self._lock:
            found = self.node.get_topic_names_and_types()
        return [(name, types) for name, types in found if not is_rmw_internal_topic(name)]

    def publishers_info(self, topic: str) -> List[Any]:
        with self._lock:
            return self.node.get_publishers_info_by_topic(topic)

    def subscriptions_info(self, topic: str) -> List[Any]:
        with self._lock:
            return self.node.get_subscriptions_info_by_topic(topic)

    def subscription_qos_for(self, topic: str) -> QoSProfile:
        pubs = self.publishers_info(topic)
        return compatible_sub_qos(p.qos_profile.reliability for p in pubs)
