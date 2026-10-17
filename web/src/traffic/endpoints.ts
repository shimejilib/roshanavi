// Traffic per (node × topic × direction): rows under a topic, or grouped by node (pure, DESIGN §6.7).
//
// Publisher values come from the backend split (rates.py: exact / measured /
// estimated / configured / unknown); subscriber values are theoretical (what the
// QoS-compatible publishers send) or 0 when nothing can be delivered. `basis`
// stays a free string so a future tracing probe can report `measured`.

import type { TrafficEntry } from '../api/types';
import { t, tDynamic } from '../i18n';
import { formatHz, formatRate } from '../lib/format';

export type Direction = 'pub' | 'sub';

export interface EndpointRow {
  node: string;
  topic: string;
  type: string;
  dir: Direction;
  hz: number | null;
  bps: number | null;
  basis: string;
  delivered: boolean;
}

export interface NodeTraffic {
  node: string;
  rows: EndpointRow[];
}

const byNode = (a: EndpointRow, b: EndpointRow) => a.node.localeCompare(b.node);

/** Publisher rows (by node) then subscriber rows (by node) of one topic. */
export function topicEndpoints(entry: TrafficEntry): EndpointRow[] {
  const base = { topic: entry.topic, type: entry.type };
  const pubs: EndpointRow[] = (entry.publishers ?? []).map((p) => ({
    ...base, node: p.node, dir: 'pub', hz: p.hz, bps: p.bps, basis: p.basis, delivered: true,
  }));
  const subs: EndpointRow[] = (entry.subscribers ?? []).map((s) => ({
    ...base, node: s.node, dir: 'sub', hz: s.hz, bps: s.bps, basis: s.basis, delivered: s.delivered,
  }));
  return [...pubs.sort(byNode), ...subs.sort(byNode)];
}

/** Every endpoint grouped by node; within a node: sends first, then receives, by topic. */
export function groupByNode(entries: Iterable<TrafficEntry>): NodeTraffic[] {
  const groups = new Map<string, EndpointRow[]>();
  for (const entry of entries) {
    for (const row of topicEndpoints(entry)) {
      groups.set(row.node, [...(groups.get(row.node) ?? []), row]);
    }
  }
  const order = (a: EndpointRow, b: EndpointRow) =>
    a.dir === b.dir ? a.topic.localeCompare(b.topic) : a.dir === 'pub' ? -1 : 1;
  return [...groups.entries()]
    .map(([node, rows]) => ({ node, rows: [...rows].sort(order) }))
    .sort((a, b) => a.node.localeCompare(b.node));
}

export function basisLabel(basis: string): string {
  return tDynamic(`traffic.basis.${basis}`, 'traffic.basis.other', { basis });
}

export function basisHelp(basis: string): string {
  return tDynamic(`traffic.basisHelp.${basis}`, 'traffic.basisHelp.other', { basis });
}

export function endpointHz(row: Pick<EndpointRow, 'hz' | 'delivered'>): string {
  if (!row.delivered) return t('traffic.notDelivered');
  return row.hz == null ? '—' : formatHz(row.hz);
}

export function endpointBandwidth(row: Pick<EndpointRow, 'bps' | 'delivered'>): string {
  if (!row.delivered) return formatRate(0);
  return row.bps == null ? '—' : formatRate(row.bps);
}

export function toggleTopic(expanded: ReadonlySet<string>, topic: string): Set<string> {
  const next = new Set(expanded);
  if (next.has(topic)) next.delete(topic);
  else next.add(topic);
  return next;
}

/** 「すべて展開」 / 「すべて折りたたむ」: expand every topic unless all already are. */
export function toggleAllTopics(expanded: ReadonlySet<string>, topics: readonly string[]): Set<string> {
  const allOpen = topics.length > 0 && topics.every((tp) => expanded.has(tp));
  return allOpen ? new Set() : new Set(topics);
}
