// Parameter value <-> text field (pure, unit-tested). The server checks again strictly.

import type { ParamInfo, ParamJsonValue, ParamType } from '../api/nodeTypes';
import { t } from '../i18n';
import type { Result } from '../inject/buildRequest';

const INT_RE = /^[+-]?\d+$/;

export function paramText(value: ParamJsonValue, type: ParamType): string {
  if (value === null || value === undefined) return '';
  if (Array.isArray(value)) return type === 'string_array' ? JSON.stringify(value) : value.join(', ');
  return String(value);
}

function scalar(text: string, kind: string): Result<boolean | number | string> {
  const v = text.trim();
  if (kind === 'bool') {
    if (v === 'true' || v === 'false') return { ok: true, value: v === 'true' };
    return { ok: false, error: t('params.error.bool') };
  }
  if (kind === 'integer' || kind === 'byte') {
    const n = Number(v);
    if (!INT_RE.test(v) || !Number.isSafeInteger(n)) return { ok: false, error: t('params.error.integer') };
    if (kind === 'byte' && (n < 0 || n > 255)) return { ok: false, error: t('params.error.byte') };
    return { ok: true, value: n };
  }
  if (kind === 'double') {
    const n = Number(v);
    if (v === '' || !Number.isFinite(n)) return { ok: false, error: t('params.error.double') };
    return { ok: true, value: n };
  }
  return { ok: true, value: text };
}

function splitArray(text: string, type: ParamType): Result<string[]> {
  const v = text.trim();
  if (v.startsWith('[')) {
    try {
      const parsed: unknown = JSON.parse(v);
      if (Array.isArray(parsed)) return { ok: true, value: parsed.map((x) => (typeof x === 'string' ? x : JSON.stringify(x))) };
    } catch {
      return { ok: false, error: t('params.error.array') };
    }
  }
  if (v === '') return { ok: true, value: [] };
  return { ok: true, value: type === 'string_array' ? v.split(',').map((s) => s.trim()) : v.split(',') };
}

/** Text from the field -> JSON value of `type` (plain-language error otherwise). */
export function parseParamInput(text: string, type: ParamType): Result<ParamJsonValue> {
  if (type === 'not_set') return { ok: false, error: t('params.error.notSet') };
  if (!type.endsWith('_array')) {
    const value = scalar(text, type);
    return value.ok ? { ok: true, value: value.value } : value;
  }
  const parts = splitArray(text, type);
  if (!parts.ok) return parts;
  const kind = type === 'byte_array' ? 'byte' : type.slice(0, -'_array'.length);
  const values: (boolean | number | string)[] = [];
  for (const part of parts.value) {
    const value = scalar(part, kind);
    if (!value.ok) return value;
    values.push(value.value);
  }
  return { ok: true, value: values as ParamJsonValue };
}

export type EditState = 'editable' | 'readOnly' | 'locked' | 'unknownType';

/** Can this row be edited now? External nodes stay locked until the user confirms. */
export function editState(param: ParamInfo, external: boolean, unlocked: boolean): EditState {
  if (param.read_only) return 'readOnly';
  if (param.type === 'not_set') return 'unknownType';
  if (external && !unlocked) return 'locked';
  return 'editable';
}
