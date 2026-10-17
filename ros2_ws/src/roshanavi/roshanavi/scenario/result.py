"""Results of a scenario run (JSON for the API / CLI, plain-Japanese step summaries)."""

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .fields import describe, json_safe, short
from .schema import Scenario, SetupEntry, StepEntry

PASSED, FAILED, ERROR, SKIPPED, CANCELLED = 'passed', 'failed', 'error', 'skipped', 'cancelled'
PENDING, RUNNING = 'pending', 'running'


def _s(value: float) -> str:
    return f'{value:g}'


def _conds(where: Any) -> str:
    return '「' + '、'.join(describe(c) for c in where) + '」' if where else ''


def summarize(entry: StepEntry) -> str:
    """One line describing what a step (or guard) does."""
    k, s = entry.kind, entry.spec
    if k == 'send':
        what = s.data if s.data is not None else s.value
        return f'送る: {s.topic} ← {short(what, 60) if what is not None else "(既定値)"}'
    if k == 'start':
        if s.target:
            return f'起動: {s.target}'
        if s.media is not None:
            return f'開始 {s.id}: {s.topic} にファイル {s.media.source} を流す'
        if s.stream:
            return f'開始 {s.id}: {s.topic} に {s.stream} を {_s(s.rate_hz)} Hz で流す'
        return f'開始 {s.id}: {s.topic} に {_s(s.rate_hz)} Hz で送り続ける'
    if k == 'stop':
        return f'停止: {s.id}' if s.id is not None else f'停止: {s.target}'
    if k == 'play':
        return f'bag を再生 {s.id}: {s.bag}' + (' (終わるまで待つ)' if s.wait else '')
    if k == 'wait':
        return f'待つ: {_s(s.seconds)} 秒'
    if k == 'expect':
        return (f'{s.topic} に {_s(s.within)} 秒以内に{_conds(s.where)}メッセージが {s.count} 件届く')
    if k == 'always':
        span = f'{_s(s.for_)} 秒間' if hasattr(s, 'for_') else 'シナリオの間ずっと'
        return f'{span} {s.topic} が{_conds(s.where) or "届き続け"}' + ('を満たす' if s.where else 'る')
    if k == 'never':
        span = f'{_s(s.for_)} 秒間' if hasattr(s, 'for_') else 'シナリオの間ずっと'
        return f'{span} {s.topic} に{_conds(s.where)}メッセージが来ない'
    if k == 'rate':
        lo = '' if s.min_hz is None else _s(s.min_hz)
        hi = '' if s.max_hz is None else _s(s.max_hz)
        return f'{s.topic} の周期が {lo} 〜 {hi} Hz ({_s(s.for_)} 秒)'
    if k == 'throughput':
        return f'{s.input} → {s.output} の件数の比が {_s(s.min_ratio)} 以上 ({_s(s.for_)} 秒)'
    if k == 'latency':
        limits = '、'.join(f'{name} ≤ {_s(v)} ms' for name, v in
                          (('p50', s.p50_ms), ('p95', s.p95_ms), ('最大', s.max_ms)) if v is not None)
        mode = '' if s.match == 'header.stamp' else ' (受信順の近似)'
        return f'{s.input} → {s.output} の処理時間 {limits} ({_s(s.for_)} 秒){mode}'
    if k == 'resources':
        limits = '、'.join(text for text, v in ((f'CPU 平均 ≤ {_s(s.cpu_max or 0)}%', s.cpu_max),
                                                (f'メモリ ≤ {_s(s.mem_max_mb or 0)} MB',
                                                 s.mem_max_mb)) if v is not None)
        return f'{s.node} の負荷が {limits} ({_s(s.for_)} 秒)'
    if k == 'mem_growth':
        return f'{s.node} のメモリの増え方が {_s(s.max_mb_per_min)} MB/分以下 ({_s(s.for_)} 秒)'
    return k


def summarize_setup(entry: SetupEntry) -> str:
    item = entry.item
    if item.label:
        return item.label
    kind = item.kind
    if kind == 'run':
        return f'ros2 run {item.run.package} {item.run.executable}'
    if kind == 'launch':
        return f'ros2 launch {item.launch.package} {item.launch.file}'
    if kind == 'cmd':
        return ' '.join(item.cmd)
    if kind == 'target':
        return f'起動設定 {item.target}'
    label = {'function': '関数ノード', 'class': 'クラスノード', 'transform': '変換ノード', 'dummy': '入力ノード'}[kind]
    return f'{label} {entry.node_spec.name}'


@dataclass
class StepResult:
    index: int
    kind: str
    summary: str
    line: Optional[int] = None
    status: str = PENDING
    message: str = ''
    details: Dict[str, Any] = field(default_factory=dict)
    hints: List[Dict[str, Any]] = field(default_factory=list)
    approx: bool = False
    started_sec: Optional[float] = None  # since the steps began
    duration_sec: Optional[float] = None


@dataclass
class SetupResult:
    index: int
    kind: str
    summary: str
    status: str = PENDING
    message: str = ''
    log_tail: List[str] = field(default_factory=list)


@dataclass
class Result:
    name: str
    file: str = ''
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = PENDING
    message: str = ''
    started_at: float = field(default_factory=time.time)
    duration_sec: float = 0.0
    setup: List[SetupResult] = field(default_factory=list)
    guards: List[StepResult] = field(default_factory=list)
    steps: List[StepResult] = field(default_factory=list)
    scenario_id: Optional[str] = None
    schema_errors: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.status == PASSED

    @property
    def current_step(self) -> Optional[int]:
        return next((s.index for s in self.steps if s.status == RUNNING), None)

    def failures(self) -> List[str]:
        items = [f'セットアップ {s.index + 1}: {s.message}' for s in self.setup
                 if s.status in (FAILED, ERROR)]
        items += [f'ガード {g.index + 1}: {g.message}' for g in self.guards
                  if g.status in (FAILED, ERROR)]
        items += [f'ステップ {s.index + 1} ({s.kind}): {s.message}' for s in self.steps
                  if s.status in (FAILED, ERROR)]
        return items

    def to_dict(self) -> Dict[str, Any]:
        out = json_safe(asdict(self))
        out['passed'] = self.passed
        out['current_step'] = self.current_step
        return out

    def summary(self) -> Dict[str, Any]:
        """Short form for the results history list."""
        failed = next((s for s in [*self.setup, *self.guards, *self.steps]
                       if s.status in (FAILED, ERROR)), None)
        return {'run_id': self.run_id, 'scenario_id': self.scenario_id, 'name': self.name,
                'file': self.file, 'status': self.status, 'started_at': self.started_at,
                'duration_sec': self.duration_sec, 'message': self.message,
                'failed': None if failed is None else {
                    'index': failed.index, 'kind': failed.kind, 'message': failed.message}}


def new_result(scenario: Scenario, file: str = '', scenario_id: Optional[str] = None) -> Result:
    return Result(
        name=scenario.name, file=file, scenario_id=scenario_id,
        setup=[SetupResult(i, e.item.kind, summarize_setup(e)) for i, e in enumerate(scenario.setup)],
        guards=[StepResult(i, g.kind, summarize(g), g.line) for i, g in enumerate(scenario.guards)],
        steps=[StepResult(i, s.kind, summarize(s), s.line) for i, s in enumerate(scenario.steps)])


def schema_error_result(name: str, file: str, exc: Any, scenario_id: Optional[str] = None
                        ) -> Result:
    return Result(name=name, file=file, scenario_id=scenario_id, status=ERROR,
                  message=f'シナリオのファイルに誤りがあります: {exc}',
                  schema_errors=list(getattr(exc, 'errors', [])))
