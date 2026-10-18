"""Resource warnings for the diagnostics panel (pure). Same shape as
:mod:`roshanavi.diagnostics` (``code``, ``severity``, ``topic``, ``nodes``, ``detail``);
the web UI writes the plain-Japanese sentence.

- ``mem_leak`` / ``gpu_mem_leak``: memory keeps growing at a steady pace without slowing down
  (the *suspect* tier of :mod:`.leak`, with the rate and how long it has been growing). The
  milder *watch* tier ("growing but levelling off") is shown on the resources tab only.
- ``disk_low``: the data_dir volume is below the recording thresholds (same
  :class:`~roshanavi.media.diskguard.DiskThresholds` as the recorder; ``stop`` = error).
- ``udp_rcvbuf``: the kernel dropped UDP datagrams for full receive buffers in the last
  minute **and** a topic with large messages lost messages -> hint about
  ``net.core.rmem_max``. Without such a topic nothing is reported here (the counter is on
  the resources tab): in practice the counter also grows during busy start-ups, and a
  permanent hint nobody can act on would only be noise.
"""

from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

LARGE_MESSAGE_BYTES = 64 * 1024


def _diag(code: str, severity: str, nodes: Iterable[str], detail: Dict[str, Any],
          topic: str = '') -> Dict[str, Any]:
    return {'code': code, 'severity': severity, 'topic': topic, 'nodes': sorted(nodes),
            'detail': detail}


def leak_diags(processes: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for proc in processes:
        for field, code in (('leak', 'mem_leak'), ('gpu_leak', 'gpu_mem_leak')):
            state = proc.get(field) or {}
            if not state.get('suspect'):
                continue
            out.append(_diag(code, 'warning', proc.get('nodes') or (), {
                'pid': proc['pid'], 'name': proc.get('name'), 'label': proc.get('label'),
                'group': proc.get('group'),
                'rate_mb_per_min': state.get('rate_mb_per_min'),
                'duration_sec': state.get('duration_sec'), 'scale_min': state.get('scale_min'),
                'rss': proc.get('rss') if code == 'mem_leak' else proc.get('gpu_mem')}))
    return out


def disk_diags(disk: Optional[Mapping[str, Any]], recording: bool) -> List[Dict[str, Any]]:
    if not disk or disk.get('level') not in ('warn', 'stop'):
        return []
    severity = 'error' if disk['level'] == 'stop' else 'warning'
    return [_diag('disk_low', severity, (), {
        'path': disk.get('path'), 'free': disk.get('free'), 'free_pct': disk.get('free_pct'),
        'level': disk['level'], 'recording': recording,
        'thresholds': disk.get('thresholds')})]


def large_drop_topics(traffic: Iterable[Mapping[str, Any]],
                      min_bytes: int = LARGE_MESSAGE_BYTES) -> List[Dict[str, Any]]:
    found = []
    for entry in traffic:
        size = entry.get('avg_size') or 0
        dropped = entry.get('dropped') or 0
        ratio = entry.get('drop_ratio') or 0
        if size >= min_bytes and (dropped > 0 or ratio > 0):
            found.append({'topic': entry['topic'], 'avg_size': size, 'dropped': dropped,
                          'drop_ratio': ratio})
    return sorted(found, key=lambda e: -e['avg_size'])


def udp_diags(udp: Optional[Mapping[str, Any]],
              traffic: Callable[[], Iterable[Mapping[str, Any]]]) -> List[Dict[str, Any]]:
    """``traffic`` is only called when the kernel actually dropped datagrams."""
    if not udp or not udp.get('rcvbuf_recent'):
        return []
    topics = large_drop_topics(traffic())
    detail = {'rcvbuf_recent': udp['rcvbuf_recent'], 'recent_sec': udp.get('recent_sec'),
              'rcvbuf_errors': udp.get('rcvbuf_errors'), 'topics': topics[:5]}
    if not topics:
        return []
    return [_diag('udp_rcvbuf', 'warning', (), detail, topics[0]['topic'])]


def diagnose(processes: Iterable[Mapping[str, Any]], disk: Optional[Mapping[str, Any]],
             recording: bool, udp: Optional[Mapping[str, Any]],
             traffic: Callable[[], Iterable[Mapping[str, Any]]]) -> List[Dict[str, Any]]:
    return [*disk_diags(disk, recording), *udp_diags(udp, traffic), *leak_diags(processes)]
