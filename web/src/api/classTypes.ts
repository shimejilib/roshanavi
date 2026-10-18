// Class nodes (クラスノード, docs/design/nodes.md): a plain Python class run as a ROS node.

import type { CodeNotice, NodeEnvironment } from './codeTypes';
import type { PortKind } from '../datakind/kinds';
import type { CallMode, FunctionPortSpec, FunctionProblem } from './functionTypes';
import type { Qos } from './types';

/** A value of an `__init__` argument in the project file (JSON arguments are written as text). */
export type InitValue = boolean | number | string | number[];

export interface ClassOutputSpec extends FunctionPortSpec {
  /** Set when the method returns a dict: this key goes to this topic. */
  key?: string;
  qos?: Pick<Qos, 'reliability' | 'durability'> & { depth: number };
}

export interface ClassMethodSpec {
  method: string;
  call: CallMode;
  inputs: FunctionPortSpec[];
  outputs: ClassOutputSpec[];
  rate_hz?: number | null;
  trigger?: string;
}

export interface ClassSpec {
  id: string;
  name: string;
  namespace?: string;
  module: string;
  class_name: string;
  params: Record<string, InitValue>;
  methods: ClassMethodSpec[];
  /** Methods without arguments that can be called by hand (button, topic, scenario step). */
  actions: string[];
  autostart?: boolean;
  auto_restart?: boolean;
}

// ---- static listing (GET /api/functions/module -> classes) -------------------------------------
export type ParamKind = 'string' | 'float' | 'int' | 'bool' | 'numbers' | 'json';

export interface ClassInitParam {
  name: string;
  annotation: string | null;
  has_default: boolean;
  default: unknown;
  default_text: string | null;
  /** The data kind a ROS parameter can carry; null = cannot be a parameter. */
  kind: ParamKind | null;
}

export interface ClassMethodInfo {
  name: string;
  line: number;
  signature: string;
  params: { name: string; annotation: string | null; kind: PortKind | null; optional: boolean }[];
  required: number;
  varargs: boolean;
  returns: string | null;
  returns_kind: PortKind | null;
  /** No required argument: it can be an action method. */
  action_candidate: boolean;
  doc: string;
}

export interface ClassInfo {
  name: string;
  line: number;
  signature: string;
  init_params: ClassInitParam[];
  methods: ClassMethodInfo[];
  hooks: Record<'close' | 'shutdown' | 'get_state' | 'set_state' | 'on_param_change', boolean>;
  doc: string;
}

// ---- live status (GET /api/targets/{id} -> function_status of a class node) ---------------------
export interface ActionRecord {
  count: number;
  last_at: number | null;
  ok: boolean | null;
  result: string | null;
  error: (FunctionProblem & { at?: number }) | null;
  topic: string;
}

export interface ClassStatus {
  kind: 'class';
  state: 'starting' | 'running' | 'import_error' | 'init_error' | 'reload_error' | 'stopped';
  class: string;
  signature: string | null;
  location: string | null;
  loads: number;
  problem: FunctionProblem | null;
  last_error: FunctionProblem | null;
  stats: { received: number; calls: number; published: number; skipped: number; waiting: number; errors: number; reloads: number; dropped: number; resets: number };
  params: { name: string; kind: ParamKind | null; annotation: string | null; required: boolean; value: unknown }[];
  warnings: string[];
  methods: { method: string; call: CallMode; calls: number; ignored_keys: string[] }[];
  actions: Record<string, ActionRecord>;
  /** The last time the instance was created again (`reset`) or its state carried over (`kept`). */
  notice: { kind: 'reset' | 'kept'; reason: 'reload' | 'param'; at: number } | null;
  hooks: Record<string, boolean>;
  environment?: NodeEnvironment;
  notices?: CodeNotice[];
  import_seconds?: number | null;
}
