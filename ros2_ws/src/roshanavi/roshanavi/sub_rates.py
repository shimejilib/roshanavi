"""Theoretical per-subscriber rates for the traffic table (pure, DESIGN §6.7).

roshanavi measures traffic per *topic* with its own subscription; what a given
subscriber really receives is not visible from outside. The theoretical value
is what the QoS-compatible publishers send:

* every publisher compatible -> the topic total (``theoretical``);
* only some compatible -> the sum of their per-publisher rates (rates.py),
  ``None`` when one of them cannot be split out;
* none compatible -> 0 with ``delivered: false`` (``not_delivered``).

``basis`` is a plain string so a later tracing probe can report ``measured``.
"""

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .qos_compat import incompatibilities
from .ros_runtime import is_self_node

BASIS_THEORETICAL = 'theoretical'
BASIS_NOT_DELIVERED = 'not_delivered'


def _round(value: Optional[float], digits: int) -> Optional[float]:
    return None if value is None else round(value, digits)


def _sum(values: Sequence[Optional[float]]) -> Optional[float]:
    return None if any(v is None for v in values) else float(sum(v or 0.0 for v in values))


def subscriber_rate(sub_qos: Mapping[str, Any], pub_edges: Sequence[Mapping[str, Any]],
                    pub_rates: Mapping[str, Mapping[str, Any]], total_hz: Optional[float],
                    total_bps: Optional[float]) -> Dict[str, Any]:
    """``{hz, bps, basis, delivered, sources}`` for one subscriber of one topic."""
    sources = [e['node'] for e in pub_edges if not incompatibilities(e.get('qos') or {}, sub_qos)]
    if pub_edges and not sources:
        return {'hz': 0.0, 'bps': 0.0, 'basis': BASIS_NOT_DELIVERED, 'delivered': False,
                'sources': []}
    if len(sources) == len(pub_edges):
        hz, bps = total_hz, total_bps
    else:
        hz = _sum([pub_rates.get(n, {}).get('hz') for n in sources])
        bps = _sum([pub_rates.get(n, {}).get('bps') for n in sources])
    return {'hz': _round(hz, 3), 'bps': _round(bps, 1), 'basis': BASIS_THEORETICAL,
            'delivered': True, 'sources': sources}


def topic_subscribers(entry: Mapping[str, Any], edges: Iterable[Mapping[str, Any]]
                      ) -> List[Dict[str, Any]]:
    """``subscribers[]`` of one annotated traffic entry (needs ``publishers[]``)."""
    topic = entry['topic']
    own = [e for e in edges if e.get('topic') == topic and not is_self_node(str(e.get('node')))]
    pub_edges = [e for e in own if e.get('dir') == 'pub']
    pub_rates = {p['node']: p for p in entry.get('publishers') or []}
    monitored = entry.get('monitored') and entry.get('status') == 'ok'
    total_hz = entry.get('hz') if monitored else None
    total_bps = entry.get('bytes_per_sec') if monitored else None
    result, seen = [], set()
    for edge in own:
        if edge.get('dir') != 'sub' or edge['node'] in seen:
            continue
        seen.add(edge['node'])
        result.append({'node': edge['node'], **subscriber_rate(
            edge.get('qos') or {}, pub_edges, pub_rates, total_hz, total_bps)})
    return result
