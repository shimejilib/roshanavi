"""``resources`` and ``mem_growth`` steps: judge one node's process instead of a topic (pure).

The runner feeds :class:`~roshanavi.resources.node_probe.NodeSample` objects (cumulative CPU
seconds and RSS, about every 0.5 s); the verdict is given when the window ends.

- ``resources``: CPU is the **average over the window** (CPU time / wall time, 100 = one
  core, like ``top``) so a single busy moment does not fail the step; the peak of the
  per-sample values is reported too. Memory is the **peak RSS**.
- ``mem_growth``: least-squares slope of RSS in MB/min over the window (no warm-up is
  applied here: put a ``wait`` step before it if start-up allocations should not count).
"""

from typing import Any, List, Optional

from ..resources.leak import MIB, mb_per_min
from ..resources.node_probe import NodeSample, segments
from .checks import Check, Verdict, _sec

SAMPLE_SEC = 0.5
NOT_FOUND = ('{node} のプロセスが見つかりませんでした。roshanavi と同じ PC で、同じユーザーの'
             'プロセスとして動いているか確認してください (別のコンテナや別の PC のノードは測れません)。')


def _conf_note(samples: List[NodeSample]) -> str:
    if samples and samples[-1].confidence != 'exact':
        return ' ※ノードとプロセスの対応づけは推定です (コマンドラインから)。'
    return ''


class NodeResourceCheck(Check):
    def __init__(self, kind: str, spec: Any, t0: float):
        super().__init__(kind, spec, t0, spec.for_)
        self.samples: List[NodeSample] = []
        self.last_sample_at: Optional[float] = None

    @property
    def topics(self) -> tuple:
        return ()

    @property
    def node(self) -> str:
        return self.spec.node

    def feed_sample(self, sample: Optional[NodeSample], now: float) -> None:
        self.last_sample_at = now
        if sample is not None and self.t0 <= sample.t <= self.end + SAMPLE_SEC:
            self.samples.append(sample)

    def wants_sample(self, now: float) -> bool:
        if self.last_sample_at is None:
            return True
        if now >= self.end and self.last_sample_at < self.end:
            return True  # one more sample right at the end of the window
        return now - self.last_sample_at >= SAMPLE_SEC

    def progress(self) -> dict:
        return {'samples': len(self.samples)}


class ResourcesCheck(NodeResourceCheck):
    def __init__(self, spec: Any, t0: float):
        super().__init__('resources', spec, t0)

    def _cpu(self) -> tuple:
        busy = span = 0.0
        peak: Optional[float] = None
        for seg in segments(self.samples):
            if len(seg) < 2:
                continue
            busy += seg[-1].cpu_seconds - seg[0].cpu_seconds
            span += seg[-1].t - seg[0].t
            for a, b in zip(seg, seg[1:]):
                if b.t > a.t:
                    value = (b.cpu_seconds - a.cpu_seconds) / (b.t - a.t) * 100.0
                    peak = value if peak is None else max(peak, value)
        return (None if span <= 0 else max(0.0, busy / span * 100.0)), peak

    def poll(self, now: float) -> Optional[Verdict]:
        if now < self.end:
            return None
        spec = self.spec
        if not self.samples:
            return Verdict(False, NOT_FOUND.format(node=spec.node), {'samples': 0})
        avg, peak = self._cpu()
        mem_mb = max(s.rss for s in self.samples) / MIB
        details = {'cpu_avg_pct': avg, 'cpu_peak_pct': peak, 'mem_max_mb': round(mem_mb, 1),
                   'cpu_max': spec.cpu_max, 'mem_max_mb_limit': spec.mem_max_mb,
                   'samples': len(self.samples), 'pids': list(self.samples[-1].pids),
                   'confidence': self.samples[-1].confidence, 'for': spec.for_}
        if spec.cpu_max is not None and avg is None:
            return Verdict(False, f'{spec.node}: CPU を測れませんでした (測定が 2 回以上必要です。'
                           f'{_sec(spec.for_)} 秒間に {len(self.samples)} 回)。', details)
        parts = []
        if avg is not None:
            parts.append(f'CPU は平均 {avg:.1f}% (1 コア = 100%、最大 {peak or 0:.0f}%)')
        parts.append(f'メモリ (RSS) は最大 {mem_mb:.0f} MB')
        limits = []
        if spec.cpu_max is not None:
            limits.append(f'CPU 上限 {spec.cpu_max:g}%')
        if spec.mem_max_mb is not None:
            limits.append(f'メモリ上限 {spec.mem_max_mb:g} MB')
        text = (f'{spec.node} の{"、".join(parts)}でした ({_sec(spec.for_)} 秒、'
                f'{"・".join(limits)})')
        over = []
        if spec.cpu_max is not None and avg is not None and avg > spec.cpu_max:
            over.append('CPU が上限を超えました')
        if spec.mem_max_mb is not None and mem_mb > spec.mem_max_mb:
            over.append('メモリが上限を超えました')
        note = _conf_note(self.samples)
        if over:
            return Verdict(False, text + '。' + '、'.join(over) + '。' + note, details)
        return Verdict(True, text + note, details)


class MemGrowthCheck(NodeResourceCheck):
    def __init__(self, spec: Any, t0: float):
        super().__init__('mem_growth', spec, t0)

    def poll(self, now: float) -> Optional[Verdict]:
        if now < self.end:
            return None
        spec = self.spec
        if not self.samples:
            return Verdict(False, NOT_FOUND.format(node=spec.node), {'samples': 0})
        seg = segments(self.samples)[-1]
        span = seg[-1].t - seg[0].t
        details = {'samples': len(seg), 'span_sec': round(span, 2),
                   'max_mb_per_min': spec.max_mb_per_min, 'for': spec.for_,
                   'pids': list(seg[-1].pids), 'confidence': seg[-1].confidence}
        if span < spec.for_ / 2:
            restarted = len(segments(self.samples)) > 1
            why = 'プロセスが途中で入れ替わった (再起動した) ため、' if restarted else ''
            return Verdict(False, f'{spec.node}: {why}増え方を測れるだけの時間がありませんでした '
                           f'({_sec(span)} 秒)。', details)
        slope = mb_per_min([(s.t, float(s.rss)) for s in seg]) or 0.0
        start_mb, end_mb = seg[0].rss / MIB, seg[-1].rss / MIB
        details.update(slope_mb_per_min=round(slope, 3), start_mb=round(start_mb, 1),
                       end_mb=round(end_mb, 1))
        text = (f'{spec.node} のメモリ (RSS) の増え方は {slope:+.2f} MB/分でした '
                f'({start_mb:.0f} → {end_mb:.0f} MB、{_sec(span)} 秒、上限 '
                f'{spec.max_mb_per_min:g} MB/分)')
        note = _conf_note(seg)
        if slope > spec.max_mb_per_min:
            return Verdict(False, text + '。増え続けています (メモリリークの疑い)。' + note, details)
        return Verdict(True, text + note, details)


def make_resource_check(kind: str, spec: Any, t0: float) -> NodeResourceCheck:
    if kind == 'resources':
        return ResourcesCheck(spec, t0)
    if kind == 'mem_growth':
        return MemGrowthCheck(spec, t0)
    raise ValueError(f'not a resource step: {kind}')
