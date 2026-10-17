// 記録モード: operations in any tab become steps; a clicked watched message becomes an
// expectation ("これが来るはず"); a selected range becomes always / never / rate / throughput / latency.

import { useMemo, useState } from 'react';
import { api, describeError } from '../api/client';
import type { RecordEvent, ScenarioFile } from '../api/scenarioTypes';
import { t, tDynamic } from '../i18n';
import { isHiddenTopic } from '../lib/topics';
import { useLive } from '../state/LiveProvider';
import { FieldPicker } from './FieldPicker';
import {
  buildSteps,
  conditionsFrom,
  defaultName,
  type Expectation,
  lastOpBefore,
  pickFields,
  shortValue,
  suggestLatencyMs,
  suggestRate,
  suggestRatio,
} from './record';
import { useScenarioLive } from './ScenarioLive';
import { describeStep } from './editSteps';

type MsgEvent = Extract<RecordEvent, { kind: 'msg' }>;
type RangeKind = 'always' | 'never' | 'rate' | 'throughput' | 'latency';
const RANGE_KINDS: RangeKind[] = ['always', 'never', 'rate', 'throughput', 'latency'];
const TIMELINE_ROWS = 300;
const DEFAULT_SPAN_SEC = 2;

let counter = 0;
const newId = () => `x${(counter += 1)}`;

function opText(ev: Extract<RecordEvent, { kind: 'op' }>): string {
  const op = ev.op;
  if (op.kind === 'inject') {
    const req = op.request;
    return t('scn.rec.opInject', { mode: tDynamic(`scn.rec.mode.${String(req.mode)}`, 'scn.rec.mode.once'), topic: String(req.topic ?? req.source ?? '') });
  }
  if (op.kind === 'inject_stop') return t('scn.rec.opInjectStop');
  if (op.kind === 'class_call') return t('scn.rec.op.class_call', { node: op.node, method: op.method });
  return tDynamic(`scn.rec.op.${op.kind}`, 'scn.rec.op.target_start', { id: op.target_id });
}


function WatchPicker({ onStart, busy }: { onStart: (topics: string[]) => void; busy: boolean }) {
  const { live } = useLive();
  const [selected, setSelected] = useState<string[]>([]);
  const topics = (live.graph?.topics ?? []).map((tp) => tp.name).filter((n) => !isHiddenTopic(n)).sort();
  const toggle = (topic: string) => setSelected((cur) => (cur.includes(topic) ? cur.filter((x) => x !== topic) : [...cur, topic]));
  return (
    <div className="scn-watch">
      <p>{t('scn.rec.intro')}</p>
      <fieldset className="rec-topics">
        <legend>{t('scn.rec.watch')}</legend>
        {topics.map((topic) => (
          <label key={topic} className="check mono">
            <input type="checkbox" checked={selected.includes(topic)} onChange={() => toggle(topic)} data-testid={`scn-watch-${topic}`} data-tour={`scn-watch-${topic}`} />
            {topic}
          </label>
        ))}
        {topics.length === 0 && <p className="muted">{t('scn.rec.noTopics')}</p>}
      </fieldset>
      <button type="button" className="primary" disabled={busy || selected.length === 0} onClick={() => onStart(selected)} data-testid="scn-rec-start" data-tour="scn-rec-start">
        {t('scn.rec.start')}
      </button>
    </div>
  );
}

function ExpectationCard({ e, onChange, onRemove, inputs }: {
  e: Expectation;
  onChange: (next: Expectation) => void;
  onRemove: () => void;
  inputs: string[];
}) {
  const num = (key: keyof Expectation, label: string) => (
    <label className="scn-field">
      {label}
      <input className="num" value={String(e[key] ?? '')} onChange={(ev) => {
        const n = Number(ev.target.value);
        onChange({ ...e, [key]: Number.isFinite(n) ? n : e[key] });
      }} />
    </label>
  );
  return (
    <li className="scn-expectation" data-testid={`scn-exp-${e.kind}`}>
      <div className="scn-edit-head">
        <select value={e.kind} aria-label={t('scn.rec.kind')} onChange={(ev) => {
          const kind = ev.target.value as Expectation['kind'];
          onChange({ ...e, kind, duration: kind === 'expect' ? e.duration : e.duration || DEFAULT_SPAN_SEC, input: e.input ?? inputs[0] });
        }}>
          {(['expect', ...RANGE_KINDS] as const).map((k) => <option key={k} value={k}>{tDynamic(`scn.kind.${k}`, 'scn.kind.expect')}</option>)}
        </select>
        <span className="mono">{e.topic}</span>
        <span className="muted small">{t('scn.rec.at', { t: e.t.toFixed(2) })}</span>
        <span className="spacer" />
        <button type="button" className="link danger-text" onClick={onRemove} aria-label={t('scn.edit.removeStep')}>✕</button>
      </div>
      <div className="scn-edit-fields">
        {e.kind === 'expect' ? num('within', t('scn.field.within')) : num('duration', t('scn.field.for'))}
        {e.kind === 'rate' && num('minHz', t('scn.field.min_hz'))}
        {e.kind === 'rate' && num('maxHz', t('scn.field.max_hz'))}
        {(e.kind === 'throughput' || e.kind === 'latency') && (
          <label className="scn-field">
            {t('scn.field.input')}
            <select value={e.input ?? ''} onChange={(ev) => onChange({ ...e, input: ev.target.value })}>
              {inputs.map((topic) => <option key={topic} value={topic}>{topic}</option>)}
            </select>
          </label>
        )}
        {e.kind === 'throughput' && num('minRatio', t('scn.field.min_ratio'))}
        {e.kind === 'latency' && num('p95Ms', t('scn.field.p95_ms'))}
        {e.kind === 'latency' && (
          <label className="scn-field">
            {t('scn.field.match')}
            <select value={e.match ?? 'header.stamp'} onChange={(ev) => onChange({ ...e, match: ev.target.value as Expectation['match'] })}>
              <option value="header.stamp">{t('scn.match.stamp')}</option>
              <option value="order">{t('scn.match.order')}</option>
            </select>
          </label>
        )}
      </div>
      {(e.kind === 'expect' || e.kind === 'always' || e.kind === 'never') && e.where.length > 0 && (
        <p className="mono small">{e.where.map((c) => `${c.field} ${c.op} ${JSON.stringify(c.value ?? c.min ?? '')}`).join(' / ')}</p>
      )}
    </li>
  );
}

export function RecordView({ onSaved }: { onSaved: (file: ScenarioFile) => void }) {
  const { record, events } = useScenarioLive();
  const session = record.session;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expectations, setExpectations] = useState<Expectation[]>([]);
  const [anchor, setAnchor] = useState<number | null>(null);
  const [rangeEnd, setRangeEnd] = useState<number | null>(null);
  const [picking, setPicking] = useState(false);
  const [hidden, setHidden] = useState<string[]>([]);
  const [name, setName] = useState(defaultName());
  // A finished (saved / discarded) session stays on the server until the next start.
  const [dismissed, setDismissed] = useState<string | null>(null);

  const messages = useMemo(() => events.filter((e): e is MsgEvent => e.kind === 'msg'), [events]);
  const selected = messages.find((m) => m.seq === anchor) ?? null;
  const endMsg = messages.find((m) => m.seq === rangeEnd) ?? null;
  const range = selected && endMsg ? [Math.min(selected.t, endMsg.t), Math.max(selected.t, endMsg.t)] as const : null;
  const steps = useMemo(() => buildSteps(events, expectations), [events, expectations]);
  const watch = session?.watch ?? [];

  const act = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  const start = (topics: string[]) => act(async () => {
    await api.startScenarioRecord(topics);
    setExpectations([]);
    setAnchor(null);
    setRangeEnd(null);
    setName(defaultName());
  });
  const stop = () => act(() => api.stopScenarioRecord());

  const clickMessage = (m: MsgEvent, extend: boolean) => {
    if (extend && selected && selected.topic === m.topic) {
      setRangeEnd(m.seq);
      return;
    }
    setAnchor(m.seq);
    setRangeEnd(null);
    setPicking(false);
  };

  const others = (m: MsgEvent) => messages.filter((o) => o.topic === m.topic && o.seq !== m.seq).slice(-20).map((o) => o.data);

  const addRange = (kind: RangeKind) => act(async () => {
    if (!selected || !session) return;
    const [from, to] = range ?? [selected.t, selected.t + DEFAULT_SPAN_SEC];
    const inputs = watch.filter((w) => w !== selected.topic);
    const base: Expectation = { id: newId(), kind, topic: selected.topic, type: session.types[selected.topic], t: from,
      duration: Math.max(to - from, 0.5), within: 0, where: [], input: inputs[0] };
    if (kind === 'always') base.where = conditionsFrom(pickFields(selected.data, others(selected)));
    if (kind === 'rate') {
      const m = await api.measureRecord({ kind: 'rate', topic: selected.topic, start: from, end: to });
      Object.assign(base, m.hz ? suggestRate(m.hz) : { minHz: 0.1 });
    }
    if (kind === 'throughput' && base.input) {
      const m = await api.measureRecord({ kind: 'throughput', input: base.input, output: selected.topic, start: from, end: to });
      base.minRatio = m.ratio ? suggestRatio(m.ratio) : 0.9;
    }
    if (kind === 'latency' && base.input) {
      let m = await api.measureRecord({ kind: 'latency', input: base.input, output: selected.topic, start: from, end: to, match: 'header.stamp' });
      base.match = 'header.stamp';
      if (!m.pairs) {
        m = await api.measureRecord({ kind: 'latency', input: base.input, output: selected.topic, start: from, end: to, match: 'order' });
        base.match = 'order';
      }
      base.p95Ms = m.p95_ms ? suggestLatencyMs(m.p95_ms) : 100;
    }
    setExpectations((cur) => [...cur, base]);
  });

  const save = () => act(async () => {
    const saved = await api.createScenario({ version: 1, name: name.trim() || defaultName(), steps });
    await api.stopScenarioRecord(true);
    setDismissed(session?.id ?? null);
    onSaved(saved);
  });

  if (!session || (!record.active && session.id === dismissed)) {
    return (
      <section className="scn-record" aria-labelledby="scn-rec-title" data-testid="scn-record">
        <h3 id="scn-rec-title">{t('scn.rec.title')}</h3>
        <WatchPicker onStart={(topics) => void start(topics)} busy={busy} />
        {error && <p className="error-box" role="alert">{error}</p>}
      </section>
    );
  }

  const rows = events.filter((e) => e.kind === 'op' || !hidden.includes(e.topic)).slice(-TIMELINE_ROWS);
  return (
    <section className="scn-record" aria-labelledby="scn-rec-title" data-testid="scn-record">
      <header className={record.active ? 'scn-rec-banner active' : 'scn-rec-banner'}>
        <h3 id="scn-rec-title">{record.active ? t('scn.rec.recording', { sec: (session.elapsed_sec ?? 0).toFixed(0) }) : t('scn.rec.stopped')}</h3>
        <p className="small">{record.active ? t('scn.rec.howto') : t('scn.rec.howtoStopped')}</p>
        <div className="row">
          {record.active ? (
            <button type="button" className="danger" disabled={busy} onClick={() => void stop()} data-testid="scn-rec-stop" data-tour="scn-rec-stop">{t('scn.rec.stop')}</button>
          ) : (
            <>
              <button type="button" disabled={busy} onClick={() => void start(watch)}>{t('scn.rec.restart')}</button>
              <button type="button" disabled={busy} onClick={() => void act(async () => {
                setDismissed(session.id);
                await api.stopScenarioRecord(true);
              })} data-testid="scn-rec-discard">{t('scn.rec.discard')}</button>
            </>
          )}
        </div>
      </header>
      {error && <p className="error-box" role="alert">{error}</p>}
      <div className="scn-rec-body">
        <div className="scn-timeline-wrap">
          <div className="row small">
            {watch.map((topic) => (
              <label key={topic} className="check mono">
                <input type="checkbox" checked={!hidden.includes(topic)}
                  onChange={() => setHidden((cur) => (cur.includes(topic) ? cur.filter((x) => x !== topic) : [...cur, topic]))} />
                {topic} ({session.counts[topic] ?? 0})
              </label>
            ))}
          </div>
          <ol className="scn-timeline" data-testid="scn-timeline" aria-label={t('scn.rec.timeline')}>
            {rows.map((ev) => ev.kind === 'op' ? (
              <li key={ev.seq} className="scn-tl-op" data-testid="scn-tl-op">
                <span className="scn-tl-t">{ev.t.toFixed(2)}</span>
                <span>▶ {opText(ev)}</span>
              </li>
            ) : (
              <li key={ev.seq}>
                <button type="button" data-testid="scn-tl-msg" data-tour="scn-tl-msg" data-topic={ev.topic}
                  className={`scn-tl-msg${ev.seq === anchor ? ' selected' : ''}${range && ev.topic === selected?.topic && ev.t >= range[0] && ev.t <= range[1] ? ' in-range' : ''}`}
                  onClick={(e) => clickMessage(ev, e.shiftKey)}>
                  <span className="scn-tl-t">{ev.t.toFixed(2)}</span>
                  <span className="mono scn-tl-topic">{ev.topic}</span>
                  <span className="mono scn-tl-value">{shortValue(ev.data)}</span>
                </button>
              </li>
            ))}
            {rows.length === 0 && <li className="muted">{t('scn.rec.empty')}</li>}
          </ol>
        </div>
        <div className="scn-rec-side">
          {selected ? (
            <div className="scn-selected" data-testid="scn-selected">
              <p className="small"><span className="mono">{selected.topic}</span> {t('scn.rec.at', { t: selected.t.toFixed(2) })}</p>
              <pre className="mono small scn-msg-data">{JSON.stringify(selected.data, null, 2)}</pre>
              {picking ? (
                <FieldPicker
                  choices={pickFields(selected.data, others(selected))}
                  response={selected.t - lastOpBefore(events, selected.t)}
                  onCancel={() => setPicking(false)}
                  onAdd={(where, within) => {
                    setExpectations((cur) => [...cur, { id: newId(), kind: 'expect', topic: selected.topic, type: session.types[selected.topic],
                      t: selected.t, duration: 0, within, where }]);
                    setPicking(false);
                  }} />
              ) : (
                <>
                  <button type="button" className="primary" onClick={() => setPicking(true)} data-testid="scn-expect-this" data-tour="scn-expect-this">{t('scn.rec.expectThis')}</button>
                  <p className="muted small">{range ? t('scn.rec.range', { from: range[0].toFixed(2), to: range[1].toFixed(2) }) : t('scn.rec.rangeHelp')}</p>
                  <div className="row">
                    {RANGE_KINDS.map((kind) => (
                      <button key={kind} type="button" disabled={busy || ((kind === 'throughput' || kind === 'latency') && watch.length < 2)}
                        onClick={() => void addRange(kind)} data-testid={`scn-range-${kind}`}>
                        {tDynamic(`scn.rec.rangeKind.${kind}`, 'scn.rec.rangeKind.always')}
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
          ) : (
            <p className="muted">{t('scn.rec.clickHelp')}</p>
          )}
          <h4>{t('scn.rec.expectations')}</h4>
          {expectations.length === 0 && <p className="muted small">{t('scn.rec.noExpectations')}</p>}
          <ol className="scn-expectations">
            {expectations.map((e) => (
              <ExpectationCard key={e.id} e={e} inputs={watch.filter((w) => w !== e.topic)}
                onChange={(next) => setExpectations((cur) => cur.map((x) => (x.id === e.id ? next : x)))}
                onRemove={() => setExpectations((cur) => cur.filter((x) => x.id !== e.id))} />
            ))}
          </ol>
          <h4>{t('scn.rec.steps', { n: steps.length })}</h4>
          <ol className="scn-preview mono small" data-testid="scn-rec-steps" data-tour="scn-rec-steps">
            {steps.map((s, i) => <li key={i}>{describeStep(s)}</li>)}
          </ol>
          <div className="scn-save">
            <label className="scn-field wide">
              {t('scn.rec.name')}
              <input value={name} onChange={(e) => setName(e.target.value)} data-testid="scn-rec-name" data-tour="scn-rec-name" />
            </label>
            <button type="button" className="primary" disabled={busy || steps.length === 0} onClick={() => void save()} data-testid="scn-rec-save" data-tour="scn-rec-save">
              {t('scn.rec.save')}
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
