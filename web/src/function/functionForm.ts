// "＋ 関数ノードを作る" dialog <-> FunctionSpec (pure, unit-tested; docs/design/nodes.md).

import type { CallMode, FunctionInfo, FunctionPortSpec, FunctionSpec } from '../api/functionTypes';
import type { PortKind } from '../datakind/kinds';
import { t } from '../i18n';
import type { Result } from '../inject/buildRequest';
import { idFromName, normalizeTopic } from '../input/inputForm';

export interface FnPortRow {
  topic: string;
  kind: PortKind | '';
  type: string;
}

export interface FunctionForm {
  name: string;
  module: string;
  fn: string;
  call: CallMode;
  inputs: FnPortRow[];
  output: FnPortRow;
  rateHz: string;
  /** 'any' or one input topic (multi_input). */
  trigger: string;
  autostart: boolean;
}

export const MAX_FUNCTION_INPUTS = 8;
export const TOPIC_RE = /^(\/[A-Za-z_][A-Za-z0-9_]*)+$/;
export const NODE_NAME_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;
export const EMPTY_ROW: FnPortRow = { topic: '', kind: '', type: '' };

export function defaultFunctionForm(topic = ''): FunctionForm {
  return {
    name: '',
    module: '',
    fn: '',
    call: 'on_message',
    inputs: [{ ...EMPTY_ROW, topic: normalizeTopic(topic) }],
    output: { ...EMPTY_ROW },
    rateHz: '1',
    trigger: 'any',
    autostart: true,
  };
}

/** How a function is called by default, from its parameters (static signature). */
export function callModeFor(info: Pick<FunctionInfo, 'params' | 'required'>): CallMode {
  if (info.params.length === 0) return 'periodic';
  return info.required >= 2 ? 'multi_input' : 'on_message';
}

/** Input rows for a call mode: none (periodic), one, or at least two. */
export function rowsFor(call: CallMode, rows: readonly FnPortRow[], count = 2): FnPortRow[] {
  if (call === 'periodic') return [];
  if (call === 'on_message') return [rows[0] ?? { ...EMPTY_ROW }];
  const wanted = Math.min(MAX_FUNCTION_INPUTS, Math.max(2, count, rows.length));
  return Array.from({ length: wanted }, (_, i) => rows[i] ?? { ...EMPTY_ROW });
}

/** Valid ROS node name from a function name (`shout` -> `shout`, `2x` -> `_2x`). */
export function suggestNodeName(fn: string): string {
  const clean = fn.replace(/[^A-Za-z0-9_]/g, '_');
  return /^[A-Za-z_]/.test(clean) ? clean : `_${clean}`;
}

/** Choosing a function: call mode, argument rows and kinds from its annotations, names. */
export function applyFunction(form: FunctionForm, info: FunctionInfo, nameTouched: boolean): FunctionForm {
  const call = callModeFor(info);
  const rows = rowsFor(call, form.inputs, info.params.length).map((row, i) => {
    const hint = info.params[i]?.kind;
    return row.kind || !hint ? row : { ...row, kind: hint };
  });
  const output = form.output.kind || !info.returns_kind ? form.output : { ...form.output, kind: info.returns_kind };
  const name = nameTouched && form.name ? form.name : suggestNodeName(info.name);
  return { ...form, fn: info.name, call, inputs: rows, output: { ...output, topic: output.topic || `/${name}_out` }, name };
}

export function portSpec(row: FnPortRow): FunctionPortSpec {
  return { topic: normalizeTopic(row.topic), kind: row.kind as PortKind, ...(row.type ? { type: row.type } : {}) };
}

/** An empty topic is a port that is not wired yet: it is wired on the map later (docs/design/wiring.md). */
export function checkPort(row: FnPortRow): string | null {
  const topic = normalizeTopic(row.topic);
  if (topic && !TOPIC_RE.test(topic)) return t('function.error.topic', { topic: row.topic });
  if (!row.kind) return t('function.error.kind', { topic: topic || t('wiring.port.unwiredShort') });
  return null;
}

function problem(form: FunctionForm): string | null {
  if (!NODE_NAME_RE.test(form.name.trim())) return t('function.error.name');
  if (!form.module || !form.fn) return t('function.error.module');
  if (form.call === 'multi_input' && form.inputs.length < 2) return t('function.error.inputs');
  if (form.call === 'periodic' && !(Number(form.rateHz) > 0)) return t('function.error.rate');
  for (const row of [...form.inputs, form.output]) {
    const bad = checkPort(row);
    if (bad) return bad;
  }
  const out = normalizeTopic(form.output.topic);
  if (out && form.inputs.some((row) => normalizeTopic(row.topic) === out)) return t('function.error.sameTopic');
  return null;
}

export function buildFunctionSpec(form: FunctionForm, takenIds: readonly string[], existingId?: string): Result<FunctionSpec> {
  const bad = problem(form);
  if (bad) return { ok: false, error: bad };
  const name = form.name.trim();
  const topics = form.inputs.map((row) => normalizeTopic(row.topic));
  const spec: FunctionSpec = {
    id: existingId ?? idFromName(name, takenIds),
    name,
    module: form.module,
    function: form.fn,
    call: form.call,
    inputs: form.call === 'periodic' ? [] : form.inputs.map(portSpec),
    output: portSpec(form.output),
    autostart: form.autostart,
    ...(form.call === 'periodic' ? { rate_hz: Number(form.rateHz) } : {}),
    ...(form.call === 'multi_input' && topics.includes(form.trigger) ? { trigger: form.trigger } : {}),
  };
  return { ok: true, value: spec };
}

function rowOf(port: FunctionPortSpec): FnPortRow {
  return { topic: port.topic, kind: port.kind, type: port.type ?? '' };
}

/** Prefill the dialog from an existing function node. */
export function formFromFunction(spec: FunctionSpec): FunctionForm {
  return {
    name: spec.name,
    module: spec.module,
    fn: spec.function,
    call: spec.call,
    inputs: spec.inputs.map(rowOf),
    output: rowOf(spec.output),
    rateHz: spec.rate_hz != null ? String(spec.rate_hz) : '1',
    trigger: spec.trigger ?? 'any',
    autostart: spec.autostart ?? false,
  };
}
