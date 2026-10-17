// Immutable helpers for editing scenario steps in the form (tested with vitest).

import type { Condition, Op, StepKind, StepRaw } from '../api/scenarioTypes';

export const STEP_KINDS: StepKind[] = ['send', 'start', 'stop', 'play', 'wait', 'expect', 'always', 'never', 'rate', 'throughput', 'latency'];
export const OPS: Op[] = ['eq', 'ne', 'lt', 'le', 'gt', 'ge', 'range', 'approx', 'regex', 'contains', 'exists', 'len_eq', 'len_range'];

/** Numeric settings shown for each kind, in order. */
export const NUMBER_FIELDS: Partial<Record<StepKind, string[]>> = {
  expect: ['within', 'count'],
  always: ['for', 'min_count'],
  never: ['for'],
  rate: ['for', 'min_hz', 'max_hz'],
  throughput: ['for', 'min_ratio'],
  latency: ['for', 'p50_ms', 'p95_ms', 'max_ms'],
};
export const TOPIC_FIELDS: Partial<Record<StepKind, string[]>> = {
  send: ['topic'],
  expect: ['topic'],
  always: ['topic'],
  never: ['topic'],
  rate: ['topic'],
  throughput: ['input', 'output'],
  latency: ['input', 'output'],
};
export const WHERE_KINDS: StepKind[] = ['expect', 'always', 'never'];

export function stepKind(step: StepRaw): StepKind {
  return Object.keys(step)[0] as StepKind;
}

export function stepBody(step: StepRaw): Record<string, unknown> {
  const kind = stepKind(step);
  const body = step[kind];
  if (kind === 'wait' && typeof body === 'number') return { seconds: body };
  if (kind === 'stop' && typeof body === 'string') return { id: body };
  return typeof body === 'object' && body !== null ? (body as Record<string, unknown>) : {};
}

function rebuild(kind: StepKind, body: Record<string, unknown>): StepRaw {
  if (kind === 'wait' && Object.keys(body).length === 1 && 'seconds' in body) return { wait: body.seconds };
  if (kind === 'stop' && Object.keys(body).length === 1 && 'id' in body) return { stop: body.id };
  return { [kind]: body } as StepRaw;
}

/** A copy of `step` with `key` set (undefined / '' removes it). */
export function setField(step: StepRaw, key: string, value: unknown): StepRaw {
  const kind = stepKind(step);
  const body = { ...stepBody(step) };
  if (value === undefined || value === '') delete body[key];
  else body[key] = value;
  return rebuild(kind, body);
}

export function conditions(step: StepRaw): Condition[] {
  const where = stepBody(step).where;
  return Array.isArray(where) ? (where as Condition[]) : [];
}

export function setConditions(step: StepRaw, where: Condition[]): StepRaw {
  return setField(step, 'where', where.length ? where : undefined);
}

export function updateCondition(step: StepRaw, index: number, patch: Partial<Condition>): StepRaw {
  const where = conditions(step).map((c, i) => {
    if (i !== index) return c;
    const next: Condition = { ...c, ...patch };
    for (const key of Object.keys(next) as (keyof Condition)[]) {
      if (next[key] === undefined) delete next[key];
    }
    return next;
  });
  return setConditions(step, where);
}

export function removeAt<T>(items: T[], index: number): T[] {
  return items.filter((_, i) => i !== index);
}

export function move<T>(items: T[], index: number, delta: -1 | 1): T[] {
  const target = index + delta;
  if (target < 0 || target >= items.length) return items;
  const next = [...items];
  const moved = next[index] as T;
  next[index] = next[target] as T;
  next[target] = moved;
  return next;
}

/** Text typed in a form field -> a value of the same kind as before (number / bool / text). */
export function parseLike(text: string, previous: unknown): unknown {
  if (typeof previous === 'number') {
    const n = Number(text);
    return text.trim() !== '' && Number.isFinite(n) ? n : text;
  }
  if (typeof previous === 'boolean') {
    if (text === 'true') return true;
    if (text === 'false') return false;
    return text;
  }
  return text;
}

export function displayValue(value: unknown): string {
  if (value === undefined || value === null) return '';
  return typeof value === 'string' ? value : JSON.stringify(value);
}

export function parseNumber(text: string): number | undefined {
  if (text.trim() === '') return undefined;
  const n = Number(text);
  return Number.isFinite(n) ? n : undefined;
}

/** `data` / `value` of a send step as editable JSON text, and back. */
export function payloadText(step: StepRaw): { key: 'data' | 'value'; text: string } {
  const body = stepBody(step);
  if ('value' in body) return { key: 'value', text: typeof body.value === 'string' ? body.value : JSON.stringify(body.value) };
  return { key: 'data', text: JSON.stringify(body.data ?? {}) };
}

export function parsePayload(key: 'data' | 'value', text: string): { ok: true; value: unknown } | { ok: false } {
  if (key === 'value') {
    try {
      const parsed: unknown = JSON.parse(text);
      return { ok: true, value: typeof parsed === 'object' || typeof parsed === 'number' || typeof parsed === 'boolean' ? parsed : text };
    } catch {
      return { ok: true, value: text };
    }
  }
  try {
    const parsed: unknown = JSON.parse(text);
    return typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed) ? { ok: true, value: parsed } : { ok: false };
  } catch {
    return { ok: false };
  }
}

function conds(body: Record<string, unknown>): string {
  const where = Array.isArray(body.where) ? (body.where as Condition[]) : [];
  return where
    .map((c) => {
      if (c.op === 'exists') return `${c.field} がある`;
      if (c.op === 'range' || c.op === 'len_range') return `${c.field} ${c.op === 'len_range' ? 'の長さ ' : ''}${c.min ?? ''}〜${c.max ?? ''}`;
      const sym: Record<string, string> = { eq: '=', ne: '≠', lt: '<', le: '≤', gt: '>', ge: '≥', approx: '≈', regex: '~', contains: '∋', len_eq: 'の長さ =' };
      return `${c.field} ${sym[c.op] ?? c.op} ${JSON.stringify(c.value)}`;
    })
    .join('、');
}

/** One plain line for a step (record-mode preview); mirrors the server's summaries. */
export function describeStep(step: StepRaw): string {
  const kind = stepKind(step);
  const b = stepBody(step);
  const where = conds(b);
  switch (kind) {
    case 'send':
      return `送る: ${String(b.topic)} ← ${JSON.stringify(b.data ?? b.value ?? {})}`;
    case 'start':
      if (b.target) return `起動: ${String(b.target)}`;
      if (b.media) return `開始 ${String(b.id ?? b.topic)}: ${String(b.topic)} にファイルを流す`;
      return `開始 ${String(b.id ?? b.topic)}: ${String(b.topic)} に ${String(b.rate_hz)} Hz で送り続ける`;
    case 'stop':
      return `停止: ${String(b.id ?? b.target)}`;
    case 'play':
      return `bag を再生: ${String(b.bag)}`;
    case 'wait':
      return `待つ: ${String(b.seconds)} 秒`;
    case 'expect':
      return `届くはず: ${String(b.topic)} に ${String(b.within)} 秒以内${where ? ` (${where})` : ''}`;
    case 'always':
      return `ずっと条件どおり: ${String(b.topic)} ${String(b.for)} 秒間${where ? ` (${where})` : ''}`;
    case 'never':
      return `来ないはず: ${String(b.topic)} ${String(b.for)} 秒間${where ? ` (${where})` : ''}`;
    case 'rate':
      return `周期: ${String(b.topic)} が ${String(b.min_hz ?? '')}〜${String(b.max_hz ?? '')} Hz (${String(b.for)} 秒)`;
    case 'throughput':
      return `件数の比: ${String(b.input)} → ${String(b.output)} が ${String(b.min_ratio)} 以上 (${String(b.for)} 秒)`;
    case 'latency':
      return `処理時間: ${String(b.input)} → ${String(b.output)} の p95 ≤ ${String(b.p95_ms)} ms (${String(b.for)} 秒${b.match === 'order' ? '、受信順の近似' : ''})`;
  }
}
