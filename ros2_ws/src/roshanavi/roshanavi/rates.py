"""Per-publisher rates for map edges and the traffic table (pure functions).

With the C++ probe (``entry['measurement'] == 'probe'``) every publisher's
messages are counted separately (``MessageInfo.publisher_gid`` matched to the
graph's ``endpoint_gid``), so each publisher node gets its own ``measured``
rate. Our own inject jobs keep their counted send rate (``exact``).

Without per-publisher data (Python fallback: rclpy Jazzy's ``MessageInfo`` has
no publisher gid, and Lyrical's is not used for splitting yet; or an RMW whose
gids do not match the graph, e.g. Cyclone DDS) the topic total is split from
what roshanavi knows:

* known (dummy) publishers get their own rate (basis ``exact`` / ``configured``);
* if exactly one other publisher remains it gets ``max(0, total - known)``
  (basis ``estimated``; ``measured`` when it is the only publisher at all);
* with two or more other publishers no per-edge number is given
  (basis ``unknown``); the UI then shows the topic total and source count.

A topic that is not measured at all (``status: not_monitored``, e.g. images by default) is not
"unknown": its publishers get basis ``not_monitored`` (roshanavi did not look), and 詳細計測モード
can fill in the send rate from the trace (tracing/merge.py). ``heavy`` tells the UI whether
the type is one that is off by default.
"""

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .graph import DUMMY_PREFIX
from .heavy_types import is_heavy
from .ros_runtime import is_self_node
from .sub_rates import topic_subscribers

BASIS_EXACT = 'exact'
BASIS_CONFIGURED = 'configured'
BASIS_ESTIMATED = 'estimated'
BASIS_UNKNOWN = 'unknown'
BASIS_MEASURED = 'measured'  # counted per publisher by the probe, or the only publisher
BASIS_NOT_MONITORED = 'not_monitored'  # the topic is not measured (not a limit of measuring)
MEASUREMENT_PROBE = 'probe'


@dataclass(frozen=True)
class KnownRate:
    hz: float
    bps: Optional[float]
    basis: str = BASIS_EXACT


def _rate(hz: Optional[float], bps: Optional[float], basis: str) -> Dict[str, Any]:
    return {'hz': None if hz is None else round(hz, 3),
            'bps': None if bps is None else round(bps, 1), 'basis': basis}


def measured_rates(entry: Mapping[str, Any]) -> Optional[Dict[str, KnownRate]]:
    """Per-node publish rates counted by the probe; None when not measured per publisher.

    None also when a publisher gid could not be matched to a graph endpoint (the
    RMW reports different ids, e.g. Cyclone DDS): the topic split is used then.
    """
    if entry.get('measurement') != MEASUREMENT_PROBE or entry.get('status') != 'ok' \
            or not entry.get('monitored'):
        return None
    endpoints = entry.get('endpoints') or []
    if any(not ep.get('resolved') for ep in endpoints):
        return None
    result: Dict[str, KnownRate] = {}
    for ep in endpoints:
        prev = result.get(ep['node'])
        hz = float(ep['hz']) + (prev.hz if prev else 0.0)
        bps = float(ep['bps']) + (prev.bps or 0.0 if prev else 0.0)
        result[ep['node']] = KnownRate(hz, bps, BASIS_MEASURED)
    return result


def _split_measured(publishers: Sequence[str], known: Mapping[str, KnownRate],
                    measured: Mapping[str, KnownRate]) -> Dict[str, Dict[str, Any]]:
    """Probe path: measured per node; inject jobs keep ``exact`` (counted sends).

    A job without a counted rate yet gets roshanavi's own measured rate when it
    is the only such job on the topic (its publisher belongs to our node).
    """
    own = [r for node, r in measured.items() if is_self_node(node)]
    uncounted = [p for p in publishers if p.startswith(DUMMY_PREFIX) and p not in known]
    result: Dict[str, Dict[str, Any]] = {}
    for node in publishers:
        rate = known.get(node)
        if rate is not None and rate.basis == BASIS_EXACT:
            result[node] = _rate(rate.hz, rate.bps, rate.basis)
        elif node in measured:
            result[node] = _rate(measured[node].hz, measured[node].bps, BASIS_MEASURED)
        elif node in uncounted:
            single = len(uncounted) == 1 and len(own) == 1
            result[node] = (_rate(own[0].hz, own[0].bps, BASIS_MEASURED) if single
                            else _rate(None, None, BASIS_UNKNOWN))
        else:  # the probe sees every publisher; nothing received means nothing sent
            result[node] = _rate(0.0, 0.0, BASIS_MEASURED)
    return result


def split_topic_rates(total_hz: Optional[float], total_bps: Optional[float],
                      publishers: Sequence[str], known: Mapping[str, KnownRate],
                      measured: Optional[Mapping[str, KnownRate]] = None
                      ) -> Dict[str, Dict[str, Any]]:
    """``{publisher node: {hz, bps, basis}}`` for one topic."""
    if measured is not None:
        return _split_measured(publishers, known, measured)
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
        rates = split_topic_rates(total_hz, total_bps, topic_pubs, known,
                                  measured_rates(entry))
        if entry.get('status') == 'not_monitored':
            rates = {n: {**r, 'basis': BASIS_NOT_MONITORED} if r['basis'] == BASIS_UNKNOWN else r
                     for n, r in rates.items()}
        annotated = {**entry, 'source_count': len(topic_pubs),
                     'heavy': is_heavy(str(entry.get('type') or '')),
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
