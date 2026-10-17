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
WINDOWS_SEC = (1.0, 5.0, 10.0)  # averaging windows the UI can choose
MAX_WINDOW_SEC = max(WINDOWS_SEC)
# A topic counts as stopped (hz 0) after this many expected periods of silence, at least
# STALE_MIN_SEC; without it a stopped topic would keep its old average for a whole window.
STALE_PERIODS = 3.0
STALE_MIN_SEC = 1.0
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
    (``last_seen``). Both are injectable for deterministic tests. Samples are
    kept for the longest selectable window so any of :data:`WINDOWS_SEC` can be
    computed on request (``snapshot(window_sec)``).
    """

    def __init__(self, window_sec: float = DEFAULT_WINDOW_SEC, clock: Clock = time.monotonic,
                 wall_clock: Clock = time.time, max_samples: int = MAX_SAMPLES):
        self._window = window_sec
        self._retain = max(window_sec, MAX_WINDOW_SEC)
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
        cutoff = now - self._retain
        while self._samples and self._samples[0].t < cutoff:
            self._samples.popleft()

    def snapshot(self, window_sec: Optional[float] = None) -> Dict[str, Any]:
        """Statistics over the last ``window_sec`` (default: the configured window)."""
        window = window_sec or self._window
        now = self._clock()
        with self._lock:
            self._prune(now)
            retained = list(self._samples)
            total, last_seen = self._total, self._last_seen
            history = list(self._history)
        samples = [s for s in retained if s.t >= now - window]
        recent = sum(1 for s in samples if s.t > now - RECENT_SEC)
        stale = bool(retained) and is_silent(retained, now)
        samples, rate_window, rate_note = rate_samples(samples, retained, now, window, stale)
        stats = compute_stats(samples)
        if stale:
            stats = zero_rates(stats)
        return {**stats, 'last_seen': last_seen, 'total_count': total,
                'recent_count': recent, 'history': history, 'window_sec': window,
                'rate_window_sec': rate_window, 'rate_note': rate_note, 'stale': stale}

    def tick(self) -> None:
        """Append the current hz to the 1 s history (called once per second)."""
        hz = self.snapshot()['hz']
        with self._lock:
            self._history.append(hz)


def rate_samples(samples: Sequence[Sample], retained: Sequence[Sample], now: float,
                 window: float, stale: bool) -> Tuple[Sequence[Sample], float, Optional[str]]:
    """Samples to compute rates from, the span actually used and a note for the UI.

    A live topic slower than the window (fewer than 2 messages in it) would read
    0 Hz although it is alive. Its rate is then computed over the longest window
    (``rate_note='extended'``); when even that holds fewer than 2 messages the
    rate cannot be measured (``'too_few'``, hz 0 but the UI shows a dash).
    """
    if stale or len(samples) >= 2 or not retained:
        return samples, window, None
    longer = [s for s in retained if s.t >= now - MAX_WINDOW_SEC]
    if MAX_WINDOW_SEC > window and len(longer) >= 2:
        return longer, MAX_WINDOW_SEC, 'extended'
    return samples, window, 'too_few'


def window_rate(times: Sequence[float], now: float, window: float
                ) -> Tuple[Optional[float], Optional[str]]:
    """Event rate over the last ``window`` s from ascending event times (seconds).

    Same semantics as :meth:`TopicStats.snapshot`: (n-1)/(t_last-t_first) over the
    events inside the window, the longest window for slow streams (``'extended'``),
    0 for a stopped stream. ``(None, 'too_few')`` when it cannot be measured yet
    (fewer than 2 events), so callers show "measuring" rather than a number.
    """
    retained = [Sample(t, 0) for t in times if t >= now - MAX_WINDOW_SEC and t <= now]
    in_window = [s for s in retained if s.t >= now - window]
    stale = bool(retained) and is_silent(retained, now)
    used, _span, note = rate_samples(in_window, retained, now, window, stale)
    if stale:
        return 0.0, note
    if note == 'too_few':
        return None, note
    return _rate_and_intervals([s.t for s in used])[0], note


def expected_period(samples: Sequence[Sample]) -> Optional[float]:
    """Mean receive interval of the retained samples (None with fewer than 2)."""
    if len(samples) < 2:
        return None
    span = samples[-1].t - samples[0].t
    return span / (len(samples) - 1) if span > 0 else None


def is_silent(samples: Sequence[Sample], now: float) -> bool:
    """True when nothing arrived for max(3 x expected period, 1 s)."""
    if not samples:
        return False
    period = expected_period(samples)
    limit = max(STALE_PERIODS * period if period else 0.0, STALE_MIN_SEC)
    return now - samples[-1].t > limit


def zero_rates(stats: Dict[str, Any]) -> Dict[str, Any]:
    """Rates of a stopped topic: 0 (sizes, jitter and latency keep their last values)."""
    hz_source = 0.0 if stats.get('hz_source') is not None else None
    return {**stats, 'hz': 0.0, 'hz_recv': 0.0, 'hz_source': hz_source, 'bytes_per_sec': 0.0}


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
