// Launch decomposition import: preview display and the commit request (pure, DESIGN §4.16).

import type { ImportArgument, ImportCommitRequest, ImportNode, ImportPlan, ImportSource } from '../api/nodeListTypes';
import type { WorkspacePackage } from '../api/types';
import { t, tDynamic } from '../i18n';

export type ImportMode = 'nodes' | 'whole';

export interface SourceForm {
  kind: 'package' | 'path';
  package: string;
  launchFile: string;
  path: string;
}

export const EMPTY_SOURCE: SourceForm = { kind: 'package', package: '', launchFile: '', path: '' };

/** Packages that have launch files (workspace first, as discovery sorts them). */
export function launchPackages(packages: readonly WorkspacePackage[]): WorkspacePackage[] {
  return packages.filter((p) => p.built && p.launch_files.length > 0);
}

export function sourceFromForm(form: SourceForm): ImportSource | null {
  if (form.kind === 'package') {
    return form.package && form.launchFile ? { kind: 'package', package: form.package, launch_file: form.launchFile } : null;
  }
  const path = form.path.trim();
  return path ? { kind: 'path', path } : null;
}

/** Argument fields: the user's value, else the declared default ('' when required). */
export function initialArgValues(args: readonly ImportArgument[], current: Record<string, string>): Record<string, string> {
  return Object.fromEntries(args.map((a) => [a.name, current[a.name] ?? a.default ?? '']));
}

/** Only values that differ from the default are sent (keeps the whole-launch target tidy). */
export function changedArgs(args: readonly ImportArgument[], values: Record<string, string>): Record<string, string> {
  return Object.fromEntries(
    args.filter((a) => values[a.name] !== undefined && values[a.name] !== (a.default ?? null) && values[a.name] !== '')
      .map((a) => [a.name, values[a.name] ?? '']),
  );
}

export function defaultSelection(plan: Pick<ImportPlan, 'nodes'>): Set<number> {
  return new Set(plan.nodes.filter((n) => n.importable && !n.duplicate_of).map((n) => n.index));
}

export function nodeTitle(node: Pick<ImportNode, 'fq_name' | 'spec'>): string {
  return node.fq_name ?? t('import.unnamed', { exe: `${node.spec.package}/${node.spec.executable ?? '?'}` });
}

/** One-line facts about a proposed target: executable, parameters, remaps, arguments. */
export function nodeFacts(node: ImportNode): string[] {
  const spec = node.spec;
  const facts = [`${spec.package} / ${spec.executable ?? '?'}`];
  const params = Object.keys(spec.params ?? {}).length;
  if (params > 0) facts.push(t('import.facts.params', { n: params }));
  const extra = Object.keys(node.file_params).length;
  if (extra > 0) facts.push(t('import.facts.fileParams', { n: extra }));
  const remaps = Object.entries(spec.remaps ?? {});
  if (remaps.length > 0) facts.push(t('import.facts.remaps', { list: remaps.map(([a, b]) => `${a} → ${b}`).join(', ') }));
  if ((spec.args ?? []).length > 0) facts.push(t('import.facts.args', { list: (spec.args ?? []).join(' ') }));
  if (node.lifecycle) facts.push(t('import.facts.lifecycle'));
  return facts;
}

export function reasonText(code: string): string {
  return tDynamic(`import.reason.${code}`, 'import.reason.unknown', { code });
}

export function warningText(code: string): string {
  return tDynamic(`import.warn.${code}`, 'import.warn.unknown', { code });
}

export function problemText(node: Pick<ImportNode, 'problem' | 'duplicate_of'>): string | null {
  if (node.problem) return `${tDynamic(`error.${node.problem.code}`, 'error.unknown')} (${node.problem.message})`;
  if (node.duplicate_of) return t('import.duplicate', { id: node.duplicate_of });
  return null;
}

export function commitRequest(plan: ImportPlan, mode: ImportMode, selection: ReadonlySet<number>,
  role: 'mine' | 'dependency'): ImportCommitRequest {
  const indices = mode === 'nodes' ? plan.nodes.filter((n) => n.importable && selection.has(n.index)).map((n) => n.index) : [];
  return { preview_id: plan.preview_id, mode, indices, role, autostart: false };
}

/** Why the import button is disabled (null = can import). */
export function importBlocker(plan: ImportPlan, mode: ImportMode, selection: ReadonlySet<number>): string | null {
  if (plan.missing_args.length > 0) return t('import.blocker.args', { names: plan.missing_args.join(', ') });
  if (mode === 'whole') return plan.whole ? null : reasonText(plan.whole_reason ?? 'not_in_package');
  return commitRequest(plan, mode, selection, 'dependency').indices.length > 0 ? null : t('import.blocker.none');
}
