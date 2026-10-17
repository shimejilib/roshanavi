// Data for the edge dialog: QoS of both sides and why data may not arrive (pure).

import type { GraphEdge, GraphSnapshot, TrafficEntry } from '../api/types';
import { t } from '../i18n';
import { diagnosticText } from './diagnosticsText';

export interface EdgeDetails {
  edge: GraphEdge | undefined;
  /** Every endpoint of the topic, publishers first (the clicked edge included). */
  endpoints: GraphEdge[];
  reasons: string[];
}

export function edgeDetails(graph: GraphSnapshot | null, topic: string, node: string, dir: 'pub' | 'sub', traffic: TrafficEntry | undefined): EdgeDetails {
  const edges = graph?.edges.filter((e) => e.topic === topic) ?? [];
  const edge = edges.find((e) => e.node === node && e.dir === dir);
  const endpoints = [...edges].sort((a, b) => (a.dir === b.dir ? a.node.localeCompare(b.node) : a.dir === 'pub' ? -1 : 1));
  const diags = (graph?.diagnostics ?? []).filter((d) => d.topic === topic && (d.nodes.length === 0 || d.nodes.includes(node)));
  const reasons = diags.map(diagnosticText);
  if (reasons.length === 0) {
    if (!edges.some((e) => e.dir === 'pub')) reasons.push(t('edge.noPublisher'));
    else if (traffic && (traffic.stale || traffic.total_count === 0)) reasons.push(t('edge.noData'));
  }
  return { edge, endpoints, reasons };
}

export function qosCells(e: GraphEdge): string[] {
  const ms = (v: number | null | undefined) => (v == null ? t('edge.unlimited') : `${v} ms`);
  return [e.qos.reliability, e.qos.durability, e.qos.depth ? String(e.qos.depth) : '—', ms(e.qos.deadline_ms), e.qos.liveliness ?? '—'];
}
