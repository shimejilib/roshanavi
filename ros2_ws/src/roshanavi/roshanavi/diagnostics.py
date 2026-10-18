"""Beginner-oriented warnings derived from a graph snapshot (pure functions).

Each diagnostic is a plain dict with an English ``code`` and machine-readable
``detail``; the web UI renders the sentence (Japanese by default):

- ``qos_incompatible``: a pub/sub pair on one topic that DDS will not connect.
- ``type_mismatch``: one topic name advertised with several types.
- ``similar_names``: a topic with only one side whose name differs only slightly from a
  topic the other side uses (likely typo / missing remap), also when that other topic is
  perfectly connected (``/chater`` published while the listener hears ``/chatter``).
- ``no_subscriber`` / ``no_publisher``: a topic with only one side. Severity ``info``: the UI
  shows it quietly on the map and in the topic / node details and does not count it in the
  diagnostics badge (a sensor nobody listens to yet is normal while building a system).

The time-dependent warnings (``subscriber_lost`` / ``publisher_lost`` / ``mine_no_input``)
need memory of earlier snapshots and live in :mod:`roshanavi.diag_history`.

Infrastructure never produces one-sided diagnostics and never counts as an endpoint: hidden
topics (a segment starting with ``_``, e.g. ``/x/_action/status``), ``/rosout``,
``/parameter_events``, rosbag2's ``/events/write_split``, lifecycle ``*/transition_event``,
and infrastructure nodes: hidden nodes (a name starting with ``_``: the ``ros2`` CLI daemon
``_ros2cli_daemon_*`` and the transient ``_ros2cli_*`` nodes of ``ros2 topic echo`` and
friends) and roshanavi's own nodes (its viewers, echo and probe are not the user's subscribers).
"""

from typing import Any, Collection, Dict, Iterable, List, Mapping, Set, Tuple

from .qos_compat import incompatible_pairs
from .ros_runtime import is_self_node

# ``/events/write_split`` is published by ``ros2 bag record`` itself while roshanavi records.
INFRA_TOPICS = frozenset({'/rosout', '/parameter_events', '/events/write_split'})
# Every lifecycle node publishes ``<node>/transition_event``.
LIFECYCLE_EVENT_SEGMENT = 'transition_event'
SEVERITY_ORDER = {'error': 0, 'warning': 1, 'info': 2}
SHORT_NAME_LEN = 4  # names this short only tolerate one edit

Sides = Dict[str, Tuple[Set[str], Set[str]]]


def is_hidden_topic(topic: str) -> bool:
    """Infrastructure topics (shown only with the 内部トピック toggle off)."""
    segments = [seg for seg in topic.split('/') if seg]
    return (topic in INFRA_TOPICS or any(seg.startswith('_') for seg in segments)
            or (len(segments) > 1 and segments[-1] == LIFECYCLE_EVENT_SEGMENT))


def is_hidden_node(node: str) -> bool:
    """ROS hides nodes whose name starts with ``_`` (``_ros2cli_daemon_0_...``, ``_ros2cli_123``)."""
    return node.rsplit('/', 1)[-1].startswith('_')


def is_infra_node(node: str) -> bool:
    """Not a user's node: hidden by ROS convention, or roshanavi itself."""
    return is_hidden_node(node) or is_self_node(node)


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def _normalize(name: str) -> str:
    return name.replace('_', '').replace('-', '').lower()


def names_similar(a: str, b: str) -> bool:
    """True for likely typos: same namespace and a small edit on the last segment,
    or identical after dropping ``_``/``-`` and case."""
    if a == b:
        return False
    if _normalize(a) == _normalize(b):
        return True
    ns_a, _, last_a = a.rpartition('/')
    ns_b, _, last_b = b.rpartition('/')
    if ns_a != ns_b or not last_a or not last_b:
        return False
    longest = max(len(last_a), len(last_b))
    limit = 1 if longest <= SHORT_NAME_LEN else 2
    return levenshtein(last_a, last_b) <= limit


def topic_sides(snapshot: Mapping[str, Any], quiet_topics: Collection[str] = ()) -> Sides:
    """Per topic ``(publisher nodes, subscriber nodes)``, infrastructure nodes left out.

    ``quiet_topics`` (class nodes' action topics: subscribed, nobody publishes until a button is
    pressed) are left out entirely, so no one-sided or lost warning can mention them."""
    quiet = frozenset(quiet_topics)
    sides: Sides = {t['name']: (set(), set()) for t in snapshot.get('topics', [])
                    if t['name'] not in quiet}
    for edge in snapshot.get('edges', []):
        if is_infra_node(edge['node']) or edge['topic'] in quiet:
            continue
        pubs, subs = sides.setdefault(edge['topic'], (set(), set()))
        (pubs if edge['dir'] == 'pub' else subs).add(edge['node'])
    return sides


def make_diag(code: str, severity: str, topic: str, nodes: Iterable[str],
          detail: Dict[str, Any]) -> Dict[str, Any]:
    return {'code': code, 'severity': severity, 'topic': topic,
            'nodes': sorted(nodes), 'detail': detail}


def _qos_diags(snapshot: Mapping[str, Any]) -> List[Dict[str, Any]]:
    edges = [e for e in snapshot.get('edges', []) if not is_infra_node(e['node'])]
    return [make_diag('qos_incompatible', 'error', p['topic'], [p['publisher'], p['subscriber']],
                  {'publisher': p['publisher'], 'subscriber': p['subscriber'],
                   'reasons': p['reasons']})
            for p in incompatible_pairs(edges)]


def one_sided(sides: Mapping[str, Tuple[Set[str], Set[str]]]
              ) -> Tuple[List[str], List[str]]:
    """``(publish-only topics, subscribe-only topics)``, hidden topics left out."""
    pub_only, sub_only = [], []
    for topic, (pubs, subs) in sorted(sides.items()):
        if is_hidden_topic(topic) or (not pubs and not subs):
            continue
        if pubs and not subs:
            pub_only.append(topic)
        elif subs and not pubs:
            sub_only.append(topic)
    return pub_only, sub_only


def _similar_diags(sides: Mapping[str, Tuple[Set[str], Set[str]]], pub_only: List[str],
                   sub_only: List[str]) -> List[Dict[str, Any]]:
    """One-sided topic A vs any other visible topic B that the missing side uses.

    A publish-only ``/chater`` next to a subscribed ``/chatter``, or a subscribe-only
    ``/chatter`` next to a published ``/chater``. A pair is reported once (when both topics are
    one-sided the pair would match from both directions); ``topic`` is the one-sided one
    (the publish-only one of such a pair).
    """
    visible = [t for t in sorted(sides) if not is_hidden_topic(t)]
    found: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for topic in pub_only:
        for other in visible:
            if sides[other][1] and names_similar(topic, other):
                found.setdefault((topic, other), make_diag(
                    'similar_names', 'warning', topic, sides[topic][0] | sides[other][1],
                    {'published': topic, 'subscribed': other}))
    for topic in sub_only:
        for other in visible:
            if sides[other][0] and names_similar(other, topic):
                found.setdefault((other, topic), make_diag(
                    'similar_names', 'warning', topic, sides[other][0] | sides[topic][1],
                    {'published': other, 'subscribed': topic}))
    return list(found.values())


def _side_diags(sides: Mapping[str, Tuple[Set[str], Set[str]]]) -> List[Dict[str, Any]]:
    pub_only, sub_only = one_sided(sides)
    result = [make_diag('no_subscriber', 'info', t, sides[t][0], {}) for t in pub_only]
    result += [make_diag('no_publisher', 'info', t, sides[t][1], {}) for t in sub_only]
    return result + _similar_diags(sides, pub_only, sub_only)


def _type_diags(snapshot: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return [make_diag('type_mismatch', 'error', t['name'], [], {'types': sorted(t['types'])})
            for t in snapshot.get('topics', []) if len(set(t.get('types', []))) > 1]


def sort_diagnostics(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Most severe first, deterministic order."""
    return sorted(items, key=lambda d: (SEVERITY_ORDER[d['severity']], d['code'], d['topic'],
                                        d['nodes']))


def diagnose(snapshot: Mapping[str, Any], quiet_topics: Collection[str] = ()
             ) -> List[Dict[str, Any]]:
    """All stateless diagnostics for a snapshot, most severe first, deterministic order.

    ``quiet_topics`` are one-sided on purpose (a class node's action topics: nobody publishes
    until a button is pressed); they are treated as not existing for every one-sided diagnostic."""
    sides = topic_sides(snapshot, quiet_topics)
    return sort_diagnostics(_qos_diags(snapshot) + _type_diags(snapshot) + _side_diags(sides))
