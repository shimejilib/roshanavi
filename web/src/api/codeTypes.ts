// Where function / class node code comes from (docs/design/user-code.md): the 「コードの場所」 report,
// the scaffold result, the dependency hint and what the node reports about its Python.

export type CodeScope = 'workspace' | 'code_path' | 'installed';

export type CodeProblemCode =
  | 'no_src'
  | 'no_init'
  | 'namespace_package'
  | 'loose_files'
  | 'not_ros_package'
  | 'syntax_error'
  | 'no_members'
  | 'private_only'
  | 'submodule_empty'
  | 'outside_symlink'
  | 'reserved_name'
  | 'name_collision'
  | 'code_path_invalid'
  | 'code_path_empty'
  | 'installed_not_found';

/** One reason why code did not become a candidate (paths are the user's real paths). */
export interface CodeProblem {
  code: CodeProblemCode;
  path?: string;
  file?: string;
  line?: number | null;
  message?: string;
  package?: string;
  files?: string[];
  names?: string[];
  skipped?: string[];
  target?: string;
  root?: string;
  command?: string;
  top?: string;
  kept?: string;
  ignored?: string;
  kept_scope?: CodeScope;
  ignored_scope?: CodeScope;
  module?: string;
  scope?: CodeScope;
}

export interface PythonInfo {
  executable: string | null;
  version: string | null;
  prefix?: string | null;
  venv: boolean | null;
  error?: string | null;
  /** The venv interpreter nodes are started with (`ros2 run --prefix`), when one is active. */
  forced?: string | null;
}

export interface CodePathStatus {
  path: string;
  real: string | null;
  status: 'ok' | 'invalid';
  error?: string;
  packages: { top: string; dir: string; layout: 'flat' | 'src' | 'package' }[];
}

export interface InstalledStatus {
  module: string;
  status: 'found' | 'not_found' | 'extension' | 'namespace' | 'shadowed';
  file: string | null;
  listable: boolean;
  shadowed_by?: string;
}

export interface CodeSettings {
  code_paths: string[];
  installed_modules: string[];
}

export interface CodeLocationsReport {
  workspace: string;
  src: string;
  src_exists: boolean;
  src_writable: boolean;
  scopes: {
    workspace: { root: string; packages: { top: string; ros_package: string | null; dir: string }[] };
    code_paths: CodePathStatus[];
    installed_modules: InstalledStatus[];
  };
  installed_listed: number;
  problems: CodeProblem[];
  place_here: { scope: CodeScope; root: string }[];
  python: PythonInfo | null;
  settings: CodeSettings;
}

export interface ScaffoldResult {
  package: string;
  directory: string;
  module: string;
  function: string;
  class_name: string;
  files: string[];
}

export interface RosdepLookup {
  status: 'found' | 'not_found' | 'unavailable';
  key?: string;
  installer?: string;
  packages?: string[];
  reason?: 'rosdep_missing' | 'no_database' | 'timeout' | 'error';
  candidate?: string;
  tried?: string[];
}

export interface DependencyHint {
  missing: string;
  top: string;
  rosdep: RosdepLookup;
  scope: CodeScope | null;
  route: 'rosdep' | 'venv';
  python: { executable: string | null; version: string | null; venv: boolean | null };
  exec_depend?: string;
  apt_command?: string | null;
  package_xml?: string;
  already_declared?: boolean;
  rosdep_command?: string;
  venv: { pip_name: string; pip_name_differs: boolean; requirements: string | null; commands: string[]; active: boolean };
  note?: 'code_path';
}

export type NoticeCode =
  | 'slow_import'
  | 'imports_rclpy'
  | 'extension_module'
  | 'extension_no_reload'
  | 'no_hot_reload_installed';

export interface CodeNotice {
  code: NoticeCode;
  seconds?: number;
  files?: string[];
}

export interface RequirementsCheck {
  file: string;
  missing: { name: string; spec: string; line: number }[];
  mismatched: { name: string; spec: string; installed: string; line: number }[];
  skipped: { line: number; text: string; reason: string }[];
  ok: number;
  exact: boolean;
  error?: string;
}

/** What a function / class node reports about where its code runs (status `environment`). */
export interface NodeEnvironment {
  python: { executable: string; version: string; prefix: string; venv: boolean; virtual_env: string | null };
  scope?: CodeScope;
  loaded_from?: string | null;
  requirements: RequirementsCheck[];
}
