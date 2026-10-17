"""Pure sliding-window traffic statistics (no ROS dependency, clock-injectable).

Receive-side numbers (``hz_recv``, ``jitter_recv_ms``) are what ``ros2 topic hz``
reports; they under-report when messages are lost or the subscriber lags and
include transport jitter. Publish-side numbers use the ``MessageInfo``
``source_timestamp`` and ``publication_sequence_number`` of each sample.
"""

import math
import threading
import time
from collections import defaultdict, deque
from typing import Any, Callable, Deque, Dict, List, Mapping, NamedTuple, Optional, Sequence, Tuple

DEFAULT_WINDOW_SEC = 5.0
HISTORY_LEN = 60
MAX_SAMPLES = 20000  # bounds memory for very high-rate topics
NS_PER_MS = 1e6
RECENT_SEC = 1.0  # ``recent_count`` = messages received in the last tick period

Clock = Callable[[], float]


class Sample(NamedTuple):
    """One received message. ``src_ns``/``recv_ns``/``seq`` are 0 when unsupported."""
    t: float  # monotonic receive time (s)
    size: int
    src_ns: int = 0
    recv_ns: int = 0
    gid: Optional[bytes] = None  # publisher id; None when rclpy does not expose it
    seq: int = 0


def sample_from_info(now: float, size: int, info: Optional[Mapping[str, Any]]) -> Sample:
    """Build a :class:`Sample` from a rclpy ``MessageInfo`` dict (may be None)."""
    if not info:
        return Sample(now, size)
    gid = info.get('publisher_gid')
    return Sample(now, size, int(info.get('source_timestamp') or 0),
                  int(info.get('received_timestamp') or 0),
                  bytes(gid) if gid else None, int(info.get('publication_sequence_number') or 0))


class TopicStats:
    """Sliding-window statistics for one topic.

    ``clock`` is monotonic seconds (intervals), ``wall_clock`` epoch seconds
    (``last_seen``). Both are injectable for deterministic tests.
    """

    def __init__(self, window_sec: float = DEFAULT_WINDOW_SEC, clock: Clock = time.monotonic,
                 wall_clock: Clock = time.time, max_samples: int = MAX_SAMPLES):
        self._window = window_sec
        self._clock = clock
        self._wall = wall_clock
        self._lock = threading.Lock()
        self._samples: Deque[Sample] = deque(maxlen=max_samples)
        self._history: Deque[float] = deque(maxlen=HISTORY_LEN)
        self._total = 0
        self._last_seen: Optional[float] = None

    def record(self, size: int, info: Optional[Mapping[str, Any]] = None) -> None:
        sample = sample_from_info(self._clock(), size, info)
        with self._lock:
            self._samples.append(sample)
            self._total += 1
            self._last_seen = self._wall()

    def _prune(self, now: float) -> None:
        cutoff = now - self._window
        while self._samples and self._samples[0].t < cutoff:
            self._samples.popleft()

    def snapshot(self) -> Dict[str, Any]:
        now = self._clock()
        with self._lock:
            self._prune(now)
            samples = list(self._samples)
            total, last_seen = self._total, self._last_seen
            history = list(self._history)
        recent = sum(1 for s in samples if s.t > now - RECENT_SEC)
        return {**compute_stats(samples), 'last_seen': last_seen, 'total_count': total,
                'recent_count': recent, 'history': history}

    def tick(self) -> None:
        """Append the current hz to the 1 s history (called once per second)."""
        hz = self.snapshot()['hz']
        with self._lock:
            self._history.append(hz)


def _rate_and_intervals(times: Sequence[float], count: Optional[int] = None
                        ) -> Tuple[float, List[float]]:
    """(count-1)/span rate and inter-arrival intervals of sorted ``times``.

    ``count`` is the number of messages actually published in the span when
    known (sequence numbers); it defaults to ``len(times)``.
    """
    if len(times) < 2:
        return 0.0, []
    span = times[-1] - times[0]
    published = count if count is not None else len(times)
    rate = (published - 1) / span if span > 0 else 0.0
    return rate, [b - a for a, b in zip(times, times[1:])]


def _std_ms(intervals: Sequence[float]) -> float:
    if not intervals:
        return 0.0
    mean = sum(intervals) / len(intervals)
    var = sum((x - mean) ** 2 for x in intervals) / len(intervals)
    return math.sqrt(var) * 1000.0


def _seq_monotonic(seqs: Sequence[int]) -> bool:
    return all(q > 0 for q in seqs) and all(b > a for a, b in zip(seqs, seqs[1:]))


def _source_rate(samples: Sequence[Sample]) -> Tuple[Optional[float], List[float]]:
    """Publish-side rate summed over publishers, or (None, []) if unsupported.

    Lost messages still count toward the publish rate when sequence numbers
    prove they were published.
    """
    if len(samples) < 2 or any(s.src_ns <= 0 for s in samples):
        return None, []
    groups: Dict[Optional[bytes], List[Sample]] = defaultdict(list)
    for s in samples:
        groups[s.gid].append(s)
    total, intervals = 0.0, []
    for members in groups.values():
        seqs = [m.seq for m in members]
        count = seqs[-1] - seqs[0] + 1 if _seq_monotonic(seqs) else None
        rate, ivs = _rate_and_intervals(sorted(m.src_ns / 1e9 for m in members), count)
        total += rate
        intervals.extend(ivs)
    return total, intervals


def _drops(samples: Sequence[Sample]) -> Tuple[Optional[int], Optional[float]]:
    """(dropped, drop_ratio) from per-publisher sequence gaps; (None, None) if unusable."""
    groups: Dict[Optional[bytes], List[int]] = defaultdict(list)
    for s in samples:
        groups[s.gid].append(s.seq)
    dropped = expected = 0
    for seqs in groups.values():
        if not _seq_monotonic(seqs):
            return None, None  # unsupported, restarted publisher or interleaved publishers
        span = seqs[-1] - seqs[0] + 1
        dropped += span - len(seqs)
        expected += span
    if not expected:
        return None, None
    return dropped, dropped / expected


def _latency_ms(samples: Sequence[Sample]) -> Optional[float]:
    diffs = [s.recv_ns - s.src_ns for s in samples if s.src_ns > 0 and s.recv_ns > 0]
    return sum(diffs) / len(diffs) / NS_PER_MS if diffs else None


def compute_stats(samples: Sequence[Sample]) -> Dict[str, Any]:
    """Rates, jitter, drops and latency from window samples (arrival order).

    ``hz_recv`` is (n-1)/(t_last-t_first) on receive times. ``hz_source`` is the
    publish-side rate; ``hz``/``jitter_ms`` use it when every sample carries a
    source timestamp (``hz_basis == 'source'``), else the receive side.
    ``dropped`` is None when sequence numbers are unusable.
    """
    n = len(samples)
    avg_size = sum(s.size for s in samples) / n if n else 0.0
    hz_recv, recv_ivs = _rate_and_intervals([s.t for s in samples])
    jitter_recv = _std_ms(recv_ivs)
    hz_source, src_ivs = _source_rate(samples)
    use_source = hz_source is not None
    hz = hz_source if use_source else hz_recv
    dropped, drop_ratio = _drops(samples) if n >= 2 else (None, None)
    return {'hz': hz, 'hz_basis': 'source' if use_source else 'receive',
            'hz_recv': hz_recv, 'hz_source': hz_source,
            'bytes_per_sec': hz * avg_size, 'avg_size': avg_size,
            'jitter_ms': _std_ms(src_ivs) if use_source else jitter_recv,
            'jitter_recv_ms': jitter_recv, 'dropped': dropped, 'drop_ratio': drop_ratio,
            'latency_ms': _latency_ms(samples)}
