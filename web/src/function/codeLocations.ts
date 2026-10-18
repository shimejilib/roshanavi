// Pure logic of the 「コードの場所」 panel and the dependency info (docs/design/user-code.md):
// client-side checks that mirror the server (the server stays authoritative), plain-language
// texts for every not-found reason, and grouping of the module list by scope.

import type { CodeNotice, CodeProblem, CodeScope, DependencyHint, RequirementsCheck } from '../api/codeTypes';
import type { ModuleEntry, SkippedMember } from '../api/functionTypes';
import { t, type MessageKey, type Params } from '../i18n';

export const DEFAULT_SCAFFOLD_NAME = 'my_logic';
export const MAX_CODE_PATHS = 20;
export const MAX_INSTALLED_MODULES = 50;
export const PACKAGE_NAME_RE = /^[a-z][a-z0-9_]*$/;
export const MODULE_NAME_RE = /^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*){0,7}$/;
export const FUNCTION_NAME_RE = /^[A-Za-z][A-Za-z0-9_]{0,63}$/;
// eslint-disable-next-line no-control-regex
const CONTROL_RE = /[\u0000-\u001f\u007f]/;

// Names the server refuses too (Python keywords, a few standard / ROS libraries); the server's
// list is longer (the whole standard library) and has the last word.
const RESERVED_NAMES = new Set([
  'and', 'as', 'assert', 'async', 'await', 'break', 'class', 'continue',
  'def', 'del', 'elif', 'else', 'except', 'finally', 'for', 'from', 'global', 'if', 'import',
  'in', 'is', 'lambda', 'nonlocal', 'not', 'or', 'pass', 'raise', 'return', 'try', 'while',
  'with', 'yield', 'roshanavi', 'rclpy', 'numpy', 'yaml', 'json', 'os', 'sys', 'time', 'math',
  'test', 'logging', 'typing', 'random', 're', 'std_msgs', 'sensor_msgs', 'launch', 'launch_ros',
]);

export interface Check {
  key: MessageKey;
  params?: Params;
}

/** The scaffold's package name: the ROS package name rules (REP 144) and a Python name. */
export function checkPackageName(name: string): Check | null {
  if (name.length > 64) return { key: 'code.scaffold.invalidLong' };
  if (!PACKAGE_NAME_RE.test(name)) return { key: 'code.scaffold.invalid' };
  if (name.includes('__') || name.endsWith('_')) return { key: 'code.scaffold.invalidUnderscore' };
  if (RESERVED_NAMES.has(name)) return { key: 'code.scaffold.invalidReserved', params: { name } };
  return null;
}

export function checkCodePath(path: string, existing: readonly string[]): Check | null {
  const value = path.trim();
  if (!value) return { key: 'code.path.empty' };
  if (CONTROL_RE.test(path)) return { key: 'code.path.control' };
  if (value.length > 1024) return { key: 'code.path.long' };
  if (existing.includes(value)) return { key: 'code.path.duplicate' };
  if (existing.length >= MAX_CODE_PATHS) return { key: 'code.path.full', params: { max: MAX_CODE_PATHS } };
  return null;
}

export function checkModuleName(name: string, existing: readonly string[]): Check | null {
  const value = name.trim();
  if (!MODULE_NAME_RE.test(value)) return { key: 'code.module.invalid' };
  if (value.split('.')[0] === 'roshanavi') return { key: 'code.module.roshanavi' };
  if (existing.includes(value)) return { key: 'code.module.duplicate' };
  if (existing.length >= MAX_INSTALLED_MODULES) return { key: 'code.module.full', params: { max: MAX_INSTALLED_MODULES } };
  return null;
}

export function addEntry(list: readonly string[], value: string): string[] {
  const clean = value.trim();
  return !clean || list.includes(clean) ? [...list] : [...list, clean];
}

export function removeEntry(list: readonly string[], value: string): string[] {
  return list.filter((item) => item !== value);
}

function scopeName(scope: CodeScope | undefined): string {
  return scope ? t(`code.scopeName.${scope}` as MessageKey) : '';
}

/** The plain-Japanese reason and next step for one problem (paths are the user's own). */
export function problemText(p: CodeProblem): string {
  const params: Params = {
    path: p.path ?? '',
    file: p.file ?? '',
    line: p.line ?? '?',
    message: p.message ?? '',
    package: p.package ?? '<パッケージ名>',
    files: (p.files ?? []).join(', '),
    names: (p.names ?? []).join(', '),
    target: p.target ?? '',
    root: p.root ?? '',
    top: p.top ?? '',
    kept: p.kept ?? '',
    ignored: p.ignored ?? '',
    keptScope: scopeName(p.kept_scope),
    ignoredScope: scopeName(p.ignored_scope),
    module: p.module ?? '',
  };
  if (p.code === 'outside_symlink' && p.scope === 'code_path') return t('code.problem.outside_symlink_code_path', params);
  return t(`code.problem.${p.code}` as MessageKey, params);
}

export function placeHereText(place: { scope: CodeScope; root: string }): string {
  return t(place.scope === 'workspace' ? 'code.place.workspace' : 'code.place.code_path', { root: place.root });
}

export interface ModuleGroup {
  scope: CodeScope;
  label: string;
  modules: ModuleEntry[];
}

/** The module list by scope (A, B, C), keeping the server's order inside each group. */
export function groupModules(modules: readonly ModuleEntry[]): ModuleGroup[] {
  const order: CodeScope[] = ['workspace', 'code_path', 'installed'];
  return order
    .map((scope) => ({
      scope,
      label: t(`code.group.${scope}` as MessageKey),
      modules: modules.filter((m) => (m.scope ?? 'workspace') === scope),
    }))
    .filter((group) => group.modules.length > 0);
}

export function skippedText(skipped: readonly SkippedMember[]): string {
  const list = skipped.map((s) => t(`code.skipped.${s.reason}` as MessageKey, { name: s.name })).join('、');
  return t('code.skipped', { list });
}

export function noticeText(notice: CodeNotice): string {
  return t(`code.notice.${notice.code}` as MessageKey, {
    seconds: notice.seconds ?? '?',
    files: (notice.files ?? []).join(', '),
  });
}

export interface Line {
  text: string;
  bad: boolean;
}

/** Lines that summarize one requirements.txt comparison (bad: something is missing / wrong). */
export function requirementsLines(req: RequirementsCheck): Line[] {
  const lines: Line[] = [];
  if (req.missing.length > 0) {
    lines.push({ text: t('dep.reqMissing', { list: req.missing.map((m) => `${m.name}${m.spec}`).join(', ') }), bad: true });
  }
  if (req.mismatched.length > 0) {
    const list = req.mismatched.map((m) => `${m.name}${m.spec} (${m.installed})`).join(', ');
    lines.push({ text: t('dep.reqMismatch', { list }), bad: true });
  }
  if (req.ok > 0) lines.push({ text: t('dep.reqOk', { ok: req.ok }), bad: false });
  if (req.skipped.length > 0) lines.push({ text: t('dep.reqSkipped', { count: req.skipped.length }), bad: false });
  if (!req.exact) lines.push({ text: t('dep.reqInexact'), bad: false });
  return lines;
}

/** The missing library of a node's error, if any (the import error first, then the last call). */
export function missingModuleOf(
  problem: { missing_module?: string } | null | undefined,
  lastError: { missing_module?: string } | null | undefined,
): string | null {
  return problem?.missing_module ?? lastError?.missing_module ?? null;
}

export interface RouteStep {
  text: string;
  code?: string;
}

/** Route ① (package.xml + rosdep) as text + command blocks, or null when there is no key. */
export function rosdepRoute(hint: DependencyHint): RouteStep[] | null {
  const key = hint.rosdep.key ?? hint.rosdep.candidate;
  if (!key) return null;
  const steps: RouteStep[] = [];
  if (hint.rosdep.status === 'unavailable') {
    steps.push({ text: t('dep.route1.unverified', { key, reason: t(`dep.reason.${hint.rosdep.reason ?? 'error'}` as MessageKey) }) });
  }
  if (hint.package_xml && hint.exec_depend) {
    if (hint.already_declared) {
      steps.push({ text: t('dep.route1.declared', { file: hint.package_xml }) });
    } else {
      steps.push({ text: t('dep.route1.add', { file: hint.package_xml }), code: hint.exec_depend });
    }
    if (hint.rosdep_command) steps.push({ text: t('dep.route1.run'), code: hint.rosdep_command });
  } else if (hint.apt_command) {
    steps.push({ text: t('dep.route1.noPackage'), code: hint.apt_command });
  } else if (hint.exec_depend) {
    steps.push({ text: t('dep.route1.noPackage'), code: hint.exec_depend });
  }
  return steps;
}
