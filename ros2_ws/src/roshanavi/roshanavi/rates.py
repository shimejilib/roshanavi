"""Per-publisher rates for map edges (pure functions).

Traffic statistics are per *topic*: rclpy Jazzy's ``MessageInfo`` has no
publisher gid, so we cannot tell which publisher sent a sample. What we do
know exactly is what roshanavi itself sends (inject jobs count their sends)
and, approximately, the configured rate of persistent dummy nodes. From that:

* known (dummy) publishers get their own rate (basis ``exact`` / ``configured``);
* if exactly one other publisher remains it gets ``max(0, total - known)``
  (basis ``estimated``; ``measured`` when it is the only publisher at all);
* with two or more other publishers no per-edge number is given
  (basis ``unknown``); the UI then shows the topic total and source count.
"""

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .ros_runtime import is_self_node
from .sub_rates import topic_subscribers

BASIS_EXACT = 'exact'
BASIS_CONFIGURED = 'configured'
BASIS_ESTIMATED = 'estimated'
BASIS_UNKNOWN = 'unknown'
BASIS_MEASURED = 'measured'  # the only publisher: the topic total is its rate


@dataclass(frozen=True)
class KnownRate:
    hz: float
    bps: Optional[float]
    basis: str = BASIS_EXACT


def _rate(hz: Optional[float], bps: Optional[float], basis: str) -> Dict[str, Any]:
    return {'hz': None if hz is None else round(hz, 3),
            'bps': None if bps is None else round(bps, 1), 'basis': basis}


def split_topic_rates(total_hz: Optional[float], total_bps: Optional[float],
                      publishers: Sequence[str],
                      known: Mapping[str, KnownRate]) -> Dict[str, Dict[str, Any]]:
    """``{publisher node: {hz, bps, basis}}`` for one topic."""
    result: Dict[str, Dict[str, Any]] = {}
    unknown = [p for p in publishers if p not in known]
    for node in publishers:
        if node in known:
            rate = known[node]
            result[node] = _rate(rate.hz, rate.bps, rate.basis)
    if len(unknown) != 1:
        for node in unknown:
            result[node] = _rate(None, None, BASIS_UNKNOWN)
        return result
    known_rates = [known[p] for p in publishers if p in known]
    hz = None if total_hz is None else max(0.0, total_hz - sum(r.hz for r in known_rates))
    bps = None
    if total_bps is not None and all(r.bps is not None for r in known_rates):
        bps = max(0.0, total_bps - sum(r.bps or 0.0 for r in known_rates))
    if hz is None:
        result[unknown[0]] = _rate(None, None, BASIS_UNKNOWN)
    elif not known_rates:
        result[unknown[0]] = _rate(hz, bps, BASIS_MEASURED)
    else:
        result[unknown[0]] = _rate(hz, bps, BASIS_ESTIMATED)
    return result


def publishers_by_topic(edges: Iterable[Mapping[str, Any]]) -> Dict[str, List[str]]:
    result: Dict[str, List[str]] = {}
    for edge in edges:
        if edge.get('dir') != 'pub' or is_self_node(str(edge.get('node', ''))):
            continue
        nodes = result.setdefault(edge['topic'], [])
        if edge['node'] not in nodes:
            nodes.append(edge['node'])
    return result


def annotate_traffic(entries: Sequence[Mapping[str, Any]], edges: Iterable[Mapping[str, Any]],
                     known: Mapping[str, KnownRate]) -> List[Dict[str, Any]]:
    """Copy of the traffic entries with ``publishers``, ``subscribers`` and ``source_count``."""
    edges = list(edges)
    pubs = publishers_by_topic(edges)
    result = []
    for entry in entries:
        topic_pubs = pubs.get(entry['topic'], [])
        monitored = entry.get('monitored') and entry.get('status') == 'ok'
        total_hz = entry.get('hz') if monitored else None
        total_bps = entry.get('bytes_per_sec') if monitored else None
        rates = split_topic_rates(total_hz, total_bps, topic_pubs, known)
        annotated = {**entry, 'source_count': len(topic_pubs),
                     'publishers': [{'node': n, **rates[n]} for n in topic_pubs]}
        annotated['subscribers'] = topic_subscribers(annotated, edges)
        result.append(annotated)
    return result


def known_rates(jobs: Iterable[Mapping[str, Any]], nodes: Iterable[Mapping[str, Any]],
                targets: Iterable[Mapping[str, Any]], dummy_prefix: str = 'dummy:'
                ) -> Dict[str, KnownRate]:
    """Rates roshanavi knows: running jobs (counted sends) and persistent dummies (config)."""
    known: Dict[str, KnownRate] = {}
    for job in jobs:
        if job.get('state') == 'running' and job.get('send_hz') is not None:
            known[dummy_prefix + str(job['id'])] = KnownRate(job['send_hz'], job.get('send_bps'))
    by_id = {t['id']: t for t in targets}
    for node in nodes:
        target = by_id.get(node.get('target_id') or '')
        if node.get('role') != 'dummy' or target is None or target.get('status') != 'running':
            continue
        spec = target.get('spec') or {}
        if spec.get('mode') in ('periodic', 'stream', 'media') and spec.get('rate_hz'):
            known[node['id']] = KnownRate(float(spec['rate_hz']), None, BASIS_CONFIGURED)
    return known
