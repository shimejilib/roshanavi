"""Scenario runner: setup -> pre-subscribe -> steps (with guards) -> teardown (always).

Timing rules (docs/design/scenarios.md):
- Every topic a check or guard reads is subscribed before the first step, with
  monotonic receive times (:mod:`.buffers`).
- A check's evaluation window starts when the check step starts. An ``expect``
  right after an input step (send / start / stop / play) counts from just before
  that input, so a response that arrives while the input step is still finishing
  is not missed.
- Guards run from the first step to the end; a violation stops the scenario in
  the middle of whatever step is running.
- The first failing step stops the scenario (the rest are ``skipped``).
- Teardown always runs: inject jobs, targets put back as they were, setup
  processes stopped (process groups), subscriptions destroyed.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .. import data_kinds, msgutil
from ..graph import collect, fq_name
from ..injector import Injector
from ..jobs import InjectError, InjectSpec
from ..ros_runtime import RosRuntime
from .buffers import Subscriptions
from ..resources.node_probe import NodeProbe
from .checks import Check, Verdict, make_check, make_guard
from .resource_checks import NodeResourceCheck
from .fields import short
from .hints import hints as graph_hints
from .procs import DEAD_STATES, SetupError, SetupProcesses, TargetController, wait_nodes
from .result import (CANCELLED, ERROR, FAILED, PASSED, RUNNING, SKIPPED, Result, StepResult)
from .schema import CHECK_STEPS, INPUT_STEPS, Scenario, StepEntry, check_topics

LOG = logging.getLogger(__name__)

POLL_SEC = 0.02
PROGRESS_SEC = 0.5
SEND_TIMEOUT_SEC = 5.0
TYPE_WAIT_SEC = 2.0
DISCOVERY_WAIT_SEC = 3.0
SETTLE_SEC = 0.5  # after setup: let new nodes' publishers / subscriptions be discovered


class StepError(Exception):
    """A step could not do its action (bad payload, unknown type, job error ...)."""


class _Cancelled(Exception):
    pass


class _GuardBroken(Exception):
    def __init__(self, index: int, verdict: Verdict):
        super().__init__(verdict.message)
        self.index = index
        self.verdict = verdict


@dataclass
class RunContext:
    runtime: RosRuntime
    data_dir: str
    setup: SetupProcesses
    targets: TargetController
    extra_roots: Sequence[str] = ()
    cancel: threading.Event = field(default_factory=threading.Event)
    progress: Optional[Callable[[Dict[str, Any]], None]] = None
    clock: Callable[[], float] = time.monotonic
    settle_sec: float = SETTLE_SEC
    node_probe: Optional[NodeProbe] = None  # resources / mem_growth (default: by cmdline)


def _type_hints(scenario: Scenario) -> Dict[str, str]:
    hints: Dict[str, str] = {}
    for entry in (*scenario.guards, *scenario.steps):
        spec = entry.spec
        topic = getattr(spec, 'topic', None)
        if not topic:
            continue
        type_name = getattr(spec, 'type', None)
        kind = getattr(spec, 'kind', None)
        if type_name:
            hints.setdefault(topic, msgutil.normalize_type_name(type_name))
        elif kind and kind != data_kinds.MESSAGE_KIND:
            hints.setdefault(topic, data_kinds.ros_type(kind))
    return hints


class ScenarioRunner:
    def __init__(self, scenario: Scenario, ctx: RunContext, result: Result):
        self.scenario = scenario
        self.ctx = ctx
        self.result = result
        self.injector = Injector(ctx.runtime, ctx.data_dir, clock=ctx.clock,
                                 extra_roots=tuple(ctx.extra_roots))
        self.subs: Optional[Subscriptions] = None
        self.guards: List[Check] = []
        self._cursors: Dict[Tuple[int, str], int] = {}
        self._started: Dict[str, Tuple[str, str]] = {}  # step id -> ('job' | 'target', ref)
        self._sent_topics: List[str] = []
        self._t_begin = 0.0
        self._last_progress = 0.0
        self._probe = ctx.node_probe or NodeProbe(
            owned=lambda: [*ctx.setup.pids(), *ctx.targets.pids()], clock=ctx.clock)

    # ---- public ------------------------------------------------------------------------
    def run(self) -> Result:
        started = self.ctx.clock()
        self.result.status = RUNNING
        self._progress(force=True)
        try:
            if self._setup():
                self._begin()
                self._steps()
        except _Cancelled:
            self._cancel_rest()
        except Exception as exc:  # a bug must still produce a result and a teardown
            LOG.exception('scenario %s crashed', self.scenario.name)
            self.result.status = ERROR
            self.result.message = f'シナリオの実行中に予期しないエラーが起きました: {type(exc).__name__}: {exc}'
        finally:
            self._teardown()
            self.result.duration_sec = self.ctx.clock() - started
            self._progress(force=True)
        return self.result

    # ---- progress / loop ------------------------------------------------------------------
    def _progress(self, force: bool = False) -> None:
        if self.ctx.progress is None:
            return
        now = self.ctx.clock()
        if not force and now - self._last_progress < PROGRESS_SEC:
            return
        self._last_progress = now
        try:
            self.ctx.progress(self.result.to_dict())
        except Exception:  # the UI feed must never break a run
            LOG.exception('scenario progress callback failed')

    def _check_cancel(self) -> None:
        if self.ctx.cancel.is_set():
            raise _Cancelled()

    def _pump(self, checks: Sequence[Check]) -> None:
        if self.subs is None:
            return
        for check in checks:
            for topic in check.topics:
                buf = self.subs.buffers.get(topic)
                if buf is None:
                    continue
                key = (id(check), topic)
                records, cursor = buf.since(self._cursors.get(key, 0))
                self._cursors[key] = cursor
                for rec in records:
                    check.feed(topic, rec)

    def _tick(self, active: Optional[Check] = None) -> None:
        self._check_cancel()
        if self.subs is not None:
            self.subs.retry()
        self._pump([*self.guards, *([active] if active else [])])
        now = self.ctx.clock()
        for index, guard in enumerate(self.guards):
            verdict = guard.poll(now)
            if verdict is not None and not verdict.passed:
                raise _GuardBroken(index, verdict)
        self._progress()

    def _sleep_until(self, deadline: float, active: Optional[Check] = None) -> None:
        while True:
            self._tick(active)
            remaining = deadline - self.ctx.clock()
            if remaining <= 0:
                return
            time.sleep(min(POLL_SEC, remaining))

    # ---- setup ---------------------------------------------------------------------------
    def _present_nodes(self) -> List[str]:
        return [fq_name(n, ns) for n, ns in self.ctx.runtime.node_names_and_namespaces()]

    def _setup(self) -> bool:
        for index, entry in enumerate(self.scenario.setup):
            res = self.result.setup[index]
            res.status = RUNNING
            self._progress(force=True)
            try:
                res.message = self._setup_one(index, entry)
                res.status = PASSED
            except SetupError as exc:
                res.status, res.message, res.log_tail = FAILED, str(exc), exc.log_tail
                for later in self.result.setup[index + 1:]:
                    later.status = SKIPPED
                for step in self.result.steps:
                    step.status = SKIPPED
                self.result.status = FAILED
                self.result.message = f'セットアップ {index + 1} で失敗しました: {exc}'
                return False
        if self.scenario.setup:
            deadline = self.ctx.clock() + self.ctx.settle_sec
            while self.ctx.clock() < deadline:
                self._check_cancel()
                time.sleep(POLL_SEC)
        return True

    def _setup_one(self, index: int, entry: Any) -> str:
        item = entry.item
        if item.kind == 'target':
            target_id = item.target
            text = self.ctx.targets.start(target_id)
            names = [*self.ctx.targets.nodes(target_id),
                     *(n if n.startswith('/') else '/' + n for n in item.wait_for_node)]
            status = lambda: self.ctx.targets.status(target_id)  # noqa: E731
            tail = lambda: self.ctx.targets.log_tail(target_id)  # noqa: E731
        else:
            names = self.ctx.setup.start(index, entry)
            target_id = self.ctx.setup.last_id()
            status = lambda: self.ctx.setup.status(target_id)  # noqa: E731
            tail = lambda: self.ctx.setup.log_tail(target_id)  # noqa: E731
            text = '起動しました'
        names = list(dict.fromkeys(names))
        missing = wait_nodes(self._present_nodes, names, item.wait_timeout,
                             lambda: status() not in DEAD_STATES, self._check_cancel)
        if status() in DEAD_STATES:
            raise SetupError(f'プロセスが終了しました (状態: {status()})。ログの最後を見てください。', tail())
        if missing:
            raise SetupError(f'{item.wait_timeout:g} 秒待ってもノード {", ".join(missing)} が現れませんでした '
                             '(ノード名・名前空間が合っているか、起動に時間がかかっていないか確認してください)。',
                             tail())
        return f'{text}。ノード {", ".join(names)} を確認しました' if names else text

    # ---- steps -----------------------------------------------------------------------------
    def _begin(self) -> None:
        self.subs = Subscriptions(self.ctx.runtime, self.scenario.topics(),
                                  _type_hints(self.scenario), self.ctx.clock)
        self.subs.start()
        # Nodes started just before (setup, launch_pytest) may not be discovered yet: give
        # topics of unknown type a moment to appear, so the first response is not missed.
        deadline = self.ctx.clock() + DISCOVERY_WAIT_SEC
        while self.subs.pending() and self.ctx.clock() < deadline:
            self._check_cancel()
            time.sleep(0.05)
            self.subs.retry(force=True)
        self.subs.wait_matched()
        self._t_begin = self.ctx.clock()
        self.guards = [make_guard(g.kind, g.spec, self._t_begin) for g in self.scenario.guards]
        for res in self.result.guards:
            res.status = RUNNING

    def _steps(self) -> None:
        input_at: Optional[float] = None
        for index, entry in enumerate(self.scenario.steps):
            res = self.result.steps[index]
            res.status = RUNNING
            started = self.ctx.clock()
            res.started_sec = started - self._t_begin
            self._progress(force=True)
            try:
                if entry.kind in CHECK_STEPS:
                    t0 = input_at if entry.kind == 'expect' and input_at is not None else started
                    input_at = None
                    verdict = self._run_check(entry, t0, res)
                else:
                    input_at = started if entry.kind in INPUT_STEPS else None
                    verdict = self._run_action(entry)
            except _GuardBroken as broken:
                self._guard_broken(index, broken)
                return
            except _Cancelled:
                res.status = CANCELLED
                res.duration_sec = self.ctx.clock() - started
                self._cancel_rest()
                return
            except StepError as exc:
                self._fail(index, ERROR, str(exc), entry)
                res.duration_sec = self.ctx.clock() - started
                return
            res.duration_sec = self.ctx.clock() - started
            res.message, res.details, res.approx = verdict.message, verdict.details, verdict.approx
            if not verdict.passed:
                self._fail(index, FAILED, verdict.message, entry)
                return
            res.status = PASSED
        self._finish_guards()

    def _finish_guards(self) -> None:
        now = self.ctx.clock()
        self._pump(self.guards)
        ok = True
        for index, guard in enumerate(self.guards):
            verdict = guard.finish(now)
            res = self.result.guards[index]
            res.status = PASSED if verdict.passed else FAILED
            res.message, res.details = verdict.message, verdict.details
            ok = ok and verdict.passed
        self.result.status = PASSED if ok else FAILED
        count = len(self.result.steps)
        self.result.message = (f'{count} ステップすべて成功しました' if ok
                               else 'ガードが破れました')

    def _skip_rest(self, after: int) -> None:
        for res in self.result.steps[after + 1:]:
            res.status = SKIPPED

    def _fail(self, index: int, status: str, message: str, entry: StepEntry) -> None:
        res = self.result.steps[index]
        res.status, res.message = status, message
        res.hints = self._hints(entry)
        self._skip_rest(index)
        self._close_guards(None)
        self.result.status = FAILED
        self.result.message = f'ステップ {index + 1} ({entry.kind}) で失敗しました'

    def _guard_broken(self, index: int, broken: _GuardBroken) -> None:
        res = self.result.steps[index]
        res.status = FAILED
        res.duration_sec = self.ctx.clock() - self._t_begin - (res.started_sec or 0.0)
        res.message = f'このステップの最中にガード {broken.index + 1} が破れたので中断しました'
        self._skip_rest(index)
        self._close_guards(broken)
        self.result.status = FAILED
        self.result.message = f'ガード {broken.index + 1} がステップ {index + 1} の最中に破れました'

    def _close_guards(self, broken: Optional[_GuardBroken]) -> None:
        for i, res in enumerate(self.result.guards):
            if broken is not None and i == broken.index:
                res.status, res.message = FAILED, broken.verdict.message
                res.details = broken.verdict.details
            elif res.status == RUNNING:
                res.status = SKIPPED
                res.message = 'シナリオが途中で終わったので最後まで見ていません'

    def _cancel_rest(self) -> None:
        for res in [*self.result.setup, *self.result.steps]:
            if res.status in ('pending', RUNNING):
                res.status = CANCELLED
        for res in self.result.guards:
            if res.status == RUNNING:
                res.status = SKIPPED
        self.result.status = CANCELLED
        self.result.message = '途中で中止しました'

    def _hints(self, entry: StepEntry) -> List[Dict[str, Any]]:
        outputs = check_topics(entry)
        topic = getattr(entry.spec, 'topic', None)
        inputs = list(dict.fromkeys([*self._sent_topics, *([topic] if topic and
                                                           entry.kind in ('send', 'start')
                                                           else [])]))
        found: List[Dict[str, Any]] = []
        for name in outputs:
            buf = self.subs.buffers.get(name) if self.subs else None
            if buf is not None and buf.error:
                found.append({'code': 'subscribe_failed', 'topic': name, 'message': buf.error})
            elif buf is not None and buf.subscription is None:
                found.append({'code': 'type_unknown', 'topic': name, 'message':
                              f'{name} の型が最後まで分からず購読できませんでした (誰も送っていません)。'
                              'ステップに type か kind を書くと、最初から購読します。'})
            elif buf is not None and buf.subscribed_at is not None \
                    and buf.subscribed_at > self._t_begin + 0.5:
                found.append({'code': 'subscribed_late', 'topic': name, 'message':
                              f'{name} は途中で現れたトピックなので、購読を始めたのが '
                              f'{buf.subscribed_at - self._t_begin:.1f} 秒後でした。'})
        try:
            found += graph_hints(collect(self.ctx.runtime), inputs, outputs)
        except Exception as exc:  # hints are best effort
            LOG.warning('scenario hints failed: %s', exc)
        return found

    # ---- checks ----------------------------------------------------------------------------
    def _run_check(self, entry: StepEntry, t0: float, res: StepResult) -> Verdict:
        check = make_check(entry.kind, entry.spec, t0)
        while True:
            self._tick(check)
            if isinstance(check, NodeResourceCheck) and check.wants_sample(self.ctx.clock()):
                check.feed_sample(self._probe.sample(check.node), self.ctx.clock())
            verdict = check.poll(self.ctx.clock())
            if verdict is not None:
                return verdict
            res.details = check.progress()
            time.sleep(POLL_SEC)

    # ---- actions ---------------------------------------------------------------------------
    def _run_action(self, entry: StepEntry) -> Verdict:
        kind, spec = entry.kind, entry.spec
        if kind == 'wait':
            self._sleep_until(self.ctx.clock() + spec.seconds)
            return Verdict(True, f'{spec.seconds:g} 秒待ちました')
        if kind == 'send':
            return self._send(spec)
        if kind == 'start':
            return self._start(spec)
        if kind == 'stop':
            if spec.target is not None:
                return self._stop_target(spec.target)
            return self._stop(spec.id)
        return self._play(spec)

    def _topic_types(self, topic: str) -> List[str]:
        return list(dict(self.ctx.runtime.topic_names_and_types()).get(topic, []))

    def _type_for(self, spec: Any) -> str:
        if spec.type:
            return msgutil.normalize_type_name(spec.type)
        deadline = self.ctx.clock() + TYPE_WAIT_SEC
        while True:
            types = self._topic_types(spec.topic)
            if spec.kind and spec.kind != data_kinds.MESSAGE_KIND:
                fitting = [t for t in types if data_kinds.fits(spec.kind, t)]
                return fitting[0] if fitting else data_kinds.ros_type(spec.kind)
            if len(types) == 1:
                return types[0]
            if len(types) > 1:
                raise StepError(f'{spec.topic} は複数の型 ({", ".join(types)}) で使われています。'
                                'type で 1 つ選んでください。')
            if self.ctx.clock() >= deadline:
                raise StepError(f'{spec.topic} の型が分かりません (まだ誰も使っていないトピックです)。'
                                'type (ROS の型) か kind (データの種類) を書いてください。')
            self._tick()
            time.sleep(0.1)

    @staticmethod
    def _payload(spec: Any, type_name: str) -> Any:
        if spec.data is not None:
            return spec.data
        if spec.value is None:
            return {}
        kind, value = spec.kind, spec.value
        if kind == data_kinds.MESSAGE_KIND:
            if not isinstance(value, dict):
                raise StepError('kind: message の value はメッセージのフィールドの対応にしてください')
            return value
        if isinstance(value, str) and '${' in value and kind in ('string', 'float', 'int', 'bool'):
            return {'data': value}  # an expression: rendered (type kept) on every send
        try:
            fields = data_kinds.payload(kind, value, type_name)
        except data_kinds.KindError as exc:
            raise StepError(f'value を {kind} として送れません: {exc}') from exc
        return {k: (list(v) if not isinstance(v, (str, int, float, bool, list, dict)) else v)
                for k, v in fields.items()}

    def _inject(self, spec: InjectSpec) -> str:
        try:
            return self.injector.start(spec)['id']
        except InjectError as exc:
            raise StepError(f'送信を始められません: {exc}') from exc

    def _job(self, job_id: str) -> Dict[str, Any]:
        return self.injector.get(job_id)

    def _send(self, spec: Any) -> Verdict:
        type_name = self._type_for(spec)
        payload = self._payload(spec, type_name)
        qos = spec.qos.model_dump() if spec.qos else {}
        job_id = self._inject(InjectSpec(mode='once', topic=spec.topic, type=type_name,
                                         payload=payload, qos=qos))
        self._sent_topics.append(spec.topic)
        deadline = self.ctx.clock() + SEND_TIMEOUT_SEC
        while True:
            job = self._job(job_id)
            if job['state'] == 'done':
                return Verdict(True, f'{spec.topic} に 1 件送りました: {short(payload, 120)}',
                               {'type': type_name})
            if job['state'] != 'running':
                raise StepError(f'{spec.topic} に送れませんでした: {job.get("error") or job["state"]}')
            if self.ctx.clock() >= deadline:
                raise StepError(f'{spec.topic} への送信が {SEND_TIMEOUT_SEC:g} 秒で終わりませんでした')
            self._tick()
            time.sleep(POLL_SEC)

    def _start(self, spec: Any) -> Verdict:
        if spec.target:
            try:
                text = self.ctx.targets.start(spec.target)
            except SetupError as exc:
                raise StepError(str(exc)) from exc
            self._started[spec.id] = ('target', spec.target)
            return Verdict(True, text)
        qos = spec.qos.model_dump() if spec.qos else {}
        if spec.media is not None:
            options = spec.media.model_dump(exclude={'source'})
            inject = InjectSpec(mode='media', topic=spec.topic, type=spec.type,
                                source=spec.media.source, rate_hz=spec.rate_hz, loop=spec.loop,
                                qos=qos, media=options)
            what = f'ファイル {spec.media.source}'
        else:
            type_name = self._type_for(spec)
            if spec.stream:
                inject = InjectSpec(mode='stream', topic=spec.topic, type=type_name,
                                    source=spec.stream, rate_hz=spec.rate_hz, count=spec.count,
                                    loop=spec.loop, qos=qos)
                what = f'{spec.stream} ({spec.rate_hz:g} Hz)'
            else:
                inject = InjectSpec(mode='periodic', topic=spec.topic, type=type_name,
                                    payload=self._payload(spec, type_name), rate_hz=spec.rate_hz,
                                    count=spec.count, qos=qos)
                what = f'{spec.rate_hz:g} Hz'
        job_id = self._inject(inject)
        self._started[spec.id] = ('job', job_id)
        self._sent_topics.append(spec.topic)
        job = self._job(job_id)
        if job['state'] == 'error':
            raise StepError(f'{spec.topic} への送信がすぐに止まりました: {job.get("error")}')
        return Verdict(True, f'{spec.topic} に {what} で送り始めました', {'job': job_id})

    def _stop_target(self, target_id: str) -> Verdict:
        try:
            return Verdict(True, self.ctx.targets.stop(target_id))
        except SetupError as exc:
            raise StepError(str(exc)) from exc

    def _stop(self, step_id: str) -> Verdict:
        kind, ref = self._started.pop(step_id, ('', ''))
        if kind == 'target':
            try:
                return Verdict(True, self.ctx.targets.stop(ref))
            except SetupError as exc:
                raise StepError(str(exc)) from exc
        if kind != 'job':
            raise StepError(f'{step_id} は始まっていません')
        before = self._job(ref)
        if before['state'] == 'error':
            raise StepError(f'{step_id} はエラーで止まっていました: {before.get("error")}')
        job = self.injector.stop(ref)
        note = '' if before['state'] == 'running' else ' (もう終わっていました)'
        return Verdict(True, f'{step_id} を止めました (送った数: {job.get("sent", 0)}){note}')

    def _play(self, spec: Any) -> Verdict:
        job_id = self._inject(InjectSpec(mode='bag', source=spec.bag, loop=spec.loop,
                                         bag_rate=spec.rate, bag_topics=tuple(spec.topics)))
        self._started[spec.id] = ('job', job_id)
        if not spec.wait:
            return Verdict(True, f'bag {spec.bag} の再生を始めました', {'job': job_id})
        started = self.ctx.clock()
        deadline = started + spec.timeout
        while True:
            job = self._job(job_id)
            if job['state'] == 'done':
                return Verdict(True, f'bag {spec.bag} の再生が終わりました '
                               f'({self.ctx.clock() - started:.1f} 秒)', {'job': job_id})
            if job['state'] != 'running':
                raise StepError(f'bag {spec.bag} を再生できませんでした: {job.get("error") or job["state"]}')
            if self.ctx.clock() >= deadline:
                raise StepError(f'bag {spec.bag} の再生が {spec.timeout:g} 秒で終わりませんでした')
            self._tick()
            time.sleep(0.05)

    # ---- teardown --------------------------------------------------------------------------
    def _teardown(self) -> None:
        for name, action in (('inject jobs', self.injector.close),
                             ('targets', self.ctx.targets.restore),
                             ('setup processes', self.ctx.setup.close),
                             ('subscriptions', self.subs.close if self.subs else None)):
            if action is None:
                continue
            try:
                action()
            except Exception:  # keep tearing the rest down
                LOG.exception('scenario teardown of %s failed', name)
