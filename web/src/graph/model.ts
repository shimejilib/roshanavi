// Graph snapshot + traffic -> renderer-agnostic element list (pure, unit-tested).

import type { Diagnostic, GraphEdge, GraphSnapshot, RateBasis, Role, TrafficEntry } from '../api/types';
import { t } from '../i18n';
import { ageSec, edgeLabel, formatHz, formatRate } from '../lib/format';
import { isHiddenNode, isHiddenTopic } from '../lib/topics';
import type { NodeBadge } from '../api/resourceTypes';
import { badgeLabel, loadLevel, type LoadLevel } from '../resources/model';
import { quietTopicNotes, qosReasonText, warningDiagnostics } from './diagnosticsText';

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
  /** CPU load of the node's process (resource monitoring); 'none' when unknown / topics. */
  load: LoadLevel;
  /** The node's memory keeps growing (leak suspicion). */
  leak: boolean;
  /** Nodes with つなぎ口 (map wiring): box size that fits the ports. */
  pw?: number;
  ph?: number;
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
  /** How `hz`/`bw` were obtained: per publisher (rates.py) or the topic total. */
  rateBasis: RateBasis | 'total';
  rateNote: string;
  /** Map wiring: the edge ends at its port (cytoscape `source-endpoint` / `target-endpoint`). */
  sep?: string;
  tep?: string;
  /** Map wiring: the key of the port this edge is the wire of. */
  port?: string;
}

interface EdgeRate {
  hz: number;
  bw: number;
  label: string;
  basis: RateBasis | 'total';
  note: string;
}

const RATE_NOTES: Partial<Record<RateBasis, () => string>> = {
  exact: () => t('graph.rate.exactHelp'),
  configured: () => t('graph.rate.configuredHelp'),
  estimated: () => t('graph.rate.estimatedHelp'),
  unknown: () => t('graph.rate.unknownHelp'),
};

function rateLabel(hz: number, bps: number | null, basis: RateBasis): string {
  if (!(hz > 0)) return '';
  const base = bps == null ? formatHz(hz) : `${formatHz(hz)} · ${formatRate(bps)}`;
  if (basis === 'estimated') return `${base} (${t('graph.rate.estimated')})`;
  if (basis === 'configured') return `${base} (${t('graph.rate.configured')})`;
  return base;
}

/** Theoretical rate of a subscriber (QoS-compatible publishers only), like the traffic table. */
function subscriberRate(node: string, entry: TrafficEntry | undefined, total: EdgeRate): EdgeRate {
  const sub = entry?.subscribers?.find((s) => s.node === node);
  if (!sub || sub.hz == null || (sub.hz === total.hz && sub.delivered)) return total;
  const bw = sub.bps ?? 0;
  return { hz: sub.hz, bw, label: edgeLabel(sub.hz, bw), basis: 'total', note: '' };
}

/** Subscribers receive what the compatible publishers send; publishers get their own share when known. */
export function edgeRate(e: Pick<GraphEdge, 'node' | 'dir'>, entry: TrafficEntry | undefined): EdgeRate {
  const totalHz = entry?.hz ?? 0;
  const totalBw = entry?.bytes_per_sec ?? 0;
  const total: EdgeRate = { hz: totalHz, bw: totalBw, label: edgeLabel(totalHz, totalBw), basis: 'total', note: '' };
  if (e.dir === 'sub') return subscriberRate(e.node, entry, total);
  const pub = entry?.publishers?.find((p) => p.node === e.node);
  if (!pub) return total;
  const note = RATE_NOTES[pub.basis]?.() ?? '';
  const share = Math.max(1, entry?.source_count ?? 1);
  if (pub.hz == null) {
    // Unknown split: no number on the edge; animate/size with an even share.
    return { hz: totalHz / share, bw: totalBw / share, label: '', basis: pub.basis, note };
  }
  const bw = pub.bps ?? totalBw / share;
  return { hz: pub.hz, bw, label: rateLabel(pub.hz, pub.bps, pub.basis), basis: pub.basis, note };
}

/** Topic label; with several publishers it carries the total and the source count. */
export function topicLabel(name: string, entry: TrafficEntry | undefined): string {
  const sources = entry?.source_count ?? 0;
  if (sources < 2 || !entry || !(entry.hz > 0)) return name;
  return `${name}\n${t('graph.rate.total', { hz: formatHz(entry.hz), n: sources })}`;
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
  if (entry.stale || age == null || age > STALE_AFTER_SEC) return 'stale';
  if ((entry.drop_ratio ?? 0) > 0) return 'drops';
  return 'active';
}

/** Keep hidden topics and infrastructure nodes (ros2 CLI daemon, `_ros2cli_*`) out and apply the
 *  name filter (matches pull in neighbours). */
export function filterSnapshot(snap: GraphSnapshot, opts: FilterOptions): GraphSnapshot {
  const topics = opts.hideHidden ? snap.topics.filter((tp) => !isHiddenTopic(tp.name)) : snap.topics;
  const topicNames = new Set(topics.map((tp) => tp.name));
  let nodes = opts.hideHidden ? snap.nodes.filter((n) => !isHiddenNode(n.id)) : snap.nodes;
  const nodeIds = new Set(nodes.map((n) => n.id));
  let edges = snap.edges.filter((e) => topicNames.has(e.topic) && nodeIds.has(e.node));
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

/** Ports of a wireable node, in order (topic per port, '' = not wired), and their keys. */
export interface PortSlots {
  inputs: readonly string[];
  outputs: readonly string[];
  inputKeys?: readonly string[];
  outputKeys?: readonly string[];
  /** Port labels drawn inside the box (its width follows them). */
  inputLabels?: readonly string[];
  outputLabels?: readonly string[];
}

export const PORT_PITCH = 14;
export const PORT_BOX_WIDTH = 46;
const PORT_PAD = 8;
const PORT_BOX_MIN_HEIGHT = 26;

const LABEL_FONT_ASCII = 5.4; // px per character at the 9 px port label font
const LABEL_FONT_WIDE = 9.2;
const LABEL_GAP = 14;
const BOX_MAX_WIDTH = 180;

/** Rough width of a port label (no DOM: the model is pure). */
export function labelWidth(text: string): number {
  let w = 0;
  for (const ch of text) w += ch.charCodeAt(0) < 0x2e80 ? LABEL_FONT_ASCII : LABEL_FONT_WIDE;
  return w;
}

/** Box width that fits the labels of both sides. */
export function portBoxWidth(slots: PortSlots): number {
  const widest = (labels: readonly string[] | undefined) => Math.max(0, ...(labels ?? []).map(labelWidth));
  const w = widest(slots.inputLabels) + widest(slots.outputLabels) + LABEL_GAP + 2 * PORT_PAD;
  return Math.round(Math.min(BOX_MAX_WIDTH, Math.max(PORT_BOX_WIDTH, w)));
}

/** Box height that fits `n` ports on a side (at least the plain node height). */
export function portBoxHeight(slots: PortSlots): number {
  const n = Math.max(slots.inputs.length, slots.outputs.length, 1);
  return Math.max(PORT_BOX_MIN_HEIGHT, n * PORT_PITCH + PORT_PAD);
}

/** Vertical position of port `index` of `count`, as a fraction of the box height (-0.5 .. 0.5). */
export function portFraction(index: number, count: number): number {
  return (index + 0.5) / Math.max(1, count) - 0.5;
}

function endpointOf(slots: PortSlots | undefined, dir: 'pub' | 'sub', topic: string): { at: string; key: string } | null {
  if (!slots) return null;
  const list = dir === 'pub' ? slots.outputs : slots.inputs;
  const index = list.indexOf(topic);
  if (index < 0) return null;
  const x = dir === 'pub' ? '50%' : '-50%';
  const y = `${(portFraction(index, list.length) * 100).toFixed(2)}%`;
  const key = (dir === 'pub' ? slots.outputKeys : slots.inputKeys)?.[index] ?? '';
  return { at: `${x} ${y}`, key };
}

function buildEdges(snap: GraphSnapshot, traffic: Map<string, TrafficEntry>, nowMs: number, ports: ReadonlyMap<string, PortSlots>): EdgeData[] {
  const bad = qosBadEdges(snap.diagnostics);
  const seen = new Set<string>();
  const edges: EdgeData[] = [];
  for (const e of snap.edges) {
    const id = `e:${e.dir}:${e.node}:${e.topic}`;
    if (seen.has(id)) continue;
    seen.add(id);
    const entry = traffic.get(e.topic);
    const rate = edgeRate(e, entry);
    const reasons = e.dir === 'sub' ? (bad.get(`${e.node}\u0000${e.topic}`) ?? []) : [];
    const nodeEl = nodeElementId(e.node);
    const topicEl = topicElementId(e.topic);
    const end = endpointOf(ports.get(e.node), e.dir, e.topic);
    edges.push({
      id,
      source: e.dir === 'pub' ? nodeEl : topicEl,
      target: e.dir === 'pub' ? topicEl : nodeEl,
      topic: e.topic,
      node: e.node,
      dir: e.dir,
      hz: rate.hz,
      bw: rate.bw,
      width: edgeWidth(rate.bw),
      label: rate.label,
      state: edgeState(entry, nowMs),
      qosBad: reasons.length > 0,
      qosReason: reasons.map((d) => qosReasonText(d)).join('\n'),
      rateBasis: rate.basis,
      rateNote: rate.note,
      ...(end ? { [e.dir === 'pub' ? 'sep' : 'tep']: end.at, port: end.key } : {}),
    });
  }
  return edges;
}

function nodeLabel(n: GraphSnapshot['nodes'][number], badge: NodeBadge | undefined): string {
  // Virtual inject-job sources show the job id; real (persistent) dummies their name.
  const base = n.job_id ? `${n.name}\n${n.job_id}` : n.id;
  const extra = badgeLabel(badge);
  return extra ? `${base}\n${extra}` : base;
}

/** `受信なし` / `送信なし` as a last, small line under the topic name (info, not a warning). */
function withQuietNote(label: string, note: string | undefined): string {
  return note ? `${label}\n${note}` : label;
}

/** Full element list for the current (already filtered) snapshot. ``resources``: per-node
 *  CPU / memory badges (resource monitoring), keyed by node id. */
export function buildElements(
  snap: GraphSnapshot,
  traffic: Map<string, TrafficEntry>,
  nowMs: number,
  resources: Readonly<Record<string, NodeBadge>> = {},
  ports: ReadonlyMap<string, PortSlots> = new Map(),
): Element[] {
  // Endpoints can briefly reference nodes the node list does not have yet (graph race).
  const known = new Set(snap.nodes.map((n) => n.id));
  const edges = buildEdges(snap, traffic, nowMs, ports).filter((e) => known.has(e.node));
  const nodeBw = new Map<string, number>();
  for (const e of edges) nodeBw.set(e.node, (nodeBw.get(e.node) ?? 0) + e.bw);
  const warnTopics = new Set(warningDiagnostics(snap.diagnostics).map((d) => d.topic));
  const quietNotes = quietTopicNotes(snap.diagnostics);
  const warnNodes = new Set(warningDiagnostics(snap.diagnostics).filter((d) => d.code === 'mine_no_input').flatMap((d) => d.nodes));
  const elements: Element[] = snap.nodes.map((n) => {
    const badge = n.job_id ? undefined : resources[n.id];
    const slots = ports.get(n.id);
    return {
      group: 'nodes',
      data: {
        id: nodeElementId(n.id),
        label: nodeLabel(n, badge),
        kind: 'node',
        role: n.role,
        ref: n.id,
        border: borderWidth(nodeBw.get(n.id) ?? 0),
        state: 'none',
        warn: warnNodes.has(n.id),
        load: loadLevel(badge?.cpu_pct),
        leak: badge?.leak?.suspect === true,
        ...(slots ? { pw: portBoxWidth(slots), ph: portBoxHeight(slots) } : {}),
      },
    };
  });
  for (const tp of snap.topics) {
    const entry = traffic.get(tp.name);
    elements.push({
      group: 'nodes',
      data: {
        id: topicElementId(tp.name),
        label: withQuietNote(topicLabel(tp.name, entry), quietNotes.get(tp.name)),
        kind: 'topic',
        role: 'topic',
        ref: tp.name,
        border: borderWidth(entry?.bytes_per_sec ?? 0),
        state: edgeState(entry, nowMs),
        warn: warnTopics.has(tp.name),
        load: 'none',
        leak: false,
      },
    });
  }
  return [...elements, ...edges.map((data): Element => ({ group: 'edges', data }))];
}
