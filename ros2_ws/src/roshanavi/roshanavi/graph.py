"""ROS graph snapshot (nodes, topics, pub/sub edges with QoS).

``collect()`` queries rclpy once into a plain :class:`RawGraph`; the pure
function ``build_snapshot()`` turns it into the API shape. :class:`GraphMonitor`
caches the latest snapshot plus a content hash so WebSocket clients only get
the graph when it changed.
"""

import hashlib
import json
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from rclpy.exceptions import InvalidTopicNameException

from .diagnostics import diagnose
from .ros_runtime import RosRuntime, is_self_node, is_self_topic, qos_to_dict

LOG = logging.getLogger(__name__)
_REPORTED_BAD_TOPICS: set = set()


@dataclass(frozen=True)
class Endpoint:
    node: str  # fully qualified node name, e.g. "/ns/talker"
    qos: Dict[str, Any]


@dataclass(frozen=True)
class RawGraph:
    nodes: List[Tuple[str, str]] = field(default_factory=list)  # (name, namespace)
    topics: Dict[str, List[str]] = field(default_factory=dict)  # name -> types
    publishers: Dict[str, List[Endpoint]] = field(default_factory=dict)
    subscribers: Dict[str, List[Endpoint]] = field(default_factory=dict)
    lifecycle: Tuple[str, ...] = ()  # managed nodes (offer lifecycle_msgs get_state)


def fq_name(name: str, namespace: str) -> str:
    namespace = namespace or '/'
    return f'{namespace.rstrip("/")}/{name}'


def collect(runtime: RosRuntime) -> RawGraph:
    """Query the ROS graph once. Must be called with a running runtime."""
    topics = dict(runtime.topic_names_and_types())
    pubs: Dict[str, List[Endpoint]] = {}
    subs: Dict[str, List[Endpoint]] = {}
    for topic in list(topics):
        try:
            pubs[topic] = [_endpoint(i) for i in runtime.publishers_info(topic)]
            subs[topic] = [_endpoint(i) for i in runtime.subscriptions_info(topic)]
        except InvalidTopicNameException as exc:
            # One unqueryable name (DDS can carry names rclpy rejects) must not stop the graph.
            if topic not in _REPORTED_BAD_TOPICS and len(_REPORTED_BAD_TOPICS) < 100:
                _REPORTED_BAD_TOPICS.add(topic)
                LOG.warning('graph: skipping topic rclpy cannot query: %s', exc)
            topics.pop(topic)
            pubs.pop(topic, None)
    return RawGraph(nodes=list(runtime.node_names_and_namespaces()), topics=topics,
                    publishers=pubs, subscribers=subs,
                    lifecycle=tuple(lifecycle_nodes(runtime.service_names_and_types())))


GET_STATE_TYPE = 'lifecycle_msgs/srv/GetState'


def lifecycle_nodes(services: Iterable[Tuple[str, List[str]]]) -> List[str]:
    """Nodes that offer ``<node>/get_state`` of the lifecycle_msgs type (sorted)."""
    found = {name[:-len('/get_state')] for name, types in services
             if name.endswith('/get_state') and GET_STATE_TYPE in types}
    return sorted(n for n in found if n)


def _endpoint(info: Any) -> Endpoint:
    return Endpoint(node=fq_name(info.node_name, info.node_namespace),
                    qos=qos_to_dict(info.qos_profile))


def topic_is_live(raw: RawGraph, topic: str) -> bool:
    """A topic matters if it has any publisher or any non-self subscriber.

    Our own subscriptions (traffic/echo) must not keep a topic alive, otherwise
    a vanished topic would never be unsubscribed. Our own publishers (inject
    jobs) do count, so injected topics show up in traffic. The server <-> probe
    topics (``/roshanavi/_probe/...``) never matter.
    """
    if is_self_topic(topic):
        return False
    if raw.publishers.get(topic):
        return True
    return any(not is_self_node(e.node) for e in raw.subscribers.get(topic, []))


ROLE_OTHER = 'other'
ROLE_DUMMY = 'dummy'
DUMMY_PREFIX = 'dummy:'
DEFAULT_JOB_QOS = {'reliability': 'reliable', 'durability': 'volatile', 'history': 'keep_last',
                   'depth': 10, 'deadline_ms': None, 'liveliness': 'automatic',
                   'lease_ms': None}


def dummy_nodes(jobs: Iterable[Mapping[str, Any]]) -> Tuple[List[Dict[str, Any]],
                                                             List[Dict[str, Any]]]:
    """Virtual ``dummy`` sources for running inject jobs that publish one topic.

    Inject publishers belong to the roshanavi node itself (hidden by default),
    so each running job is drawn as its own node ``dummy:<job id>``.
    """
    nodes, edges = [], []
    for job in jobs:
        if job.get('state') != 'running' or not job.get('topic'):
            continue
        node_id = DUMMY_PREFIX + str(job['id'])
        nodes.append({'id': node_id, 'name': f"inject {job.get('mode')}", 'namespace': '',
                      'role': ROLE_DUMMY, 'job_id': job['id']})
        edges.append({'node': node_id, 'topic': job['topic'], 'dir': 'pub',
                      'qos': {**DEFAULT_JOB_QOS, **(job.get('qos') or {})}})
    return nodes, edges


def node_ids(raw: RawGraph) -> List[str]:
    """Fully qualified ids of real nodes, excluding roshanavi's own node."""
    return sorted({fq_name(name, namespace) for name, namespace in raw.nodes
                   if not is_self_node(fq_name(name, namespace))})


def build_snapshot(raw: RawGraph, show_self: bool = False,
                   jobs: Iterable[Mapping[str, Any]] = (),
                   node_info: Optional[Mapping[str, Mapping[str, Any]]] = None) -> Dict[str, Any]:
    """``node_info``: per node id ``{role, target_id, confidence}`` from the launcher."""
    nodes, seen = [], set()
    for name, namespace in sorted(raw.nodes, key=lambda n: fq_name(n[0], n[1])):
        node_id = fq_name(name, namespace)
        if node_id in seen or not (show_self or not is_self_node(node_id)):
            continue
        seen.add(node_id)
        info = (node_info or {}).get(node_id)
        node = {'id': node_id, 'name': name, 'namespace': namespace, 'role': ROLE_OTHER}
        if node_id in raw.lifecycle:
            node['lifecycle'] = True
        if info:
            node.update(role=info['role'], target_id=info['target_id'],
                        confidence=info['confidence'])
        nodes.append(node)
    topics, edges = [], []
    for topic in sorted(raw.topics):
        if not show_self and not topic_is_live(raw, topic):
            continue
        topics.append({'name': topic, 'types': list(raw.topics[topic])})
        for direction, endpoints in (('pub', raw.publishers), ('sub', raw.subscribers)):
            for ep in endpoints.get(topic, []):
                if show_self or not is_self_node(ep.node):
                    edges.append({'node': ep.node, 'topic': topic, 'dir': direction,
                                  'qos': dict(ep.qos)})
    known_topics = {t['name'] for t in topics}
    extra_nodes, extra_edges = dummy_nodes(jobs)
    nodes += extra_nodes
    edges += [e for e in extra_edges if e['topic'] in known_topics]
    edges.sort(key=lambda e: (e['node'], e['topic'], e['dir']))
    snapshot = {'nodes': nodes, 'topics': topics, 'edges': edges}
    snapshot['diagnostics'] = diagnose(snapshot)
    return snapshot


def snapshot_hash(snapshot: Dict[str, Any]) -> str:
    return hashlib.sha1(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()


class GraphMonitor:
    """Holds the latest raw graph + snapshot; refreshed by the housekeeping timer."""

    def __init__(self, show_self: bool = False):
        self._show_self = show_self
        self._lock = threading.Lock()
        self._raw = RawGraph()
        self._snapshot = build_snapshot(self._raw, show_self)
        self._hash = snapshot_hash(self._snapshot)

    def update(self, raw: RawGraph, jobs: Iterable[Mapping[str, Any]] = (),
               node_info: Optional[Mapping[str, Mapping[str, Any]]] = None) -> bool:
        """Store a new raw graph (+ running inject jobs, node roles). True when changed."""
        snapshot = build_snapshot(raw, self._show_self, jobs, node_info)
        digest = snapshot_hash(snapshot)
        with self._lock:
            changed = digest != self._hash
            self._raw, self._snapshot, self._hash = raw, snapshot, digest
        return changed

    def snapshot(self) -> Tuple[Dict[str, Any], str]:
        with self._lock:
            return self._snapshot, self._hash

    def raw(self) -> RawGraph:
        with self._lock:
            return self._raw
