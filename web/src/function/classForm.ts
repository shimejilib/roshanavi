// Class-node part of the "＋ 関数・クラスノードを作る" dialog <-> ClassSpec (pure, unit-tested;
// docs/design/nodes.md). The class, its __init__ arguments and its methods come from the server's
// static parse (`ClassInfo`); the user edits the parameters' start values, binds methods to topics
// and marks action methods.

import type { ClassInfo, ClassInitParam, ClassMethodInfo, ClassMethodSpec, ClassOutputSpec, ClassSpec, InitValue } from '../api/classTypes';
import type { CallMode } from '../api/functionTypes';
import type { PortKind } from '../datakind/kinds';
import { t, tDynamic } from '../i18n';
import type { Result } from '../inject/buildRequest';
import { idFromName, normalizeTopic } from '../input/inputForm';
import { callModeFor, checkPort, EMPTY_ROW, NODE_NAME_RE, portSpec, rowsFor, suggestNodeName, type FnPortRow } from './functionForm';

/** What the user does with a method: leave it, bind it to topics, or make it a button / action topic. */
export type MethodUse = 'none' | 'topic' | 'action';

export interface OutputRow extends FnPortRow {
  /** Key of the returned dict (when `MethodForm.dict`). */
  key: string;
}

export interface MethodForm {
  method: string;
  use: MethodUse;
  call: CallMode;
  inputs: FnPortRow[];
  outputs: OutputRow[];
  /** The method returns a dict: one output row per key. */
  dict: boolean;
  rateHz: string;
  trigger: string;
}

export interface ClassForm {
  name: string;
  module: string;
  className: string;
  /** Start value of each `__init__` argument that is a parameter, as typed. */
  params: Record<string, string>;
  methods: MethodForm[];
  autostart: boolean;
}

const KEY_RE = /^[A-Za-z_][A-Za-z0-9_]{0,63}$/;
const INT_RE = /^[+-]?\d+$/;
const EMPTY_OUTPUT: OutputRow = { ...EMPTY_ROW, key: '' };
export const MAX_OUTPUT_ROWS = 8;

export function defaultClassForm(): ClassForm {
  return { name: '', module: '', className: '', params: {}, methods: [], autostart: true };
}

/** `MovingAverage` -> `moving_average`. */
export function snakeCase(name: string): string {
  const snake = name.replace(/([a-z0-9])([A-Z])/g, '$1_$2').replace(/([A-Z]+)([A-Z][a-z])/g, '$1_$2').toLowerCase();
  return suggestNodeName(snake);
}

/** A start value as text for the form (the argument's default). */
export function paramText(param: ClassInitParam): string {
  if (!param.has_default || param.default === null || param.default === undefined) return '';
  if (param.kind === 'json') return JSON.stringify(param.default);
  if (param.kind === 'numbers' && Array.isArray(param.default)) return param.default.join(', ');
  return String(param.default);
}

/** The arguments that become ROS parameters (the rest keep Python's default). */
export function parameterArgs(info: ClassInfo): ClassInitParam[] {
  return info.init_params.filter((p) => p.kind !== null);
}

function emptyMethod(info: ClassMethodInfo): MethodForm {
  const call = callModeFor(info);
  return {
    method: info.name,
    use: 'none',
    call,
    inputs: rowsFor(call, [], info.params.length).map((row, i) => ({ ...row, kind: info.params[i]?.kind ?? '' })),
    outputs: [{ ...EMPTY_OUTPUT, kind: info.returns_kind ?? '' }],
    dict: false,
    rateHz: '1',
    trigger: 'any',
  };
}

/** Default output topic of a bound method: `/<node>_out` for the first one, `/<node>_<method>_out` after. */
export function outputTopicFor(node: string, method: string, first: boolean): string {
  return first ? `/${node}_out` : `/${node}_${method}_out`;
}

/** Choosing a class: parameters with their defaults, a first guess for every method. */
export function applyClass(form: ClassForm, info: ClassInfo, nameTouched: boolean): ClassForm {
  const name = nameTouched && form.name ? form.name : snakeCase(info.name);
  let firstBound = true;
  const methods = info.methods.map((m) => {
    const base = emptyMethod(m);
    if (m.action_candidate) return { ...base, use: 'action' as const };
    if (!firstBound) return base;
    firstBound = false;
    const output = { ...base.outputs[0]!, topic: outputTopicFor(name, m.name, true) };
    return { ...base, use: 'topic' as const, outputs: [output] };
  });
  const params = Object.fromEntries(parameterArgs(info).map((p) => [p.name, paramText(p)]));
  return { ...form, className: info.name, name, params, methods };
}

export function setMethodUse(form: ClassForm, method: string, use: MethodUse, info?: ClassInfo): ClassForm {
  return {
    ...form,
    methods: form.methods.map((m) => {
      if (m.method !== method) return m;
      if (use !== 'topic' || m.outputs.some((o) => o.topic)) return { ...m, use };
      const first = !form.methods.some((x) => x.use === 'topic' && x.method !== method);
      const target = info?.methods.find((x) => x.name === method);
      const outputs = [{ ...(m.outputs[0] ?? EMPTY_OUTPUT), topic: outputTopicFor(form.name || snakeCase(form.className), method, first) }];
      return { ...m, use, call: target ? callModeFor(target) : m.call, outputs };
    }),
  };
}

/** Renaming the node: output topics still holding the suggested name follow it. */
export function renameNode(form: ClassForm, name: string): ClassForm {
  const before = form.name.trim();
  const after = name.trim();
  if (!before || !after) return { ...form, name };
  const methods = form.methods.map((m) => {
    const first = form.methods.find((x) => x.use === 'topic')?.method === m.method;
    const suggested = outputTopicFor(before, m.method, first);
    if (m.dict || m.outputs.length !== 1 || m.outputs[0]?.topic !== suggested) return m;
    return { ...m, outputs: [{ ...m.outputs[0], topic: outputTopicFor(after, m.method, first) }] };
  });
  return { ...form, name, methods };
}

export function updateMethod(form: ClassForm, method: string, patch: Partial<MethodForm>): ClassForm {
  return { ...form, methods: form.methods.map((m) => (m.method === method ? { ...m, ...patch } : m)) };
}

/** Switching the call mode resizes the input rows (none / one / at least two). */
export function setMethodCall(m: MethodForm, call: CallMode, argCount: number): MethodForm {
  return { ...m, call, inputs: rowsFor(call, m.inputs, argCount) };
}

/** Switching "returns a dict" on gives one row per key; off keeps the first row. */
export function setDict(m: MethodForm, dict: boolean, node: string): MethodForm {
  if (dict === m.dict) return m;
  if (!dict) return { ...m, dict, outputs: [{ ...(m.outputs[0] ?? EMPTY_OUTPUT), key: '' }] };
  const first = m.outputs[0] ?? EMPTY_OUTPUT;
  return { ...m, dict, outputs: [{ ...first, key: '', topic: first.topic && node ? `/${node}_` : first.topic }, { ...EMPTY_OUTPUT }] };
}

// ---- parameter values --------------------------------------------------------------------------
function parseParam(param: ClassInitParam, text: string): Result<InitValue> {
  const fail = (): Result<InitValue> => ({ ok: false, error: t('class.error.param', { name: param.name, kind: tDynamic(`class.paramKind.${param.kind ?? 'string'}`, 'class.paramKind.string') }) });
  const trimmed = text.trim();
  switch (param.kind) {
    case 'int':
      return INT_RE.test(trimmed) ? { ok: true, value: Number(trimmed) } : fail();
    case 'float': {
      const n = Number(trimmed);
      return trimmed !== '' && Number.isFinite(n) ? { ok: true, value: n } : fail();
    }
    case 'bool':
      return trimmed === 'true' || trimmed === 'false' ? { ok: true, value: trimmed === 'true' } : fail();
    case 'numbers': {
      const parts = trimmed === '' ? [] : trimmed.split(',').map((x) => Number(x.trim()));
      return parts.every((n) => Number.isFinite(n)) ? { ok: true, value: parts } : fail();
    }
    case 'json':
      try {
        JSON.parse(trimmed);
        return { ok: true, value: trimmed };
      } catch {
        return fail();
      }
    default:
      return { ok: true, value: text };
  }
}

/** The `params` of the spec: only what differs from the default, plus every required argument. */
function buildParams(form: ClassForm, info: ClassInfo): Result<Record<string, InitValue>> {
  const params: Record<string, InitValue> = {};
  for (const p of parameterArgs(info)) {
    const text = form.params[p.name] ?? '';
    if (text.trim() === '' && p.kind !== 'string') {
      if (!p.has_default) return { ok: false, error: t('class.error.paramRequired', { name: p.name }) };
      continue;
    }
    if (!p.has_default && text === '') return { ok: false, error: t('class.error.paramRequired', { name: p.name }) };
    if (p.has_default && text === paramText(p)) continue;
    const parsed = parseParam(p, text);
    if (!parsed.ok) return parsed;
    params[p.name] = parsed.value;
  }
  return { ok: true, value: params };
}

// ---- spec -------------------------------------------------------------------------------------
function methodProblem(m: MethodForm, inputsOf: readonly string[]): string | null {
  if (m.call === 'multi_input' && m.inputs.length < 2) return t('class.error.inputs', { method: m.method });
  if (m.call === 'periodic' && !(Number(m.rateHz) > 0)) return t('function.error.rate');
  for (const row of m.inputs) {
    const bad = checkPort(row);
    if (bad) return bad;
  }
  const used = filledOutputs(m);
  const keys = used.map((o) => o.key);
  if (m.dict && used.some((o) => !KEY_RE.test(o.key))) return t('class.error.key', { method: m.method });
  if (m.dict && new Set(keys).size !== keys.length) return t('class.error.keyDup', { method: m.method });
  if (m.dict && used.length === 0) return t('class.error.noOutputs', { method: m.method });
  for (const row of used) {
    const bad = checkPort(row);
    if (bad) return bad;
    if (inputsOf.includes(normalizeTopic(row.topic))) return t('function.error.sameTopic');
  }
  const topics = used.map((o) => normalizeTopic(o.topic));
  if (new Set(topics).size !== topics.length) return t('class.error.outputDup', { method: m.method });
  return null;
}

function filledOutputs(m: MethodForm): OutputRow[] {
  return m.outputs.filter((o) => (m.dict ? o.key.trim() !== '' || o.topic.trim() !== '' : o.topic.trim() !== ''));
}

function problem(form: ClassForm): string | null {
  if (!NODE_NAME_RE.test(form.name.trim())) return t('function.error.name');
  if (!form.module || !form.className) return t('class.error.module');
  const bound = form.methods.filter((m) => m.use === 'topic');
  if (bound.length === 0 && !form.methods.some((m) => m.use === 'action')) return t('class.error.nothing');
  const everyInput = bound.flatMap((m) => m.inputs.map((r) => normalizeTopic(r.topic)));
  for (const m of bound) {
    const bad = methodProblem(m, everyInput);
    if (bad) return bad;
  }
  const outputs = bound.flatMap((m) => filledOutputs(m).map((o) => normalizeTopic(o.topic)));
  if (new Set(outputs).size !== outputs.length) return t('class.error.outputDupAll');
  return null;
}

function outputSpec(m: MethodForm, row: OutputRow): ClassOutputSpec {
  return { ...portSpec(row), ...(m.dict ? { key: row.key.trim() } : {}) };
}

function methodSpec(m: MethodForm): ClassMethodSpec {
  const topics = m.inputs.map((r) => normalizeTopic(r.topic));
  return {
    method: m.method,
    call: m.call,
    inputs: m.call === 'periodic' ? [] : m.inputs.map(portSpec),
    outputs: filledOutputs(m).map((o) => outputSpec(m, o)),
    ...(m.call === 'periodic' ? { rate_hz: Number(m.rateHz) } : {}),
    ...(m.call === 'multi_input' && topics.includes(m.trigger) ? { trigger: m.trigger } : {}),
  };
}

export function buildClassSpec(form: ClassForm, info: ClassInfo | undefined, takenIds: readonly string[], existingId?: string): Result<ClassSpec> {
  const bad = problem(form);
  if (bad) return { ok: false, error: bad };
  if (!info) return { ok: false, error: t('class.error.module') };
  const params = buildParams(form, info);
  if (!params.ok) return params;
  const name = form.name.trim();
  const spec: ClassSpec = {
    id: existingId ?? idFromName(name, takenIds),
    name,
    module: form.module,
    class_name: form.className,
    params: params.value,
    methods: form.methods.filter((m) => m.use === 'topic').map(methodSpec),
    actions: form.methods.filter((m) => m.use === 'action').map((m) => m.method),
    autostart: form.autostart,
  };
  return { ok: true, value: spec };
}

// ---- editing an existing node --------------------------------------------------------------------
function rowOf(port: { topic: string; kind: PortKind; type?: string | null }): FnPortRow {
  return { topic: port.topic, kind: port.kind, type: port.type ?? '' };
}

function formOfBinding(info: ClassMethodInfo | undefined, spec: ClassMethodSpec): MethodForm {
  const base = info ? emptyMethod(info) : { method: spec.method, use: 'none' as const, call: spec.call, inputs: [], outputs: [], dict: false, rateHz: '1', trigger: 'any' };
  const dict = spec.outputs.some((o) => o.key);
  return {
    ...base,
    use: 'topic',
    call: spec.call,
    inputs: spec.inputs.map(rowOf),
    outputs: spec.outputs.length ? spec.outputs.map((o) => ({ ...rowOf(o), key: o.key ?? '' })) : [{ ...EMPTY_OUTPUT }],
    dict,
    rateHz: spec.rate_hz != null ? String(spec.rate_hz) : '1',
    trigger: spec.trigger ?? 'any',
  };
}

/** Prefill the dialog from an existing class node (and the class listing, when it has loaded). */
export function formFromClass(spec: ClassSpec, info: ClassInfo | undefined): ClassForm {
  const listed = info?.methods ?? [];
  const methods: MethodForm[] = listed.map((m) => {
    const bound = spec.methods.find((b) => b.method === m.name);
    if (bound) return formOfBinding(m, bound);
    return { ...emptyMethod(m), use: spec.actions.includes(m.name) ? 'action' : 'none' };
  });
  for (const bound of spec.methods) {
    if (!listed.some((m) => m.name === bound.method)) methods.push(formOfBinding(undefined, bound));
  }
  const params = Object.fromEntries((info ? parameterArgs(info) : []).map((p) => {
    const given = spec.params[p.name];
    return [p.name, given === undefined ? paramText(p) : Array.isArray(given) ? given.join(', ') : String(given)];
  }));
  return { name: spec.name, module: spec.module, className: spec.class_name, params, methods, autostart: spec.autostart ?? false };
}
