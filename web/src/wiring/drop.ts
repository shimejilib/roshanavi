// What a wire being dragged would connect to, and what happens when it is let go (pure except
// for the cytoscape hit test; docs/design/wiring.md).

import type { Core, NodeSingular } from 'cytoscape';
import type { GraphTopic, Target } from '../api/types';
import { typeForKind, type KindCatalog } from '../datakind/kinds';
import { t } from '../i18n';
import { termPair } from '../i18n/glossary';
import { planConnect, type WirePlan } from './edit';
import { findPort, suggestTopic, type NodePorts, type Port } from './ports';

/** Where the drag started: a port, or the handle of a channel (topic). */
export type DragSource = { kind: 'port'; key: string } | { kind: 'topic'; topic: string };

/** What is under the pointer. */
export type DropHit =
  | { kind: 'port'; key: string }
  | { kind: 'topic'; topic: string }
  | { kind: 'node'; nodeId: string }
  | { kind: 'blank' };

const HIT_PAD = 6;

function contains(node: NodeSingular, x: number, y: number): boolean {
  const bb = node.renderedBoundingBox({ includeLabels: false, includeOverlays: false });
  return x >= bb.x1 - HIT_PAD && x <= bb.x2 + HIT_PAD && y >= bb.y1 - HIT_PAD && y <= bb.y2 + HIT_PAD;
}

/** Hit test at container coordinates `x, y` (`portKey`: a port element under the pointer). */
export function hitAt(cy: Core, x: number, y: number, portKey: string | null): DropHit {
  if (portKey) return { kind: 'port', key: portKey };
  const topic = cy.nodes('[kind = "topic"]').filter((n) => contains(n as NodeSingular, x, y)).first();
  if (topic.nonempty()) return { kind: 'topic', topic: String(topic.data('ref')) };
  const node = cy.nodes('[kind = "node"]').filter((n) => contains(n as NodeSingular, x, y)).first();
  if (node.nonempty()) return { kind: 'node', nodeId: String(node.data('ref')) };
  return { kind: 'blank' };
}

export interface DropContext {
  nodes: readonly NodePorts[];
  targets: readonly Target[];
  topics: readonly GraphTopic[];
  catalog: KindCatalog;
}

/** One save the drop leads to (two when an output port is dropped on an input port). */
export interface DropStep {
  node: NodePorts;
  port: Port;
  target: Target | undefined;
  plan: WirePlan;
  /** The channel the port ends up on. */
  topic: string;
}

/** The outcome of letting go: steps to save, a name to ask for (output -> blank), or a message. */
export type DropOutcome =
  | { kind: 'steps'; steps: DropStep[] }
  | { kind: 'ask'; port: string; suggestion: string }
  | { kind: 'refuse'; reason: string }
  | { kind: 'none' };

const typesOf = (ctx: DropContext, topic: string): string[] => ctx.topics.find((tp) => tp.name === topic)?.types ?? [];
const targetOf = (ctx: DropContext, id: string) => ctx.targets.find((tg) => tg.id === id);

export function connectStep(ctx: DropContext, node: NodePorts, port: Port, topic: string): DropStep {
  const target = targetOf(ctx, node.targetId);
  const plan: WirePlan = target ? planConnect(node, port, target, topic, typesOf(ctx, topic), ctx.catalog) : { ok: false, reason: t('wiring.refuse.gone') };
  return { node, port, target, plan, topic };
}

function externalReason(ctx: DropContext, nodeId: string): string {
  const owned = ctx.nodes.some((np) => np.nodeId === nodeId);
  return owned ? t('wiring.dropOnPort') : t('wiring.refuse.external', { node: nodeId, channel: termPair('topic') });
}

/** Output port `out` to input port `inp`: through `out`'s channel, or a new one named after it. */
function portToPort(ctx: DropContext, out: { node: NodePorts; port: Port }, inp: { node: NodePorts; port: Port }): DropOutcome {
  if (out.node.targetId === inp.node.targetId) return { kind: 'refuse', reason: t('wiring.refuse.loop') };
  const taken = new Set(ctx.topics.map((tp) => tp.name));
  const topic = out.port.topic || suggestTopic(out.node, out.port, taken);
  const steps = out.port.topic ? [] : [connectStep(ctx, out.node, out.port, topic)];
  // A new channel gets the output port's type: check the input port against that.
  const sent = out.port.type ?? (out.port.kind ? typeForKind(out.port.kind, ctx.catalog) : null);
  const inputStep = connectStep(ctx, inp.node, inp.port, topic);
  if (!out.port.topic && inputStep.target) {
    const plan = planConnect(inp.node, inp.port, inputStep.target, topic, sent ? [sent] : [], ctx.catalog);
    steps.push({ ...inputStep, plan });
  } else {
    steps.push(inputStep);
  }
  return { kind: 'steps', steps };
}

/** The outcome of dropping `source` on `hit` (also used while dragging, for the live hint). */
export function dropOutcome(ctx: DropContext, source: DragSource, hit: DropHit): DropOutcome {
  if (source.kind === 'topic') {
    if (hit.kind !== 'port') return { kind: 'none' };
    const found = findPort(ctx.nodes, hit.key);
    if (!found) return { kind: 'none' };
    return { kind: 'steps', steps: [connectStep(ctx, found.node, found.port, source.topic)] };
  }
  const from = findPort(ctx.nodes, source.key);
  if (!from) return { kind: 'none' };
  switch (hit.kind) {
    case 'topic':
      return { kind: 'steps', steps: [connectStep(ctx, from.node, from.port, hit.topic)] };
    case 'port': {
      if (hit.key === source.key) return { kind: 'none' };
      const other = findPort(ctx.nodes, hit.key);
      if (!other) return { kind: 'none' };
      if (other.port.ref.side === from.port.ref.side) return { kind: 'refuse', reason: t('wiring.refuse.sameSide') };
      return from.port.ref.side === 'out' ? portToPort(ctx, from, other) : portToPort(ctx, other, from);
    }
    case 'node':
      return { kind: 'refuse', reason: externalReason(ctx, hit.nodeId) };
    default:
      if (from.port.ref.side === 'in') return { kind: 'refuse', reason: t('wiring.dropInputBlank', { channel: termPair('topic') }) };
      return { kind: 'ask', port: source.key, suggestion: suggestTopic(from.node, from.port, new Set(ctx.topics.map((tp) => tp.name))) };
  }
}

/** The first refusal among the steps ('' when every step can be saved). */
export function refusalOf(outcome: DropOutcome): string {
  if (outcome.kind === 'refuse') return outcome.reason;
  if (outcome.kind !== 'steps') return '';
  const bad = outcome.steps.find((s) => !s.plan.ok);
  return bad && !bad.plan.ok ? bad.plan.reason : '';
}

/** Conversion notes of the steps (shown while dragging and after the wire is made). */
export function notesOf(outcome: DropOutcome): string {
  if (outcome.kind !== 'steps') return '';
  return outcome.steps.map((s) => (s.plan.ok ? s.plan.note : '')).filter(Boolean).join(' ');
}
