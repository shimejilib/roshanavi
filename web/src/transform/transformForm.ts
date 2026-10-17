// "＋ 変換ノードを作る" editor <-> TransformSpec (pure, unit-tested; docs/design/nodes.md).

import type { TransformSpec } from '../api/transformTypes';
import { t } from '../i18n';
import { parsePayload, type Result } from '../inject/buildRequest';
import { idFromName, normalizeTopic } from '../input/inputForm';
import type { PortKind } from '../datakind/kinds';

export interface InputRow {
  topic: string;
  /** データの種類 shown for the row (the spec only stores the type). */
  kind?: PortKind | '';
  type: string;
  alias: string;
}

export interface TransformForm {
  name: string;
  inputs: InputRow[];
  mode: 'map' | 'relay';
  outputTopic: string;
  outputKind?: PortKind | '';
  outputType: string;
  /** Output message as YAML; strings with ${...} are expressions. Empty = forward the input. */
  mappingYaml: string;
  condition: string;
  /** 'any' or one input alias. */
  trigger: string;
  delayMinMs: string;
  delayMaxMs: string;
  throttleHz: string;
  /** 0..100 (%). */
  dropPercent: string;
  autostart: boolean;
}

export const HEAVY_TYPES = new Set([
  'sensor_msgs/msg/Image',
  'sensor_msgs/msg/CompressedImage',
  'sensor_msgs/msg/PointCloud2',
  'sensor_msgs/msg/PointCloud',
]);
export const MAX_INPUTS = 8;

const TYPE_RE = /^[A-Za-z][A-Za-z0-9_]*\/msg\/[A-Za-z][A-Za-z0-9_]*$/;
const TOPIC_RE = /^(\/[A-Za-z_][A-Za-z0-9_]*)+$/;
const NODE_NAME_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;
const ALIAS_RE = /^[a-z][a-z0-9_]{0,31}$/;
const RESERVED = new Set(['i', 't', 'now', 'pi', 'e']);

export function isHeavy(type: string): boolean {
  return HEAVY_TYPES.has(type.trim());
}

/** Default expression names: msg (one input), msg1, msg2 ... (several). */
export function defaultAlias(index: number, count: number): string {
  return count === 1 ? 'msg' : `msg${index + 1}`;
}

/** `/chatter` -> `chatter_transform` (a valid node name). */
export function suggestTransformName(topic: string): string {
  const last = topic.split('/').filter(Boolean).pop() ?? 'topic';
  return `${last.replace(/[^A-Za-z0-9_]/g, '_').replace(/^(\d)/, '_$1')}_transform`;
}

export function defaultTransformForm(topic = '', type = ''): TransformForm {
  const input = normalizeTopic(topic);
  return {
    name: suggestTransformName(input || '/topic'),
    inputs: [{ topic: input, type, alias: 'msg' }],
    mode: isHeavy(type) ? 'relay' : 'map',
    outputTopic: input ? `${input}_out` : '',
    outputType: type,
    mappingYaml: '',
    condition: '',
    trigger: 'any',
    delayMinMs: '',
    delayMaxMs: '',
    throttleHz: '',
    dropPercent: '',
    autostart: true,
  };
}

/**
 * Starting mapping: every leaf of the output template reads the same field of
 * the input (`${msg.linear.x}`), when the input has that field. Fields the
 * input lacks keep their default value. Arrays are copied whole.
 */
export function mappingFromTemplate(template: Record<string, unknown>, inputTemplate: Record<string, unknown> | null,
  alias: string): Record<string, unknown> {
  const walk = (out: unknown, input: unknown, path: string): unknown => {
    if (out && typeof out === 'object' && !Array.isArray(out)) {
      const inObj = input && typeof input === 'object' && !Array.isArray(input) ? (input as Record<string, unknown>) : null;
      return Object.fromEntries(Object.entries(out as Record<string, unknown>).map(([key, value]) =>
        [key, walk(value, inObj ? inObj[key] : undefined, path ? `${path}.${key}` : key)]));
    }
    return input === undefined ? out : `\${${alias}.${path}}`;
  };
  return walk(template, inputTemplate ?? undefined, '') as Record<string, unknown>;
}

function nonNegative(text: string): number | null {
  const n = Number(text);
  return text.trim() !== '' && Number.isFinite(n) && n >= 0 ? n : null;
}

function checkInputs(form: TransformForm): string | null {
  if (form.inputs.length === 0 || form.inputs.length > MAX_INPUTS) return t('transform.error.inputCount', { max: MAX_INPUTS });
  const aliases = new Set<string>();
  for (const row of form.inputs) {
    if (!TOPIC_RE.test(normalizeTopic(row.topic))) return t('transform.error.inputTopic');
    if (!TYPE_RE.test(row.type.trim())) return t('transform.error.inputType', { topic: row.topic });
    const alias = row.alias.trim();
    if (!ALIAS_RE.test(alias) || RESERVED.has(alias)) return t('transform.error.alias', { alias });
    if (aliases.has(alias)) return t('transform.error.aliasDuplicate', { alias });
    aliases.add(alias);
  }
  return null;
}

function checkBasics(form: TransformForm): string | null {
  if (!NODE_NAME_RE.test(form.name.trim())) return t('input.error.name');
  const inputs = checkInputs(form);
  if (inputs) return inputs;
  const output = normalizeTopic(form.outputTopic);
  if (!TOPIC_RE.test(output)) return t('transform.error.outputTopic');
  if (form.inputs.some((row) => normalizeTopic(row.topic) === output)) return t('transform.error.loop');
  if (form.mode === 'map' && !TYPE_RE.test(form.outputType.trim())) return t('transform.error.outputType');
  if (form.mode === 'relay' && form.inputs.length !== 1) return t('transform.error.relayOneInput');
  if (form.mode === 'map' && form.inputs.some((row) => isHeavy(row.type))) return t('transform.error.heavy');
  return null;
}

function timing(form: TransformForm): Result<Pick<TransformSpec, 'delay' | 'throttle_hz' | 'drop_ratio'>> {
  const value: Pick<TransformSpec, 'delay' | 'throttle_hz' | 'drop_ratio'> = { drop_ratio: 0 };
  if (form.delayMinMs.trim() || form.delayMaxMs.trim()) {
    const min = nonNegative(form.delayMinMs || '0');
    const max = form.delayMaxMs.trim() ? nonNegative(form.delayMaxMs) : null;
    if (min == null || min > 60000 || (form.delayMaxMs.trim() && (max == null || max < min || max > 60000))) {
      return { ok: false, error: t('transform.error.delay') };
    }
    value.delay = max != null && max !== min ? { min_ms: min, max_ms: max } : { min_ms: min };
  }
  if (form.throttleHz.trim()) {
    const hz = nonNegative(form.throttleHz);
    if (hz == null || hz <= 0 || hz > 1000) return { ok: false, error: t('transform.error.throttle') };
    value.throttle_hz = hz;
  }
  if (form.dropPercent.trim()) {
    const pct = nonNegative(form.dropPercent);
    if (pct == null || pct > 100) return { ok: false, error: t('transform.error.drop') };
    value.drop_ratio = pct / 100;
  }
  return { ok: true, value };
}

/** Build the spec; `existingId` keeps the id when editing. `lenient` (preview) skips name checks. */
export function buildTransformSpec(form: TransformForm, takenIds: readonly string[], existingId?: string,
  lenient = false): Result<TransformSpec> {
  const problem = checkBasics(lenient ? { ...form, name: form.name.trim() || 'preview' } : form);
  if (problem) return { ok: false, error: problem };
  const times = timing(form);
  if (!times.ok) return times;
  const name = form.name.trim() || 'preview';
  const inputs = form.inputs.map((row) => ({ topic: normalizeTopic(row.topic), type: row.type.trim(), alias: row.alias.trim() }));
  const spec: TransformSpec = {
    id: existingId ?? idFromName(name, takenIds),
    name,
    inputs,
    output: { topic: normalizeTopic(form.outputTopic), qos: { reliability: 'reliable', durability: 'volatile', depth: 10 } },
    mode: form.mode,
    trigger: inputs.length > 1 && inputs.some((row) => row.alias === form.trigger) ? form.trigger : 'any',
    autostart: form.autostart,
    ...times.value,
  };
  if (form.mode === 'relay') return { ok: true, value: spec };
  spec.output.type = form.outputType.trim();
  if (form.condition.trim()) spec.condition = form.condition.trim();
  if (form.mappingYaml.trim()) {
    const mapping = parsePayload(form.mappingYaml);
    if (!mapping.ok) return mapping;
    spec.mapping = mapping.value;
  } else if (inputs.length > 1) {
    return { ok: false, error: t('transform.error.needMapping') };
  }
  return { ok: true, value: spec };
}

/** Prefill the editor from an existing transform node. */
export function formFromTransform(spec: TransformSpec, yamlOf: (value: Record<string, unknown>) => string): TransformForm {
  return {
    name: spec.name,
    inputs: spec.inputs.map((row, i) => ({ topic: row.topic, type: row.type, alias: row.alias ?? defaultAlias(i, spec.inputs.length) })),
    mode: spec.mode,
    outputTopic: spec.output.topic,
    outputType: spec.output.type ?? spec.inputs[0]?.type ?? '',
    mappingYaml: spec.mapping ? yamlOf(spec.mapping) : '',
    condition: spec.condition ?? '',
    trigger: spec.trigger ?? 'any',
    delayMinMs: spec.delay ? String(spec.delay.min_ms) : '',
    delayMaxMs: spec.delay?.max_ms != null ? String(spec.delay.max_ms) : '',
    throttleHz: spec.throttle_hz != null ? String(spec.throttle_hz) : '',
    dropPercent: spec.drop_ratio ? String(Math.round(spec.drop_ratio * 1000) / 10) : '',
    autostart: spec.autostart ?? false,
  };
}

/** Renumber default aliases (msg <-> msg1, msg2 ...) after inputs were added / removed. */
export function withInputs(form: TransformForm, inputs: InputRow[]): TransformForm {
  const isDefault = (alias: string) => alias === 'msg' || /^msg\d+$/.test(alias);
  const renamed = inputs.map((row, i) => (isDefault(row.alias) ? { ...row, alias: defaultAlias(i, inputs.length) } : row));
  const trigger = renamed.some((row) => row.alias === form.trigger) ? form.trigger : 'any';
  return { ...form, inputs: renamed, trigger, mode: renamed.length > 1 ? 'map' : form.mode };
}
