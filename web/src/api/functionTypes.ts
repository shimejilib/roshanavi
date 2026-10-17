// Function nodes (関数ノード, docs/design/nodes.md): a plain Python function run as a ROS node.

import type { PortKind } from '../datakind/kinds';
import type { Qos } from './types';

export type CallMode = 'on_message' | 'periodic' | 'multi_input';

export interface FunctionPortSpec {
  topic: string;
  kind: PortKind;
  /** A compatible type of an existing topic, or the ROS type of kind `message`. */
  type?: string | null;
}

export interface FunctionSpec {
  id: string;
  name: string;
  namespace?: string;
  module: string;
  function: string;
  call: CallMode;
  inputs: FunctionPortSpec[];
  output: FunctionPortSpec & { qos?: Pick<Qos, 'reliability' | 'durability'> & { depth: number } };
  rate_hz?: number | null;
  trigger?: string;
  autostart?: boolean;
  auto_restart?: boolean;
}

export interface FunctionProblem {
  kind: 'import' | 'call' | 'convert' | 'publish';
  message: string;
  location: string | null;
  at?: number;
}

/** What the running node reports (GET /api/targets/{id} -> function_status). */
export interface FunctionStatus {
  state: 'running' | 'import_error' | 'reload_error' | 'stopped';
  function: string;
  signature: string | null;
  location: string | null;
  loads: number;
  problem: FunctionProblem | null;
  last_error: FunctionProblem | null;
  stats: { received: number; calls: number; published: number; skipped: number; waiting: number; errors: number; reloads: number };
}

export interface ModuleEntry {
  module: string;
  ros_package: string;
  file: string;
}

export interface FunctionParam {
  name: string;
  annotation: string | null;
  kind: PortKind | null;
  optional: boolean;
}

export interface FunctionInfo {
  name: string;
  line: number;
  signature: string;
  params: FunctionParam[];
  required: number;
  returns: string | null;
  returns_kind: PortKind | null;
  doc: string;
  varargs: boolean;
}

export interface ModuleInfo {
  module: string;
  ros_package: string;
  file: string;
  functions: FunctionInfo[];
}
