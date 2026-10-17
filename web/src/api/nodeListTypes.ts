// Node list (GET /api/node-list), lifecycle and launch-import API shapes (docs/design/launcher.md, docs/design/ui.md).

import type { MappingConfidence, Target, TargetSpec } from './types';

export type RowControl = 'target' | 'lifecycle' | 'none';
export type RowRole = 'mine' | 'dependency' | 'dummy' | 'transform' | 'function' | 'other';

export interface RowOrigin {
  kind: 'run' | 'launch' | 'dummy' | 'transform' | 'function' | 'class' | 'external';
  package?: string;
  executable?: string;
  launch_file?: string;
  imported_from?: string;
  topic?: string;
}

export interface NodeRow {
  key: string;
  /** ROS node id; null for a registered target with no node on the graph. */
  node: string | null;
  name: string;
  role: RowRole;
  status: string;
  running: boolean;
  exit_code?: number | null;
  origin: RowOrigin;
  pid: number | null;
  confidence: MappingConfidence | null;
  target_id: string | null;
  group: string | null;
  lifecycle: { state: string | null } | null;
  control: RowControl;
  reason: 'external' | 'invalid' | null;
  problem?: string | null;
}

export interface NodeGroup {
  id: string;
  kind: 'launch' | 'process';
  label: string;
  target_id: string;
  nodes: string[];
  status: string;
}

export interface NodeListResponse {
  rows: NodeRow[];
  groups: NodeGroup[];
  /** Launcher targets of the same snapshot as `rows` (bulk plans use these, never live state). */
  targets: Target[];
}

export type LifecycleTransition = 'configure' | 'activate' | 'deactivate' | 'cleanup';
export type LifecycleGoal = 'active' | 'inactive';

export interface LifecycleInfo {
  node: string;
  role: RowRole;
  state: { id: number; label: string };
  transitions: { id: number; label: LifecycleTransition; goal: string }[];
  steps?: LifecycleTransition[];
}

export interface LifecycleRequest {
  transition?: LifecycleTransition;
  goal?: LifecycleGoal;
  allow_external: boolean;
}

export type ImportSource =
  | { kind: 'package'; package: string; launch_file: string }
  | { kind: 'path'; path: string };

export interface ImportArgument {
  name: string;
  default: string | null;
  description: string;
  choices: string[] | null;
  conditional: boolean;
}

export interface ImportIssue {
  code: string;
  detail: string;
}

export interface ImportNode {
  index: number;
  fq_name: string | null;
  lifecycle: boolean;
  file: string | null;
  spec: TargetSpec;
  file_params: Record<string, unknown>;
  param_files: string[];
  warnings: ImportIssue[];
  importable: boolean;
  problem: { code: string; message: string } | null;
  duplicate_of: string | null;
}

export interface ImportEntity {
  kind: string;
  code: string;
  detail: string;
  file?: string;
  message?: string;
  composable_nodes?: string[];
}

export interface ImportPlan {
  preview_id: string;
  file: string;
  origin: string;
  args: Record<string, string>;
  arguments: ImportArgument[];
  missing_args: string[];
  nodes: ImportNode[];
  blocked: ImportEntity[];
  skipped: ImportEntity[];
  warnings: ImportIssue[];
  whole: Record<string, unknown> | null;
  whole_reason: string | null;
}

export interface ImportCommitRequest {
  preview_id: string;
  mode: 'nodes' | 'whole';
  indices: number[];
  role: 'mine' | 'dependency';
  autostart: boolean;
}

export interface ImportCommitResult {
  created: { id: string }[];
  errors: { index?: number; code: string; message: string }[];
}
