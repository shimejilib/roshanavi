"""QoS compatibility between one publisher and one subscriber (pure functions).

Only "request vs offer" rules that make DDS refuse the match are checked:

- reliability: a BEST_EFFORT publisher cannot serve a RELIABLE subscriber.
- durability: a VOLATILE publisher cannot serve a TRANSIENT_LOCAL subscriber.
- deadline: the publisher's offered deadline must be <= the requested one.
- liveliness: AUTOMATIC publisher cannot serve a MANUAL_BY_TOPIC subscriber.
- liveliness lease: the publisher's lease must be <= the requested one.

Durations are milliseconds in the QoS dicts (``None`` = infinite / unset).
Each incompatibility is reported as ``{"policy", "pub", "sub"}`` with English
policy codes; the UI turns them into plain-language text.
"""

from typing import Any, Dict, List, Mapping, Optional

LIVELINESS_RANK = {'automatic': 0, 'manual_by_topic': 1}


def _finite(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _duration_offer_too_long(offered: Any, requested: Any) -> bool:
    """Offered must be <= requested. Infinite offered vs finite requested fails."""
    req = _finite(requested)
    if req is None:
        return False
    off = _finite(offered)
    return off is None or off > req


def incompatibilities(pub: Mapping[str, Any], sub: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Reasons why ``pub`` cannot deliver to ``sub`` (empty list = compatible)."""
    reasons: List[Dict[str, Any]] = []
    if pub.get('reliability') == 'best_effort' and sub.get('reliability') == 'reliable':
        reasons.append({'policy': 'reliability', 'pub': 'best_effort', 'sub': 'reliable'})
    if pub.get('durability') == 'volatile' and sub.get('durability') == 'transient_local':
        reasons.append({'policy': 'durability', 'pub': 'volatile', 'sub': 'transient_local'})
    if _duration_offer_too_long(pub.get('deadline_ms'), sub.get('deadline_ms')):
        reasons.append({'policy': 'deadline', 'pub': pub.get('deadline_ms'),
                        'sub': sub.get('deadline_ms')})
    pub_live = LIVELINESS_RANK.get(str(pub.get('liveliness')))
    sub_live = LIVELINESS_RANK.get(str(sub.get('liveliness')))
    if pub_live is not None and sub_live is not None and pub_live < sub_live:
        reasons.append({'policy': 'liveliness', 'pub': pub.get('liveliness'),
                        'sub': sub.get('liveliness')})
    if _duration_offer_too_long(pub.get('lease_ms'), sub.get('lease_ms')):
        reasons.append({'policy': 'liveliness_lease', 'pub': pub.get('lease_ms'),
                        'sub': sub.get('lease_ms')})
    return reasons


def incompatible_pairs(edges: List[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """All incompatible (publisher, subscriber) pairs per topic, sorted.

    ``edges`` use the graph snapshot shape ``{node, topic, dir, qos}``.
    """
    by_topic: Dict[str, Dict[str, List[Mapping[str, Any]]]] = {}
    for edge in edges:
        slot = by_topic.setdefault(edge['topic'], {'pub': [], 'sub': []})
        slot[edge['dir']].append(edge)
    pairs = []
    for topic in sorted(by_topic):
        for p in by_topic[topic]['pub']:
            for s in by_topic[topic]['sub']:
                reasons = incompatibilities(p.get('qos') or {}, s.get('qos') or {})
                if reasons:
                    pairs.append({'topic': topic, 'publisher': p['node'],
                                  'subscriber': s['node'], 'reasons': reasons})
    pairs.sort(key=lambda x: (x['topic'], x['publisher'], x['subscriber']))
    return pairs
