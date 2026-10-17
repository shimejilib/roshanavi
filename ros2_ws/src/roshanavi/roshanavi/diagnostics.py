"""Beginner-oriented warnings derived from a graph snapshot (pure functions).

Each diagnostic is a plain dict with an English ``code`` and machine-readable
``detail``; the web UI renders the sentence (Japanese by default):

- ``qos_incompatible``: a pub/sub pair on one topic that DDS will not connect.
- ``no_subscriber`` / ``no_publisher``: a topic with only one side.
- ``similar_names``: a pub-only topic and a sub-only topic whose names differ
  only slightly (likely typo / missing remap).
- ``type_mismatch``: one topic name advertised with several types.

Hidden topics (a segment starting with ``_``), ``/rosout``, ``/parameter_events`` and
rosbag2's own ``/events/write_split`` never produce one-sided warnings.
"""

from typing import Any, Dict, Iterable, List, Mapping, Set, Tuple

from .qos_compat import incompatible_pairs

# ``/events/write_split`` is published by ``ros2 bag record`` itself while roshanavi records.
INFRA_TOPICS = frozenset({'/rosout', '/parameter_events', '/events/write_split'})
SEVERITY_ORDER = {'error': 0, 'warning': 1, 'info': 2}
SHORT_NAME_LEN = 4  # names this short only tolerate one edit


def is_hidden_topic(topic: str) -> bool:
    return topic in INFRA_TOPICS or any(seg.startswith('_') for seg in topic.split('/') if seg)


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


def _sides(snapshot: Mapping[str, Any]) -> Dict[str, Tuple[Set[str], Set[str]]]:
    sides: Dict[str, Tuple[Set[str], Set[str]]] = {
        t['name']: (set(), set()) for t in snapshot.get('topics', [])}
    for edge in snapshot.get('edges', []):
        pubs, subs = sides.setdefault(edge['topic'], (set(), set()))
        (pubs if edge['dir'] == 'pub' else subs).add(edge['node'])
    return sides


def _diag(code: str, severity: str, topic: str, nodes: Iterable[str],
          detail: Dict[str, Any]) -> Dict[str, Any]:
    return {'code': code, 'severity': severity, 'topic': topic,
            'nodes': sorted(nodes), 'detail': detail}


def _qos_diags(snapshot: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return [_diag('qos_incompatible', 'error', p['topic'], [p['publisher'], p['subscriber']],
                  {'publisher': p['publisher'], 'subscriber': p['subscriber'],
                   'reasons': p['reasons']})
            for p in incompatible_pairs(snapshot.get('edges', []))]


def _one_sided(sides: Mapping[str, Tuple[Set[str], Set[str]]]
               ) -> Tuple[List[str], List[str]]:
    pub_only, sub_only = [], []
    for topic, (pubs, subs) in sorted(sides.items()):
        if is_hidden_topic(topic) or (not pubs and not subs):
            continue
        if pubs and not subs:
            pub_only.append(topic)
        elif subs and not pubs:
            sub_only.append(topic)
    return pub_only, sub_only


def _side_diags(sides: Mapping[str, Tuple[Set[str], Set[str]]]) -> List[Dict[str, Any]]:
    pub_only, sub_only = _one_sided(sides)
    result = [_diag('no_subscriber', 'warning', t, sides[t][0], {}) for t in pub_only]
    result += [_diag('no_publisher', 'warning', t, sides[t][1], {}) for t in sub_only]
    for pub_topic in pub_only:
        for sub_topic in sub_only:
            if names_similar(pub_topic, sub_topic):
                result.append(_diag('similar_names', 'warning', pub_topic,
                                    sides[pub_topic][0] | sides[sub_topic][1],
                                    {'published': pub_topic, 'subscribed': sub_topic}))
    return result


def _type_diags(snapshot: Mapping[str, Any]) -> List[Dict[str, Any]]:
    return [_diag('type_mismatch', 'error', t['name'], [], {'types': sorted(t['types'])})
            for t in snapshot.get('topics', []) if len(set(t.get('types', []))) > 1]


def diagnose(snapshot: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """All diagnostics for a snapshot, most severe first, deterministic order."""
    sides = _sides(snapshot)
    items = _qos_diags(snapshot) + _type_diags(snapshot) + _side_diags(sides)
    items.sort(key=lambda d: (SEVERITY_ORDER[d['severity']], d['code'], d['topic'],
                              d['nodes']))
    return items
