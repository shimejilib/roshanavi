// Traffic per (node × topic × direction): rows under a topic, or grouped by node (pure, docs/design/ui.md).
//
// Publisher values come from the backend split (rates.py: exact / measured /
// estimated / configured / unknown); subscriber values are theoretical (what the
// QoS-compatible publishers send) or 0 when nothing can be delivered; with
// 詳細計測モード a covered subscriber is `measured` inside the node (`trace`).

import type { SubscriberTrace } from '../api/tracingTypes';
import type { TrafficEntry } from '../api/types';
import { t, tDynamic } from '../i18n';
import { formatHz, formatRate } from '../lib/format';
import { isNotMeasured, NO_VALUE } from './notMeasured';

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
  /** The topic is measured (subscribed by roshanavi); false = no number from that, only the trace (#61). */
  topicMeasured: boolean;
  /** Subscriber rows: trace values (詳細計測モード). */
  trace?: SubscriberTrace;
  /** Publisher rows: sends counted by the trace. */
  hzTraced?: number | null;
}

export interface NodeTraffic {
  node: string;
  rows: EndpointRow[];
}

const byNode = (a: EndpointRow, b: EndpointRow) => a.node.localeCompare(b.node);

/** Publisher rows (by node) then subscriber rows (by node) of one topic. */
export function topicEndpoints(entry: TrafficEntry): EndpointRow[] {
  const base = { topic: entry.topic, type: entry.type, topicMeasured: !isNotMeasured(entry) };
  const pubs: EndpointRow[] = (entry.publishers ?? []).map((p) => ({
    ...base, node: p.node, dir: 'pub', hz: p.hz, bps: p.bps, basis: p.basis, delivered: true, hzTraced: p.hz_traced,
  }));
  const subs: EndpointRow[] = (entry.subscribers ?? []).map((s) => ({
    ...base, node: s.node, dir: 'sub', hz: s.hz, bps: s.bps, basis: s.basis, delivered: s.delivered, trace: s,
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

/** Badge key: a row measured by the trace reads 実測(トレース) (a subscriber's receive count, a publisher's send count). */
export function displayBasis(row: Pick<EndpointRow, 'dir' | 'basis'>): string {
  if (row.dir === 'sub' && row.basis === 'measured') return 'traced';
  return row.dir === 'pub' && row.basis === 'traced' ? 'traced_pub' : row.basis;
}

export function basisLabel(basis: string): string {
  return tDynamic(`traffic.basis.${basis}`, 'traffic.basis.other', { basis });
}

export function basisHelp(basis: string): string {
  return tDynamic(`traffic.basisHelp.${basis}`, 'traffic.basisHelp.other', { basis });
}

export function endpointHz(row: Pick<EndpointRow, 'hz' | 'delivered'>): string {
  if (!row.delivered) return t('traffic.notDelivered');
  return row.hz == null ? NO_VALUE : formatHz(row.hz);
}

export function endpointBandwidth(row: Pick<EndpointRow, 'bps' | 'delivered' | 'hz' | 'topicMeasured'>): string {
  if (!row.delivered) return formatRate(0);
  if (row.bps != null) return formatRate(row.bps);
  // A Hz from the trace on a topic nobody subscribes to: say why there is no bandwidth.
  return !row.topicMeasured && row.hz != null ? t('monitor.noBandwidth') : NO_VALUE;
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
