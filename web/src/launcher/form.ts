// Launcher form <-> TargetSpec (pure, unit-tested). The server re-validates
// everything; these checks only give early, plain-language feedback.

import type { ParamValue, TargetSpec } from '../api/types';
import { t } from '../i18n';

export interface KeyValueRow {
  key: string;
  value: string;
}

export interface TargetForm {
  id: string;
  kind: 'run' | 'launch';
  package: string;
  executable: string;
  launchFile: string;
  name: string;
  namespace: string;
  params: KeyValueRow[];
  remaps: KeyValueRow[];
  launchArgs: KeyValueRow[];
  args: string;
  paramsFile: string;
  mine: boolean;
  autostart: boolean;
  autoRestart: boolean;
  /** Kept from a launch-decomposition import (not editable). */
  importedFrom: string;
}

export const EMPTY_FORM: TargetForm = {
  id: '',
  kind: 'run',
  package: '',
  executable: '',
  launchFile: '',
  name: '',
  namespace: '',
  params: [],
  remaps: [],
  launchArgs: [],
  args: '',
  paramsFile: '',
  mine: true,
  autostart: false,
  autoRestart: false,
  importedFrom: '',
};

export type Result<T> = { ok: true; value: T } | { ok: false; error: string };

const PARAM_NAME = /^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$/;
const ARG_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;
const NODE_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;
const NAMESPACE = /^\/?[A-Za-z_][A-Za-z0-9_]*(\/[A-Za-z_][A-Za-z0-9_]*)*$/;
const ROS_NAME = /^~?\/?[A-Za-z_{][A-Za-z0-9_/{}~]*$/;
const CONTROL = /[\u0000-\u001f\u007f]/;
const ID_MAX = 56;

/** "true"/"false" -> boolean, integers / decimals -> number, anything else -> string. */
export function parseParamValue(text: string): ParamValue {
  const trimmed = text.trim();
  if (trimmed === 'true' || trimmed === 'false') return trimmed === 'true';
  if (/^-?\d+$/.test(trimmed) && Number.isSafeInteger(Number(trimmed))) return Number(trimmed);
  if (/^-?\d+\.\d+([eE][-+]?\d+)?$/.test(trimmed)) return Number(trimmed);
  return text;
}

/** A target id like `talker` / `talker-2` that is not in `taken`. */
export function makeTargetId(base: string, taken: Iterable<string>): string {
  const used = new Set(taken);
  let slug = base.toLowerCase().replace(/\.(launch\.)?(py|xml|yaml|yml)$/, '');
  slug = slug.replace(/[^a-z0-9_-]+/g, '_').replace(/^[_-]+|[_-]+$/g, '').slice(0, ID_MAX) || 'target';
  if (!/^[a-z0-9]/.test(slug)) slug = `t_${slug}`.slice(0, ID_MAX);
  let candidate = slug;
  for (let n = 2; used.has(candidate); n += 1) candidate = `${slug}-${n}`;
  return candidate;
}

function rowsToRecord<T>(
  rows: KeyValueRow[],
  checkKey: (key: string) => boolean,
  keyError: (key: string) => string,
  convert: (value: string) => T,
): Result<Record<string, T>> {
  const out: Record<string, T> = {};
  for (const row of rows) {
    const key = row.key.trim();
    if (!key && !row.value.trim()) continue;
    if (!checkKey(key)) return { ok: false, error: keyError(key) };
    if (CONTROL.test(row.value)) return { ok: false, error: t('launcher.err.control', { name: key }) };
    out[key] = convert(row.value);
  }
  return { ok: true, value: out };
}

function runFields(form: TargetForm): Result<Partial<TargetSpec>> {
  if (!form.executable) return { ok: false, error: t('launcher.err.needExecutable') };
  const name = form.name.trim();
  const namespace = form.namespace.trim();
  if (name && !NODE_NAME.test(name)) return { ok: false, error: t('launcher.err.name', { name }) };
  if (namespace && !NAMESPACE.test(namespace)) return { ok: false, error: t('launcher.err.namespace', { name: namespace }) };
  const params = rowsToRecord(form.params, (k) => PARAM_NAME.test(k), (k) => t('launcher.err.param', { name: k }), parseParamValue);
  if (!params.ok) return params;
  const remaps = rowsToRecord(
    form.remaps,
    (k) => ROS_NAME.test(k) && !k.startsWith('__'),
    (k) => t('launcher.err.remap', { name: k }),
    (v) => v.trim(),
  );
  if (!remaps.ok) return remaps;
  const badTo = Object.entries(remaps.value).find(([, to]) => !ROS_NAME.test(to));
  if (badTo) return { ok: false, error: t('launcher.err.remap', { name: badTo[1] }) };
  const args = form.args.split(/\s+/).filter(Boolean);
  return {
    ok: true,
    value: {
      executable: form.executable,
      ...(args.length ? { args } : {}),
      ...(Object.keys(params.value).length ? { params: params.value } : {}),
      ...(Object.keys(remaps.value).length ? { remaps: remaps.value } : {}),
      ...(name ? { name } : {}),
      ...(namespace ? { namespace } : {}),
      ...(form.paramsFile.trim() ? { params_file: form.paramsFile.trim() } : {}),
    },
  };
}

function launchFields(form: TargetForm): Result<Partial<TargetSpec>> {
  if (!form.launchFile) return { ok: false, error: t('launcher.err.needLaunchFile') };
  const args = rowsToRecord(form.launchArgs, (k) => ARG_NAME.test(k), (k) => t('launcher.err.arg', { name: k }), (v) => v);
  if (!args.ok) return args;
  const items = Object.entries(args.value).map(([k, v]) => `${k}:=${v}`);
  return { ok: true, value: { launch_file: form.launchFile, ...(items.length ? { args: items } : {}) } };
}

export function buildTargetSpec(form: TargetForm, takenIds: Iterable<string>): Result<TargetSpec> {
  if (!form.package) return { ok: false, error: t('launcher.err.needPackage') };
  const fields = form.kind === 'run' ? runFields(form) : launchFields(form);
  if (!fields.ok) return fields;
  const base = form.name.trim() || (form.kind === 'run' ? form.executable : form.launchFile);
  const id = form.id || makeTargetId(base, takenIds);
  return {
    ok: true,
    value: {
      id,
      kind: form.kind,
      package: form.package,
      ...fields.value,
      role: form.mine ? 'mine' : 'dependency',
      autostart: form.autostart,
      auto_restart: form.autoRestart,
      ...(form.importedFrom ? { imported_from: form.importedFrom } : {}),
    },
  };
}

function recordToRows(record: Record<string, unknown> | undefined): KeyValueRow[] {
  return Object.entries(record ?? {}).map(([key, value]) => ({ key, value: String(value) }));
}

/** Reverse of buildTargetSpec, for editing an existing target. */
export function formFromSpec(spec: TargetSpec): TargetForm {
  const launchArgs = spec.kind === 'launch'
    ? (spec.args ?? []).map((item) => {
        const at = item.indexOf(':=');
        return { key: item.slice(0, at), value: item.slice(at + 2) };
      })
    : [];
  return {
    ...EMPTY_FORM,
    id: spec.id,
    kind: spec.kind,
    package: spec.package,
    executable: spec.executable ?? '',
    launchFile: spec.launch_file ?? '',
    name: spec.name ?? '',
    namespace: spec.namespace ?? '',
    params: recordToRows(spec.params),
    remaps: recordToRows(spec.remaps),
    launchArgs,
    args: spec.kind === 'run' ? (spec.args ?? []).join(' ') : '',
    paramsFile: spec.params_file ?? '',
    mine: spec.role === 'mine',
    autostart: spec.autostart ?? false,
    autoRestart: spec.auto_restart ?? false,
    importedFrom: spec.imported_from ?? '',
  };
}
