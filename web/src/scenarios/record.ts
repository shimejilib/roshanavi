// Record mode logic (docs/design/scenarios.md): pure functions, tested with vitest.
//
// - pickFields: which fields of a clicked message become `where` conditions
//   (scalars eq, floats approx, numbered texts a pattern; stamp / counter-like fields and
//   lengths that vary between messages unchecked).
// - withinFor: the `within` of an expect from the measured response time.
// - buildSteps: operations + expectations on one timeline -> scenario steps with waits.

import type { Condition, Op, RecordedOp, RecordEvent, StepRaw } from '../api/scenarioTypes';

export const MIN_WITHIN_SEC = 0.5;
export const WITHIN_FACTOR = 3;
export const MIN_WAIT_SEC = 0.1;
export const MAX_FIELDS = 60;
const SMALL_ARRAY = 4;

/** Path segments that change on every message (time, counters, sequence numbers). */
const VOLATILE = /^(stamp|timestamp|time|sec|nanosec|seq|sequence|seq_num|count|counter|counters|frame_number|uuid|id_counter)$/i;

export type FieldReason = 'volatile' | 'changes' | 'big' | 'element' | null;

export interface FieldChoice {
  path: string;
  value: unknown;
  op: Op;
  checked: boolean;
  /** Why it is unchecked by default (shown next to the checkbox). */
  reason: FieldReason;
  tol?: number;
}

interface Leaf {
  path: string;
  value: unknown;
  /** Array length of a (possibly truncated) array leaf. */
  length?: number;
  inArray: boolean;
  bigArray?: boolean;
}

function isTruncated(value: unknown): value is { _truncated: true; length: number; head: unknown[] } {
  return typeof value === 'object' && value !== null && (value as { _truncated?: unknown })._truncated === true;
}

function walk(value: unknown, path: string, inArray: boolean, out: Leaf[]): void {
  if (out.length >= MAX_FIELDS * 2) return;
  if (isTruncated(value)) {
    out.push({ path, value: null, length: value.length, inArray, bigArray: true });
    return;
  }
  if (Array.isArray(value)) {
    out.push({ path, value: null, length: value.length, inArray });
    value.forEach((item, i) => walk(item, path ? `${path}.${i}` : String(i), true, out));
    return;
  }
  if (typeof value === 'object' && value !== null) {
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      walk(item, path ? `${path}.${key}` : key, inArray, out);
    }
    return;
  }
  out.push({ path, value, inArray });
}

/** Leaf fields of a message (`header.stamp.sec`, `detections.0.id`, arrays as their length). */
export function flatten(data: unknown): Leaf[] {
  const out: Leaf[] = [];
  walk(data, '', false, out);
  return out.filter((leaf) => leaf.path !== '');
}

export function isVolatilePath(path: string): boolean {
  if (/^header\.stamp(\.|$)/.test(path)) return true;
  return path.split('.').some((seg) => VOLATILE.test(seg));
}

function digitsPattern(text: string): string {
  return text.replace(/\d+/g, '\u0000');
}

function escapeRegex(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** `Hello World: 12` with siblings `Hello World: 13` -> `^Hello World: \d+$` (else null). */
export function numberedPattern(value: string, others: string[]): string | null {
  if (!/\d/.test(value)) return null;
  const shape = digitsPattern(value);
  const sameShape = others.filter((o) => o !== value && digitsPattern(o) === shape);
  if (sameShape.length === 0) return null;
  return `^${escapeRegex(shape).replace(/\u0000/g, '\\d+')}$`;
}

function lookup(data: unknown, path: string): unknown {
  let current: unknown = data;
  for (const seg of path.split('.')) {
    if (isTruncated(current)) current = current.head;
    if (Array.isArray(current)) current = current[Number(seg)];
    else if (typeof current === 'object' && current !== null) current = (current as Record<string, unknown>)[seg];
    else return undefined;
  }
  return current;
}

/** An integer that is different on every message (sequence numbers, counters). */
function isCounterLike(value: number, others: unknown[]): boolean {
  if (others.length === 0) return false;
  const all = [value, ...others];
  return new Set(all).size === all.length;
}

function lengthOf(value: unknown): number | undefined {
  if (Array.isArray(value)) return value.length;
  if (isTruncated(value)) return value.length;
  return undefined;
}

export function defaultTol(value: number): number {
  return Math.max(Math.abs(value) * 0.01, 1e-6);
}

/**
 * Conditions proposed for a clicked message. `others` are other messages of the same topic
 * (from the timeline) used to spot fields that change on every message.
 */
export function pickFields(data: unknown, others: unknown[] = []): FieldChoice[] {
  const choices: FieldChoice[] = [];
  for (const leaf of flatten(data)) {
    if (choices.length >= MAX_FIELDS) break;
    if (leaf.length !== undefined) {
      const lengths = others.map((o) => lengthOf(lookup(o, leaf.path))).filter((n) => n !== undefined);
      let reason: FieldReason = null;
      if (leaf.bigArray) reason = 'big';
      else if (isVolatilePath(leaf.path)) reason = 'volatile';
      else if (lengths.some((n) => n !== leaf.length)) reason = 'changes';
      else if (leaf.inArray && !smallArrayPath(data, leaf.path)) reason = 'element';
      choices.push({ path: leaf.path, value: leaf.length, op: 'len_eq', checked: reason === null, reason });
      continue;
    }
    const value = leaf.value;
    const volatile = isVolatilePath(leaf.path);
    const otherValues = others.map((o) => lookup(o, leaf.path)).filter((v) => v !== undefined);
    const changes = otherValues.some((v) => v !== value);
    let op: Op = 'eq';
    let shown: unknown = value;
    let tol: number | undefined;
    let reason: FieldReason = volatile ? 'volatile' : null;
    if (typeof value === 'string') {
      // The clicked text is what the user expects; only a numbered text becomes a pattern.
      const pattern = changes ? numberedPattern(value, otherValues.filter((v): v is string => typeof v === 'string')) : null;
      if (pattern) {
        op = 'regex';
        shown = pattern;
      }
    } else if (typeof value === 'number' && !Number.isInteger(value)) {
      op = 'approx';
      tol = defaultTol(value);
    } else if (typeof value === 'number' && !reason && isCounterLike(value, otherValues)) {
      reason = 'changes'; // a different integer on every message: a counter / sequence number
    }
    const elementOfLargeArray = leaf.inArray && !smallArrayPath(data, leaf.path);
    if (elementOfLargeArray && !reason) reason = 'element';
    const choice: FieldChoice = { path: leaf.path, value: shown, op, checked: reason === null, reason };
    if (tol !== undefined) choice.tol = tol;
    choices.push(choice);
  }
  return choices;
}

/** True when every array on the way to `path` has at most SMALL_ARRAY items. */
function smallArrayPath(data: unknown, path: string): boolean {
  let current: unknown = data;
  for (const seg of path.split('.')) {
    if (Array.isArray(current) && current.length > SMALL_ARRAY) return false;
    if (isTruncated(current)) return false;
    current = lookup(current, seg);
  }
  return true;
}

export function conditionsFrom(choices: FieldChoice[]): Condition[] {
  return choices
    .filter((c) => c.checked)
    .map((c) => {
      const cond: Condition = { field: c.path, op: c.op, value: c.value };
      if (c.op === 'approx' && c.tol !== undefined) cond.tol = c.tol;
      return cond;
    });
}

function roundUp(sec: number, step = 0.1): number {
  return Math.round(Math.ceil(sec / step - 1e-9) * step * 1000) / 1000;
}

/** `within` for an expect: 3 x the measured response time, at least 0.5 s (0.1 s steps). */
export function withinFor(responseSec: number): number {
  return Math.max(MIN_WITHIN_SEC, roundUp(Math.max(responseSec, 0) * WITHIN_FACTOR));
}

/** Last operation at or before `t` (seconds since the recording started; 0 = the start). */
export function lastOpBefore(events: RecordEvent[], t: number): number {
  let found = 0;
  for (const ev of events) {
    if (ev.kind === 'op' && ev.t <= t && ev.t > found) found = ev.t;
  }
  return found;
}

/** What the user asked for on the timeline (before it becomes a step). */
export interface Expectation {
  id: string;
  kind: 'expect' | 'always' | 'never' | 'rate' | 'throughput' | 'latency';
  topic: string;
  type?: string;
  /** expect: the clicked message's time; others: the start of the selected range. */
  t: number;
  /** Length of the selected range (s); expect uses `within` instead. */
  duration: number;
  within: number;
  where: Condition[];
  minHz?: number;
  maxHz?: number;
  input?: string;
  minRatio?: number;
  match?: 'header.stamp' | 'order';
  p95Ms?: number;
}

function rounded(value: number, digits = 2): number {
  const f = 10 ** digits;
  return Math.round(value * f) / f;
}

export function expectationStep(e: Expectation): StepRaw {
  const typed = e.type ? { type: e.type } : {};
  const where = e.where.length ? { where: e.where } : {};
  const span = rounded(Math.max(e.duration, 0.5), 1);
  switch (e.kind) {
    case 'expect':
      return { expect: { topic: e.topic, ...typed, within: e.within, ...where } };
    case 'always':
      return { always: { topic: e.topic, ...typed, for: span, ...where } };
    case 'never':
      return { never: { topic: e.topic, ...typed, for: span, ...where } };
    case 'rate':
      return { rate: { topic: e.topic, ...typed, for: span, min_hz: e.minHz, max_hz: e.maxHz } };
    case 'throughput':
      return { throughput: { input: e.input, output: e.topic, for: span, min_ratio: e.minRatio } };
    case 'latency':
      return { latency: { input: e.input, output: e.topic, for: span, match: e.match ?? 'header.stamp', p95_ms: e.p95Ms } };
  }
}

function stripEmpty<T extends Record<string, unknown>>(obj: T): T {
  return Object.fromEntries(Object.entries(obj).filter(([, v]) => v !== undefined && v !== null)) as T;
}

/** Turns recorded operations into input steps; keeps the job -> step id map for stops. */
export class OpConverter {
  private readonly ids = new Map<string, string>();
  private readonly used = new Set<string>();

  private freshId(base: string): string {
    let id = base;
    for (let n = 2; this.used.has(id); n += 1) id = `${base}_${n}`;
    this.used.add(id);
    return id;
  }

  convert(op: RecordedOp): StepRaw[] {
    if (op.kind === 'inject') return this.inject(op.job_id, op.request);
    if (op.kind === 'inject_stop') {
      const id = this.ids.get(op.job_id);
      if (!id) return []; // started before the recording: nothing to replay
      this.ids.delete(op.job_id);
      return [{ stop: id }];
    }
    if (op.kind === 'class_call') return [{ call: { node: op.node, method: op.method } }];
    if (op.kind === 'target_start') return [{ start: { target: op.target_id } }];
    if (op.kind === 'target_stop') return [{ stop: { target: op.target_id } }];
    return [{ stop: { target: op.target_id } }, { start: { target: op.target_id } }];
  }

  private inject(jobId: string, req: Record<string, unknown>): StepRaw[] {
    const mode = req.mode as string;
    const topic = req.topic as string | undefined;
    const qos = req.qos as Record<string, unknown> | undefined;
    const customQos = qos && (qos.reliability !== 'reliable' || qos.durability !== 'volatile' || (qos.depth ?? 10) !== 10);
    const base = stripEmpty({ topic, type: req.type as string | undefined, ...(customQos ? { qos } : {}) });
    if (mode === 'once') return [{ send: { ...base, data: req.payload ?? {} } }];
    if (mode === 'bag') {
      const id = this.freshId('bag');
      this.ids.set(jobId, id);
      return [{ play: stripEmpty({ id, bag: req.source, topics: (req.topics as string[] | undefined)?.length ? req.topics : undefined,
        rate: req.bag_rate !== 1 ? req.bag_rate : undefined, loop: req.loop ? true : undefined }) }];
    }
    const id = this.freshId(topic ? topic.replace(/^\//, '').replace(/[^A-Za-z0-9_]/g, '_') || 'job' : 'job');
    this.ids.set(jobId, id);
    if (mode === 'media') {
      const media = stripEmpty({ ...(req.media as Record<string, unknown> | undefined ?? {}), source: req.source });
      return [{ start: stripEmpty({ id, ...base, media, rate_hz: req.rate_hz, loop: req.loop ? true : undefined }) }];
    }
    if (mode === 'stream') {
      return [{ start: stripEmpty({ id, ...base, stream: req.source, rate_hz: req.rate_hz, count: req.count, loop: req.loop ? true : undefined }) }];
    }
    return [{ start: stripEmpty({ id, ...base, data: req.payload ?? {}, rate_hz: req.rate_hz, count: req.count }) }];
  }
}

function waitStep(sec: number): StepRaw[] {
  return sec >= MIN_WAIT_SEC ? [{ wait: rounded(sec, 1) }] : [];
}

/**
 * The scenario steps of a recording, in time order (counted from the first operation):
 * op -> (expectations anchored after it, each as soon as the previous one ended) -> wait -> next op.
 * A range expectation waits until its range starts; an expect needs no wait (it waits itself).
 */
export function buildSteps(events: RecordEvent[], expectations: Expectation[]): StepRaw[] {
  const ops = events.filter((e): e is Extract<RecordEvent, { kind: 'op' }> => e.kind === 'op').sort((a, b) => a.t - b.t);
  const pending = [...expectations].sort((a, b) => a.t - b.t);
  const converter = new OpConverter();
  const steps: StepRaw[] = [];
  // The time before the first operation (choosing tabs, typing) is not part of the scenario.
  let cursor = ops[0]?.t ?? 0;
  const flush = (until: number) => {
    while (pending.length && (pending[0] as Expectation).t < until) {
      const e = pending.shift() as Expectation;
      if (e.kind === 'expect') {
        steps.push(expectationStep(e));
        cursor = Math.max(cursor, e.t);
      } else {
        steps.push(...waitStep(e.t - cursor));
        steps.push(expectationStep(e));
        cursor = Math.max(cursor, e.t) + Math.max(e.duration, 0.5);
      }
    }
  };
  for (const op of ops) {
    flush(op.t);
    const converted = converter.convert(op.op);
    if (converted.length === 0) continue;
    steps.push(...waitStep(op.t - cursor));
    steps.push(...converted);
    cursor = Math.max(cursor, op.t);
  }
  flush(Number.POSITIVE_INFINITY);
  return steps;
}

/** Proposed thresholds from what was measured in the selected range. */
export function suggestRate(hz: number): { minHz: number; maxHz: number } {
  return { minHz: rounded(Math.max(hz * 0.8, 0), 2), maxHz: rounded(hz * 1.2 + 0.01, 2) };
}

export function suggestRatio(ratio: number): number {
  return Math.max(0.01, Math.floor(Math.min(ratio, 1) * 0.9 * 100) / 100);
}

export function suggestLatencyMs(p95: number): number {
  return Math.ceil(Math.max(p95 * 2, p95 + 20));
}

/** Short one-line text of a message for the timeline. */
export function shortValue(data: unknown, limit = 80): string {
  let text: string;
  if (typeof data === 'object' && data !== null && 'data' in (data as Record<string, unknown>)
      && Object.keys(data as Record<string, unknown>).length === 1) {
    text = JSON.stringify((data as Record<string, unknown>).data);
  } else {
    text = JSON.stringify(data);
  }
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

export function defaultName(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `recorded_${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}`;
}
