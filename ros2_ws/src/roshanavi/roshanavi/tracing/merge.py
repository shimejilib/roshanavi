"""Trace results into the traffic entries, plus diagnostics and unsupported nodes (pure).

A subscriber row of a node the trace covers becomes ``basis: "measured"``
with ``hz_recv`` (successful takes), ``hz_processed`` (finished callbacks)
and ``cb_ms {avg, p95, max}``; the theoretical value is kept as
``hz_expected``. Everything else stays theoretical.

**Topics that are not monitored** (images by default): nothing is subscribed, so the
publisher rows carry only what the trace saw. The send rate counted at the publishers
(``hz_traced``, the sum over the publishers) becomes the row's Hz (basis ``traced``) and the topic's
``hz_traced``; bandwidth stays ``None`` (the trace does not know message sizes).

**処理が追いついていない**: rclcpp takes a message only right before running
its callback, so takes ≈ callbacks even when the node is overloaded — the
backlog is dropped inside the DDS queue, before any take. The incoming rate
is therefore the larger of what the senders sent (``hz_expected``, measured
per publisher) and what was taken; a node is behind when it processes
clearly less than that.
"""

from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..ros_runtime import is_self_node

BASIS_MEASURED = 'measured'
BASIS_TRACED = 'traced'  # a publisher counted by the trace on a topic that is not monitored
BEHIND_MIN_HZ = 0.5      # below this nothing is called "behind"
BEHIND_ABS_HZ = 0.5
BEHIND_RATIO = 0.1       # processed < 90 % of incoming
DEFAULT_WINDOW = 5

REASON_RCLPY = 'rclpy'                    # received only, no callback events
REASON_INTRA = 'intra_process'            # callbacks only, takes bypass rmw
REASON_RESTART = 'restart_needed'         # running since before the init capture
REASON_NOT_TRACED = 'not_traced'          # other container / host, or started earlier
PARTIAL_REASONS = (REASON_RCLPY, REASON_INTRA)


def _window_key(window: Optional[float]) -> str:
    return str(int(window or DEFAULT_WINDOW))


def _index(items: Iterable[Mapping[str, Any]]) -> Dict[Tuple[str, str], List[Mapping[str, Any]]]:
    index: Dict[Tuple[str, str], List[Mapping[str, Any]]] = {}
    for item in items:
        index.setdefault((item['node'], item['topic']), []).append(item)
    return index


def _sum(values: Sequence[Optional[float]]) -> Optional[float]:
    return None if not values or any(v is None for v in values) else round(sum(values), 3)


def _cb(stats: Sequence[Optional[Mapping[str, float]]]) -> Optional[Dict[str, float]]:
    known = [s for s in stats if s]
    if not known:
        return None
    return {'avg': round(sum(s['avg'] for s in known) / len(known), 3),
            'p95': max(s['p95'] for s in known), 'max': max(s['max'] for s in known)}


def behind(incoming_sent: Optional[float], received: Optional[float],
           processed: Optional[float]) -> Optional[Dict[str, Any]]:
    """``{incoming_hz, processed_hz, basis}`` when processing clearly lags, else None."""
    if processed is None:
        return None
    sent, recv = incoming_sent or 0.0, received or 0.0
    incoming, basis = (sent, 'sent') if sent >= recv else (recv, 'received')
    if incoming < BEHIND_MIN_HZ:
        return None
    if incoming - processed < max(BEHIND_ABS_HZ, BEHIND_RATIO * incoming):
        return None
    return {'incoming_hz': round(incoming, 3), 'processed_hz': round(processed, 3),
            'basis': basis}


def _measured_sub(sub: Mapping[str, Any], traced: List[Mapping[str, Any]], window: str,
                  avg_size: Optional[float]) -> Dict[str, Any]:
    values = [t['windows'].get(window) or {} for t in traced]
    hz_recv = _sum([v.get('hz_recv') for v in values])
    langs = {t['lang'] for t in traced}
    lang = 'cpp' if langs == {'cpp'} else 'py'
    hz_processed = _sum([v.get('hz_processed') for v in values]) if lang == 'cpp' else None
    cb_ms = _cb([v.get('cb_ms') for v in values]) if lang == 'cpp' else None
    expected = sub.get('hz') if sub.get('basis') == 'theoretical' else None
    result = {**sub, 'hz_expected': expected, 'hz_recv': hz_recv,
              'hz_processed': hz_processed, 'cb_ms': cb_ms, 'lang': lang,
              'intra': any(t.get('intra') for t in traced),
              'symbol': next((t['symbol'] for t in traced if t.get('symbol')), None)}
    shown = hz_recv if hz_recv is not None else hz_processed  # intra-process: callbacks only
    if sub.get('basis') != 'not_delivered' and shown is not None:  # None: still warming up
        result['basis'] = BASIS_MEASURED
        result['hz'] = shown
        result['bps'] = round(shown * avg_size, 1) if avg_size else sub.get('bps')
    result['behind'] = behind(expected, hz_recv, hz_processed)
    if result['behind'] is not None and cb_ms:
        result['behind']['cb_avg_ms'] = cb_ms['avg']
    return result


def _traced_pub(pub: Mapping[str, Any], hz: Optional[float], entry: Mapping[str, Any]
                ) -> Dict[str, Any]:
    """A publisher row with the trace's send count; for a topic nobody measures it is the row's Hz."""
    result = {**pub, 'hz_traced': hz}
    if entry.get('status') == 'not_monitored' and pub.get('hz') is None and hz is not None:
        result.update(hz=hz, bps=None, basis=BASIS_TRACED)
    return result


def _topic_hz_traced(pubs: Sequence[Mapping[str, Any]]) -> Optional[float]:
    """Topic send rate from the trace: the sum when every publisher is covered, else None."""
    rates = [p.get('hz_traced') if p.get('basis') != 'exact' else p.get('hz') for p in pubs]
    return _sum(rates)


def apply_trace(entries: Sequence[Mapping[str, Any]], snap: Optional[Mapping[str, Any]],
                window: Optional[float]) -> List[Dict[str, Any]]:
    """Copy of the annotated traffic entries with trace values on covered endpoints."""
    if not snap:
        return [dict(e) for e in entries]
    key = _window_key(window)
    subs = _index(snap.get('subscriptions') or [])
    pubs = _index(snap.get('publishers') or [])
    result = []
    for entry in entries:
        topic = entry['topic']
        avg_size = entry.get('avg_size') if entry.get('status') == 'ok' else None
        new_subs = []
        for sub in entry.get('subscribers') or []:
            traced = subs.get((sub['node'], topic))
            new_subs.append(_measured_sub(sub, traced, key, avg_size) if traced else dict(sub))
        new_pubs = []
        for pub in entry.get('publishers') or []:
            traced = pubs.get((pub['node'], topic))
            hz = _sum([(t['windows'].get(key) or {}).get('hz') for t in traced or []])
            new_pubs.append(_traced_pub(pub, hz, entry) if traced else dict(pub))
        merged = {**entry, 'subscribers': new_subs, 'publishers': new_pubs}
        if entry.get('status') == 'not_monitored':
            merged['hz_traced'] = _topic_hz_traced(new_pubs)
        result.append(merged)
    return result


def behind_list(entries: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """``processing_behind`` diagnostics of merged entries, sorted by node then topic."""
    found = [{'code': 'processing_behind', 'node': s['node'], 'topic': e['topic'], **s['behind']}
             for e in entries for s in e.get('subscribers') or [] if s.get('behind')]
    return sorted(found, key=lambda d: (d['node'], d['topic']))


def unsupported_nodes(graph_nodes: Iterable[Mapping[str, Any]], snap: Mapping[str, Any],
                      pids: Mapping[str, Optional[int]], trace_started: Optional[float],
                      created_at: Callable[[int], Optional[float]]) -> List[Dict[str, Any]]:
    """Graph nodes the trace cannot measure (fully or partly), with the reason."""
    traced: Dict[str, str] = {}
    for node in snap.get('nodes') or []:
        if traced.get(node['node']) != 'cpp':
            traced[node['node']] = node.get('lang', 'py')
    intra = {s['node'] for s in snap.get('subscriptions') or [] if s.get('intra')}
    result = []
    for node in graph_nodes:
        name = node.get('id') or ''
        if node.get('job_id') or is_self_node(name):
            continue
        reason = _reason(name, traced, intra, pids.get(name), trace_started, created_at)
        if reason is not None:
            result.append({'node': name, 'reason': reason, 'pid': pids.get(name)})
    return sorted(result, key=lambda r: r['node'])


def _reason(name: str, traced: Mapping[str, str], intra: Iterable[str], pid: Optional[int],
            trace_started: Optional[float], created_at: Callable[[int], Optional[float]]
            ) -> Optional[str]:
    if name in traced:
        if traced[name] != 'cpp':
            return REASON_RCLPY
        return REASON_INTRA if name in intra else None
    if pid is not None and trace_started is not None:
        created = created_at(pid)
        if created is not None and created < trace_started:
            return REASON_RESTART
    return REASON_NOT_TRACED
