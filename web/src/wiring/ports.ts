// The つなぎ口 (ports) of the nodes roshanavi runs, from their specs (pure; docs/design/wiring.md).
// Only function / class / transform / input nodes have ports: their wiring is their own config.
// A node someone else wrote (run from the launcher, or started outside roshanavi) has none: its
// topics are decided in its code, so its channels can be wired to, but it cannot be rewired.

import type { ClassSpec } from '../api/classTypes';
import type { FunctionSpec } from '../api/functionTypes';
import type { TransformSpec } from '../api/transformTypes';
import type { DummySpec, GraphSnapshot, Target } from '../api/types';
import { kindLabel, type PortKind } from '../datakind/kinds';
import type { PortSlots } from '../graph/model';
import { t } from '../i18n';

export type WireOwner = 'function' | 'class' | 'transform' | 'dummy';
export type Side = 'in' | 'out';

export interface PortRef {
  targetId: string;
  side: Side;
  /** Bound method of a class node (index in `methods`); 0 otherwise. */
  group: number;
  index: number;
}

export interface Port {
  key: string;
  ref: PortRef;
  /** Argument name, `戻り値`, the dict key, the transform alias ... */
  label: string;
  /** Class nodes: the method the port belongs to. */
  method: string | null;
  /** データの種類 (null: described by `type`, e.g. a transform's ROS type). */
  kind: PortKind | null;
  /** The explicit ROS type of the port (null: the kind's type). */
  type: string | null;
  /** '' = not wired yet. */
  topic: string;
  /** Function / class ports can be left unwired; transform / input node ports always have one. */
  canUnwire: boolean;
}

export type TimingMode = 'on_message' | 'periodic' | 'multi_input' | 'relay' | 'map' | 'once' | 'stream' | 'media';

/** How the code behind a group of ports is called (call-timing display). */
export interface Timing {
  owner: WireOwner;
  mode: TimingMode;
  rateHz: number | null;
  /** multi_input: 'any' or the label of the triggering input. */
  trigger: string;
  inputs: string[];
}

export interface PortGroup {
  method: string | null;
  timing: Timing;
  inputs: Port[];
  outputs: Port[];
}

export interface NodePorts {
  targetId: string;
  owner: WireOwner;
  /** ROS node name (for suggested topic names). */
  name: string;
  /** ROS node id on the map (`/ns/name`). */
  nodeId: string;
  groups: PortGroup[];
  /** Class nodes: action methods (buttons). */
  actions: string[];
  running: boolean;
}

/** Argument names of a function (group 0) or of each bound method, from the static listing. */
export type ArgNames = (target: Target, group: number) => readonly string[] | undefined;

export const portKey = (ref: PortRef): string => `${ref.targetId}|${ref.side}|${ref.group}|${ref.index}`;

const WIREABLE: Readonly<Partial<Record<Target['kind'], WireOwner>>> = { function: 'function', class: 'class', transform: 'transform', dummy: 'dummy' };

export function ownerOf(target: Target): WireOwner | null {
  return WIREABLE[target.kind] ?? null;
}

function port(ref: Omit<PortRef, 'targetId'> & { targetId: string }, fields: Omit<Port, 'key' | 'ref'>): Port {
  return { key: portKey(ref), ref, ...fields };
}

function functionGroups(target: Target, spec: FunctionSpec, names: readonly string[] | undefined): PortGroup[] {
  const inputs = (spec.inputs ?? []).map((p, index) =>
    port({ targetId: target.id, side: 'in', group: 0, index }, {
      label: names?.[index] ?? t('wiring.port.arg', { n: index + 1 }), method: null, kind: p.kind, type: p.type ?? null, topic: p.topic, canUnwire: true,
    }));
  const output = port({ targetId: target.id, side: 'out', group: 0, index: 0 }, {
    label: t('wiring.port.return'), method: null, kind: spec.output.kind, type: spec.output.type ?? null, topic: spec.output.topic, canUnwire: true,
  });
  const trigger = spec.trigger && spec.trigger !== 'any' ? inputs.find((p) => p.topic === spec.trigger)?.label ?? 'any' : 'any';
  return [{
    method: null,
    timing: { owner: 'function', mode: spec.call, rateHz: spec.rate_hz ?? null, trigger, inputs: inputs.map((p) => p.label) },
    inputs,
    outputs: [output],
  }];
}

function classGroups(target: Target, spec: ClassSpec, argNames: (group: number) => readonly string[] | undefined): PortGroup[] {
  return (spec.methods ?? []).map((m, group) => {
    const names = argNames(group);
    const inputs = (m.inputs ?? []).map((p, index) =>
      port({ targetId: target.id, side: 'in', group, index }, {
        label: names?.[index] ?? t('wiring.port.arg', { n: index + 1 }), method: m.method, kind: p.kind, type: p.type ?? null, topic: p.topic, canUnwire: true,
      }));
    const outputs = (m.outputs ?? []).map((p, index) =>
      port({ targetId: target.id, side: 'out', group, index }, {
        label: p.key ?? t('wiring.port.return'), method: m.method, kind: p.kind, type: p.type ?? null, topic: p.topic, canUnwire: true,
      }));
    const trigger = m.trigger && m.trigger !== 'any' ? inputs.find((p) => p.topic === m.trigger)?.label ?? 'any' : 'any';
    return {
      method: m.method,
      timing: { owner: 'class', mode: m.call, rateHz: m.rate_hz ?? null, trigger, inputs: inputs.map((p) => p.label) },
      inputs,
      outputs,
    };
  });
}

function transformGroups(target: Target, spec: TransformSpec): PortGroup[] {
  const specInputs = spec.inputs ?? [];
  const single = specInputs.length === 1;
  const inputs = specInputs.map((p, index) =>
    port({ targetId: target.id, side: 'in', group: 0, index }, {
      label: p.alias ?? (single ? 'msg' : `msg${index + 1}`), method: null, kind: null, type: p.type, topic: p.topic, canUnwire: false,
    }));
  const output = port({ targetId: target.id, side: 'out', group: 0, index: 0 }, {
    label: t('wiring.port.output'), method: null, kind: null, type: spec.output.type ?? (spec.mode === 'relay' ? specInputs[0]?.type ?? null : null), topic: spec.output.topic, canUnwire: false,
  });
  const trigger = spec.trigger && spec.trigger !== 'any' ? spec.trigger : 'any';
  const mode: TimingMode = spec.mode === 'relay' ? 'relay' : single ? 'map' : 'multi_input';
  return [{ method: null, timing: { owner: 'transform', mode, rateHz: spec.throttle_hz ?? null, trigger, inputs: inputs.map((p) => p.label) }, inputs, outputs: [output] }];
}

function dummyGroups(target: Target, spec: DummySpec): PortGroup[] {
  const output = port({ targetId: target.id, side: 'out', group: 0, index: 0 }, {
    label: t('wiring.port.sent'), method: null, kind: spec.kind ?? null, type: spec.type, topic: spec.topic, canUnwire: false,
  });
  const mode: TimingMode = spec.mode;
  return [{ method: null, timing: { owner: 'dummy', mode, rateHz: spec.rate_hz ?? null, trigger: 'any', inputs: [] }, inputs: [], outputs: [output] }];
}

/** Ports of one roshanavi-run node (null: not a node whose wiring roshanavi owns). */
export function portsOfTarget(target: Target, nodeId: string, argNames: ArgNames = () => undefined): NodePorts | null {
  const owner = ownerOf(target);
  if (!owner) return null;
  const spec = target.spec;
  const groups =
    owner === 'function' ? functionGroups(target, spec as FunctionSpec, argNames(target, 0))
      : owner === 'class' ? classGroups(target, spec as ClassSpec, (g) => argNames(target, g))
        : owner === 'transform' ? transformGroups(target, spec as TransformSpec)
          : dummyGroups(target, spec as DummySpec);
  return {
    targetId: target.id,
    owner,
    name: (spec as { name: string }).name,
    nodeId,
    groups,
    actions: owner === 'class' ? [...((spec as ClassSpec).actions ?? [])] : [],
    running: target.status === 'running' || target.status === 'starting',
  };
}

/** Ports of every roshanavi-run node that is on the map (mapped by the graph's `target_id`). */
export function buildNodePorts(targets: readonly Target[], graph: GraphSnapshot | null, argNames?: ArgNames): NodePorts[] {
  if (!graph) return [];
  const byTarget = new Map<string, string>();
  for (const n of graph.nodes) if (n.target_id && !byTarget.has(n.target_id)) byTarget.set(n.target_id, n.id);
  const out: NodePorts[] = [];
  for (const target of targets) {
    const nodeId = byTarget.get(target.id);
    if (!nodeId) continue;
    const ports = portsOfTarget(target, nodeId, argNames);
    if (ports) out.push(ports);
  }
  return out;
}

export function allInputs(np: NodePorts): Port[] {
  return np.groups.flatMap((g) => g.inputs);
}

export function allOutputs(np: NodePorts): Port[] {
  return np.groups.flatMap((g) => g.outputs);
}

export function findPort(nodes: readonly NodePorts[], key: string): { node: NodePorts; port: Port } | null {
  for (const node of nodes) {
    for (const p of [...allInputs(node), ...allOutputs(node)]) if (p.key === key) return { node, port: p };
  }
  return null;
}

/** The label drawn inside the node box next to the port: `text · 文字列`. */
export function portLabel(p: Port): string {
  return p.kind ? `${p.label} · ${kindLabel(p.kind)}` : p.label;
}

/** Where ports sit on each node box (for the map model): topics, keys and labels in order. */
export function portLayouts(nodes: readonly NodePorts[]): Map<string, PortSlots> {
  return new Map(nodes.map((np) => {
    const ins = allInputs(np);
    const outs = allOutputs(np);
    return [np.nodeId, {
      inputs: ins.map((p) => p.topic),
      outputs: outs.map((p) => p.topic),
      inputKeys: ins.map((p) => p.key),
      outputKeys: outs.map((p) => p.key),
      inputLabels: ins.map(portLabel),
      outputLabels: outs.map(portLabel),
    }];
  }));
}

/** `/<node>/<output>` (or `/<node>/<output>_2` ... when taken): the suggested new channel name. */
export function suggestTopic(np: NodePorts, p: Port, taken: ReadonlySet<string>): string {
  const clean = (s: string) => s.replace(/[^A-Za-z0-9_]/g, '_').replace(/^(?=\d)/, '_') || 'out';
  const leaf = np.owner === 'class' ? clean(p.label === t('wiring.port.return') ? p.method ?? 'out' : p.label) : 'out';
  const base = `/${clean(np.name)}/${leaf}`;
  if (!taken.has(base)) return base;
  for (let n = 2; ; n += 1) if (!taken.has(`${base}_${n}`)) return `${base}_${n}`;
}
