// Transform nodes (変換ノード) and project switching (docs/design/nodes.md, docs/design/launcher.md).

import type { Qos } from './types';

export interface TransformInput {
  topic: string;
  type: string;
  /** Name in expressions: msg (one input) or msg1, msg2 ... by default. */
  alias?: string;
}

export interface TransformSpec {
  id: string;
  name: string;
  namespace?: string;
  inputs: TransformInput[];
  output: { topic: string; type?: string; qos?: Pick<Qos, 'reliability' | 'durability'> & { depth: number } };
  mode: 'map' | 'relay';
  /** Output message template; strings with ${...} are expressions. Absent: forward the input. */
  mapping?: Record<string, unknown> | null;
  condition?: string | null;
  trigger?: string;
  delay?: { min_ms: number; max_ms?: number | null } | null;
  throttle_hz?: number | null;
  drop_ratio?: number;
  autostart?: boolean;
  auto_restart?: boolean;
}

export interface PreviewError {
  path: string;
  code: string;
  message: string;
  params: Record<string, string | number>;
}

export interface PreviewResult {
  ok: boolean;
  passed: boolean;
  output: Record<string, unknown> | null;
  errors: PreviewError[];
  /** Inputs without a received message: their type's default values were used. */
  templated?: string[];
  relay?: boolean;
}

export interface ProjectEntry {
  id: string;
  kind: 'example' | 'data';
  name: string;
  path: string;
  title: string;
  current: boolean;
  copy_path?: string;
}

export interface ProjectList {
  current: string;
  projects: ProjectEntry[];
}
