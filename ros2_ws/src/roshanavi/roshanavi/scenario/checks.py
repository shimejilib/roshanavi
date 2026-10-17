"""Judging steps and guards over received messages (pure: no ROS, clock passed in).

Every check gets the messages of its topics received at or after its window start
``t0`` (:meth:`Check.feed`) and is asked for a verdict with the current time
(:meth:`Check.poll`). A verdict carries a plain-Japanese explanation of what
arrived, how many, the last values and which condition failed where.
"""

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, NamedTuple, Optional, Sequence, Tuple

from ..stats import window_rate
from .fields import describe, json_safe, match_all, short, stamp_ns

LAST_VALUES = 3


class Record(NamedTuple):
    """One received message: monotonic receive time, wall time, plain (capped) data."""
    t: float
    wall: float
    plain: Any


@dataclass
class Verdict:
    passed: bool
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    approx: bool = False


def _sec(value: float) -> str:
    return f'{value:.2f}'.rstrip('0').rstrip('.') if value < 100 else f'{value:.0f}'


def _conds_text(where: Sequence[Any]) -> str:
    return '、'.join(describe(c) for c in where)


class Check:
    """Base: ``topics`` it reads, window start ``t0``, ``end`` (None = until finish)."""

    def __init__(self, kind: str, spec: Any, t0: float, duration: Optional[float]):
        self.kind = kind
        self.spec = spec
        self.t0 = t0
        self.end = None if duration is None else t0 + duration
        self.received: Dict[str, int] = {}
        self.last: Dict[str, Deque[Tuple[float, Any]]] = {}

    @property
    def topics(self) -> Tuple[str, ...]:
        return (self.spec.topic,)

    def feed(self, topic: str, rec: Record) -> None:
        if rec.t < self.t0 or (self.end is not None and rec.t > self.end):
            return
        self.received[topic] = self.received.get(topic, 0) + 1
        self.last.setdefault(topic, deque(maxlen=LAST_VALUES)).append((rec.t, rec.plain))
        self._on(topic, rec)

    def _on(self, topic: str, rec: Record) -> None:
        pass

    def poll(self, now: float) -> Optional[Verdict]:
        raise NotImplementedError

    def finish(self, now: float) -> Verdict:
        """Final verdict when the scenario ends (guards); default: poll at ``end``."""
        verdict = self.poll(max(now, self.end or now))
        return verdict or Verdict(False, '判定が終わりませんでした')

    def count(self, topic: Optional[str] = None) -> int:
        return self.received.get(topic or self.topics[0], 0)

    def last_values(self, topic: Optional[str] = None) -> List[Any]:
        return [json_safe(p) for _t, p in self.last.get(topic or self.topics[0], ())]

    def progress(self) -> Dict[str, Any]:
        return {'received': {t: self.count(t) for t in self.topics}}


class ExpectCheck(Check):
    def __init__(self, spec: Any, t0: float):
        super().__init__('expect', spec, t0, spec.within)
        self.matched = 0
        self.first_match: Optional[float] = None
        self.last_mismatch: List[Dict[str, Any]] = []

    def _on(self, topic: str, rec: Record) -> None:
        if self.matched >= self.spec.count:
            return
        ok, failed = match_all(self.spec.where, rec.plain)
        if ok:
            self.matched += 1
            if self.matched >= self.spec.count:
                self.first_match = rec.t
        else:
            self.last_mismatch = failed

    def poll(self, now: float) -> Optional[Verdict]:
        spec = self.spec
        details = {'received': self.count(), 'matched': self.matched, 'count': spec.count,
                   'within': spec.within, 'last_values': self.last_values()}
        if self.first_match is not None:
            after = self.first_match - self.t0
            return Verdict(True, f'{spec.topic} に条件どおりのメッセージが {self.matched} 件届きました '
                           f'({_sec(after)} 秒後)', {**details, 'after_sec': after})
        if now < self.end:
            return None
        what = f'「{_conds_text(spec.where)}」を満たす' if spec.where else ''
        head = (f'{spec.topic} に {_sec(spec.within)} 秒以内に{what}メッセージが {spec.count} 件'
                '届くはずでしたが、')
        received = self.count()
        if received == 0:
            return Verdict(False, head + '1 件も届きませんでした。', details)
        text = head + (f'条件に合ったのは {self.matched} 件でした (この間に届いたのは {received} 件)。'
                       if spec.where else f'届いたのは {received} 件でした。')
        values = self.last_values()
        if len(values) == 1:
            text += f'届いた値: {short(values[0], 160)}。'
        elif values:
            text += (f'最後に届いた {len(values)} 件 (新しい順): '
                     + ' / '.join(short(v, 100) for v in reversed(values)) + '。')
        if self.last_mismatch:
            text += '最後の値で合わなかった条件: ' + ' / '.join(
                f'{m["condition"]} → {m["reason"]}' for m in self.last_mismatch) + '。'
        return Verdict(False, text, {**details, 'mismatches': self.last_mismatch})


class AlwaysCheck(Check):
    def __init__(self, spec: Any, t0: float, duration: Optional[float], min_count: int):
        super().__init__('always', spec, t0, duration)
        self.min_count = min_count
        self.violation: Optional[Tuple[float, Any, List[Dict[str, Any]]]] = None

    def _on(self, topic: str, rec: Record) -> None:
        if self.violation is not None:
            return
        ok, failed = match_all(self.spec.where, rec.plain)
        if not ok:
            self.violation = (rec.t, rec.plain, failed)

    def poll(self, now: float) -> Optional[Verdict]:
        spec = self.spec
        details = {'received': self.count(), 'last_values': self.last_values()}
        if self.violation is not None:
            t, plain, failed = self.violation
            text = (f'{spec.topic} のメッセージはすべて「{_conds_text(spec.where)}」を満たすはずでしたが、'
                    f'{_sec(t - self.t0)} 秒後に合わないものが届きました: {short(json_safe(plain), 160)}。'
                    '合わなかった条件: ' + ' / '.join(f'{m["condition"]} → {m["reason"]}'
                                               for m in failed) + '。')
            return Verdict(False, text, {**details, 'at_sec': t - self.t0, 'mismatches': failed,
                                         'value': json_safe(plain)})
        if self.end is None or now < self.end:
            return None
        received = self.count()
        if received < self.min_count:
            text = (f'{spec.topic} に {_sec(self.end - self.t0)} 秒間で {self.min_count} 件以上届くはずでしたが、'
                    + ('1 件も届きませんでした。' if received == 0 else f'{received} 件でした。'))
            return Verdict(False, text, details)
        cond = f'すべて「{_conds_text(spec.where)}」を満たしました' if spec.where else '届き続けました'
        return Verdict(True, f'{spec.topic}: {_sec(self.end - self.t0)} 秒間に {received} 件、{cond}',
                       details)

    def finish(self, now: float) -> Verdict:
        verdict = self.poll(now)
        if verdict is not None:
            return verdict
        cond = f'「{_conds_text(self.spec.where)}」' if self.spec.where else ''
        return Verdict(True, f'{self.spec.topic}: シナリオの間に届いた {self.count()} 件はすべて{cond}'
                       'を満たしました', {'received': self.count()})


class NeverCheck(Check):
    def __init__(self, spec: Any, t0: float, duration: Optional[float]):
        super().__init__('never', spec, t0, duration)
        self.violation: Optional[Tuple[float, Any]] = None

    def _on(self, topic: str, rec: Record) -> None:
        if self.violation is None and match_all(self.spec.where, rec.plain)[0]:
            self.violation = (rec.t, rec.plain)

    def _what(self) -> str:
        return f'「{_conds_text(self.spec.where)}」に合うメッセージ' if self.spec.where else 'メッセージ'

    def poll(self, now: float) -> Optional[Verdict]:
        spec = self.spec
        if self.violation is not None:
            t, plain = self.violation
            return Verdict(False, f'{spec.topic} に来てはいけない{self._what()}が {_sec(t - self.t0)} 秒後に'
                           f'届きました: {short(json_safe(plain), 160)}',
                           {'received': self.count(), 'at_sec': t - self.t0,
                            'value': json_safe(plain)})
        if self.end is None or now < self.end:
            return None
        others = f' (届いた {self.count()} 件はすべて条件の外でした)' if self.count() else ''
        return Verdict(True, f'{spec.topic}: {_sec(self.end - self.t0)} 秒間、{self._what()}は'
                       f'来ませんでした{others}', {'received': self.count()})

    def finish(self, now: float) -> Verdict:
        verdict = self.poll(now)
        if verdict is not None:
            return verdict
        return Verdict(True, f'{self.spec.topic}: シナリオの間、{self._what()}は来ませんでした',
                       {'received': self.count()})


class RateCheck(Check):
    def __init__(self, spec: Any, t0: float):
        super().__init__('rate', spec, t0, spec.for_)
        self.times: List[float] = []

    def _on(self, topic: str, rec: Record) -> None:
        self.times.append(rec.t)

    def poll(self, now: float) -> Optional[Verdict]:
        if now < self.end:
            return None
        spec = self.spec
        span = self.end - self.t0
        hz, note = window_rate(self.times, self.end, span, retain_sec=span)
        lo = '' if spec.min_hz is None else _sec(spec.min_hz)
        hi = '' if spec.max_hz is None else _sec(spec.max_hz)
        bounds = f'{lo} 〜 {hi} Hz'
        details = {'hz': hz, 'received': len(self.times), 'min_hz': spec.min_hz,
                   'max_hz': spec.max_hz, 'for': span}
        if hz is None:
            return Verdict(False, f'{spec.topic}: {_sec(span)} 秒間に {len(self.times)} 件しか届かず、'
                           f'周期を測れませんでした (2 件以上必要。期待 {bounds})。', details)
        if hz == 0.0 and self.times:
            ago = self.end - self.times[-1]
            return Verdict(False, f'{spec.topic}: 途中で止まりました。最後の受信は終わりの {_sec(ago)} 秒前で、'
                           f'周期は 0 Hz とみなしました (期待 {bounds})。', details)
        ok = (spec.min_hz is None or hz >= spec.min_hz) and (spec.max_hz is None or hz <= spec.max_hz)
        text = f'{spec.topic} の周期は {hz:.2f} Hz でした ({len(self.times)} 件, 期待 {bounds})'
        return Verdict(ok, text if ok else text + '。範囲の外です。', details)


class _PairCheck(Check):
    def __init__(self, kind: str, spec: Any, t0: float):
        super().__init__(kind, spec, t0, spec.for_)
        self.inputs: List[Record] = []
        self.outputs: List[Record] = []

    @property
    def topics(self) -> Tuple[str, ...]:
        return (self.spec.input, self.spec.output)

    def _on(self, topic: str, rec: Record) -> None:
        # The same topic as input and output is allowed (counts twice), though unusual.
        if topic == self.spec.input:
            self.inputs.append(rec)
        if topic == self.spec.output:
            self.outputs.append(rec)


class ThroughputCheck(_PairCheck):
    def __init__(self, spec: Any, t0: float):
        super().__init__('throughput', spec, t0)

    def poll(self, now: float) -> Optional[Verdict]:
        if now < self.end:
            return None
        spec = self.spec
        n_in, n_out = len(self.inputs), len(self.outputs)
        details = {'inputs': n_in, 'outputs': n_out, 'min_ratio': spec.min_ratio,
                   'max_ratio': spec.max_ratio, 'for': spec.for_}
        if n_in == 0:
            return Verdict(False, f'入力 {spec.input} が {_sec(spec.for_)} 秒間に 1 件も届かなかったので、'
                           f'比を出せませんでした (出力 {spec.output} は {n_out} 件)。', details)
        ratio = n_out / n_in
        details['ratio'] = ratio
        text = (f'入力 {spec.input} {n_in} 件に対して出力 {spec.output} {n_out} 件 '
                f'(比 {ratio:.2f}、下限 {spec.min_ratio:g}'
                + (f'、上限 {spec.max_ratio:g}' if spec.max_ratio is not None else '') + ')')
        if ratio < spec.min_ratio:
            return Verdict(False, text + '。出力が足りません (取りこぼし・フレーム落ち・処理の遅れの可能性)。',
                           details)
        if spec.max_ratio is not None and ratio > spec.max_ratio:
            return Verdict(False, text + '。出力が多すぎます。', details)
        return Verdict(True, text, details)


def percentile(sorted_values: Sequence[float], pct: float) -> float:
    """Nearest-rank percentile of an ascending list (non-empty)."""
    rank = max(1, math.ceil(pct / 100.0 * len(sorted_values)))
    return sorted_values[min(rank, len(sorted_values)) - 1]


def pair_by_stamp(inputs: Sequence[Record], outputs: Sequence[Record]) -> Tuple[List[float], int]:
    """Latencies (s) of outputs whose header.stamp equals an input's; and unmatched outputs."""
    first: Dict[int, float] = {}
    for rec in inputs:
        stamp = stamp_ns(rec.plain)
        if stamp is not None and stamp not in first:
            first[stamp] = rec.t
    latencies, unmatched = [], 0
    for rec in outputs:
        stamp = stamp_ns(rec.plain)
        t_in = first.get(stamp) if stamp is not None else None
        if t_in is None or rec.t < t_in:
            unmatched += 1
        else:
            latencies.append(rec.t - t_in)
    return latencies, unmatched


def pair_by_order(inputs: Sequence[Record], outputs: Sequence[Record]) -> Tuple[List[float], int]:
    """Approximation: the n-th output answers the oldest input not yet answered (FIFO)."""
    queue = deque(sorted(r.t for r in inputs))
    latencies, unmatched = [], 0
    for rec in sorted(outputs, key=lambda r: r.t):
        if queue and queue[0] <= rec.t:
            latencies.append(rec.t - queue.popleft())
        else:
            unmatched += 1
    return latencies, unmatched


class LatencyCheck(_PairCheck):
    def __init__(self, spec: Any, t0: float):
        super().__init__('latency', spec, t0)

    def poll(self, now: float) -> Optional[Verdict]:
        if now < self.end:
            return None
        spec = self.spec
        approx = spec.match == 'order'
        pair = pair_by_order if approx else pair_by_stamp
        latencies, unmatched = pair(self.inputs, self.outputs)
        mode = '受信順で対応づけた近似' if approx else 'header.stamp で対応づけ'
        details: Dict[str, Any] = {'inputs': len(self.inputs), 'outputs': len(self.outputs),
                                   'pairs': len(latencies), 'unmatched': unmatched,
                                   'match': spec.match}
        if len(latencies) < spec.min_samples:
            text = (f'{spec.input} → {spec.output} の対応づけられた組が {len(latencies)} 組で、'
                    f'{spec.min_samples} 組に足りませんでした (入力 {len(self.inputs)} 件、'
                    f'出力 {len(self.outputs)} 件、{mode})。')
            if not approx and self.inputs and self.outputs and not latencies:
                text += ('出力の header.stamp が入力のどれとも一致しません。ノードが入力の stamp を'
                         '引き継いでいないなら match: order (近似) を使ってください。')
            return Verdict(False, text, details, approx)
        ms = sorted(v * 1000.0 for v in latencies)
        p50, p95, worst = percentile(ms, 50), percentile(ms, 95), ms[-1]
        details.update(p50_ms=p50, p95_ms=p95, max_ms=worst, limits={
            'p50_ms': spec.p50_ms, 'p95_ms': spec.p95_ms, 'max_ms': spec.max_ms})
        over = [f'{name} {value:.1f} ms > 上限 {limit:g} ms'
                for name, value, limit in (('p50', p50, spec.p50_ms), ('p95', p95, spec.p95_ms),
                                           ('最大', worst, spec.max_ms)) if limit is not None
                and value > limit]
        text = (f'{spec.input} → {spec.output} の処理時間: p50 {p50:.1f} ms / p95 {p95:.1f} ms / '
                f'最大 {worst:.1f} ms ({len(latencies)} 組、{mode})')
        if approx:
            text += '。近似: 取りこぼしがあると対応がずれるので throughput と一緒に確かめてください'
        if over:
            return Verdict(False, text + '。上限を超えました: ' + '、'.join(over) + '。', details,
                           approx)
        return Verdict(True, text, details, approx)


def make_check(kind: str, spec: Any, t0: float) -> Check:
    if kind == 'expect':
        return ExpectCheck(spec, t0)
    if kind == 'always':
        return AlwaysCheck(spec, t0, spec.for_, spec.min_count)
    if kind == 'never':
        return NeverCheck(spec, t0, spec.for_)
    if kind == 'rate':
        return RateCheck(spec, t0)
    if kind == 'throughput':
        return ThroughputCheck(spec, t0)
    if kind == 'latency':
        return LatencyCheck(spec, t0)
    if kind in ('resources', 'mem_growth'):
        from .resource_checks import make_resource_check  # imports this module
        return make_resource_check(kind, spec, t0)
    raise ValueError(f'not a check step: {kind}')


def make_guard(kind: str, spec: Any, t0: float) -> Check:
    if kind == 'always':
        return AlwaysCheck(spec, t0, None, 0)
    return NeverCheck(spec, t0, None)
