// Graph snapshot + traffic -> renderer-agnostic element list (pure, unit-tested).

import type { Diagnostic, GraphSnapshot, Role, TrafficEntry } from '../api/types';
import { ageSec, edgeLabel } from '../lib/format';
import { isHiddenTopic } from '../lib/topics';
import { qosReasonText } from './diagnosticsText';

export const STALE_AFTER_SEC = 3;
const WIDTH_MIN = 1.5;
const WIDTH_MAX = 10;
const BORDER_MIN = 1;
const BORDER_MAX = 8;

export type EdgeState = 'active' | 'stale' | 'drops' | 'not_monitored' | 'idle';

export interface NodeData {
  id: string;
  label: string;
  kind: 'node' | 'topic';
  role: Role | 'topic';
  ref: string; // ROS node id or topic name
  border: number;
  state: EdgeState | 'none';
  warn: boolean;
}

export interface EdgeData {
  id: string;
  source: string;
  target: string;
  topic: string;
  node: string;
  dir: 'pub' | 'sub';
  hz: number;
  bw: number;
  width: number;
  label: string;
  state: EdgeState;
  qosBad: boolean;
  qosReason: string;
}

export type Element = { group: 'nodes'; data: NodeData } | { group: 'edges'; data: EdgeData };

export interface FilterOptions {
  query: string;
  hideHidden: boolean;
}

export const nodeElementId = (nodeId: string): string => `n:${nodeId}`;
export const topicElementId = (topic: string): string => `t:${topic}`;

/** Edge width grows with log(bandwidth): 1 KB/s ≈ 1.9 px, 1 MB/s ≈ 5 px. */
export function edgeWidth(bytesPerSec: number): number {
  const w = WIDTH_MIN + 1.2 * Math.log10(1 + Math.max(0, bytesPerSec) / 1000);
  return Math.min(WIDTH_MAX, Number(w.toFixed(2)));
}

export function borderWidth(bytesPerSec: number): number {
  const w = BORDER_MIN + Math.log10(1 + Math.max(0, bytesPerSec) / 1000);
  return Math.min(BORDER_MAX, Number(w.toFixed(2)));
}

export function edgeState(entry: TrafficEntry | undefined, nowMs: number): EdgeState {
  if (!entry) return 'idle';
  if (!entry.monitored || entry.status === 'not_monitored') return 'not_monitored';
  if (entry.status !== 'ok') return 'idle';
  const age = ageSec(entry.last_seen, nowMs);
  if (age == null || age > STALE_AFTER_SEC) return 'stale';
  if ((entry.drop_ratio ?? 0) > 0) return 'drops';
  return 'active';
}

/** Keep hidden topics out and apply the name filter (matches pull in neighbours). */
export function filterSnapshot(snap: GraphSnapshot, opts: FilterOptions): GraphSnapshot {
  const topics = opts.hideHidden ? snap.topics.filter((tp) => !isHiddenTopic(tp.name)) : snap.topics;
  const topicNames = new Set(topics.map((tp) => tp.name));
  let edges = snap.edges.filter((e) => topicNames.has(e.topic));
  let nodes = snap.nodes;
  const query = opts.query.trim().toLowerCase();
  if (query) {
    const matchT = new Set(topics.filter((tp) => tp.name.toLowerCase().includes(query)).map((tp) => tp.name));
    const matchN = new Set(nodes.filter((n) => n.id.toLowerCase().includes(query)).map((n) => n.id));
    const keepT = new Set(matchT);
    const keepN = new Set(matchN);
    for (const e of edges) {
      if (matchN.has(e.node)) keepT.add(e.topic);
      if (matchT.has(e.topic)) keepN.add(e.node);
    }
    edges = edges.filter((e) => keepT.has(e.topic) && keepN.has(e.node));
    nodes = nodes.filter((n) => keepN.has(n.id));
    return { ...snap, nodes, topics: topics.filter((tp) => keepT.has(tp.name)), edges };
  }
  return { ...snap, nodes, topics, edges };
}

function qosBadEdges(diags: Diagnostic[]): Map<string, Diagnostic[]> {
  const bad = new Map<string, Diagnostic[]>();
  for (const d of diags) {
    if (d.code !== 'qos_incompatible' || !d.detail.subscriber) continue;
    const key = `${d.detail.subscriber}\u0000${d.topic}`;
    bad.set(key, [...(bad.get(key) ?? []), d]);
  }
  return bad;
}

function buildEdges(snap: GraphSnapshot, traffic: Map<string, TrafficEntry>, nowMs: number): EdgeData[] {
  const bad = qosBadEdges(snap.diagnostics);
  const seen = new Set<string>();
  const edges: EdgeData[] = [];
  for (const e of snap.edges) {
    const id = `e:${e.dir}:${e.node}:${e.topic}`;
    if (seen.has(id)) continue;
    seen.add(id);
    const entry = traffic.get(e.topic);
    const hz = entry?.hz ?? 0;
    const bw = entry?.bytes_per_sec ?? 0;
    const reasons = e.dir === 'sub' ? (bad.get(`${e.node}\u0000${e.topic}`) ?? []) : [];
    const nodeEl = nodeElementId(e.node);
    const topicEl = topicElementId(e.topic);
    edges.push({
      id,
      source: e.dir === 'pub' ? nodeEl : topicEl,
      target: e.dir === 'pub' ? topicEl : nodeEl,
      topic: e.topic,
      node: e.node,
      dir: e.dir,
      hz,
      bw,
      width: edgeWidth(bw),
      label: edgeLabel(hz, bw),
      state: edgeState(entry, nowMs),
      qosBad: reasons.length > 0,
      qosReason: reasons.map((d) => qosReasonText(d)).join('\n'),
    });
  }
  return edges;
}

/** Full element list for the current (already filtered) snapshot. */
export function buildElements(snap: GraphSnapshot, traffic: Map<string, TrafficEntry>, nowMs: number): Element[] {
  // Endpoints can briefly reference nodes the node list does not have yet (graph race).
  const known = new Set(snap.nodes.map((n) => n.id));
  const edges = buildEdges(snap, traffic, nowMs).filter((e) => known.has(e.node));
  const nodeBw = new Map<string, number>();
  for (const e of edges) nodeBw.set(e.node, (nodeBw.get(e.node) ?? 0) + e.bw);
  const warnTopics = new Set(snap.diagnostics.map((d) => d.topic));
  const elements: Element[] = snap.nodes.map((n) => ({
    group: 'nodes',
    data: {
      id: nodeElementId(n.id),
      // Virtual inject-job sources show the job id; real (persistent) dummies their name.
      label: n.job_id ? `${n.name}\n${n.job_id}` : n.id,
      kind: 'node',
      role: n.role,
      ref: n.id,
      border: borderWidth(nodeBw.get(n.id) ?? 0),
      state: 'none',
      warn: false,
    },
  }));
  for (const tp of snap.topics) {
    const entry = traffic.get(tp.name);
    elements.push({
      group: 'nodes',
      data: {
        id: topicElementId(tp.name),
        label: tp.name,
        kind: 'topic',
        role: 'topic',
        ref: tp.name,
        border: borderWidth(entry?.bytes_per_sec ?? 0),
        state: edgeState(entry, nowMs),
        warn: warnTopics.has(tp.name),
      },
    });
  }
  return [...elements, ...edges.map((data): Element => ({ group: 'edges', data }))];
}
