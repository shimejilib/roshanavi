// What a node receives and sends, for the right pane (pure, docs/design/ui.md).
// The data shown is what flows on the topic, not proof the node got it; a
// QoS mismatch is called out as "not delivered to this node".

import type { GraphEdge, GraphSnapshot, Qos, TrafficEntry } from '../api/types';
import { isHiddenTopic } from '../lib/topics';

/** Same set as the backend (traffic.HEAVY_TYPES): only shown when opened. */
export const HEAVY_TYPES = new Set([
  'sensor_msgs/msg/Image',
  'sensor_msgs/msg/CompressedImage',
  'sensor_msgs/msg/PointCloud2',
  'sensor_msgs/msg/PointCloud',
]);
export const AUTO_OPEN = 3;

export interface IoItem {
  key: string;
  topic: string;
  dir: 'pub' | 'sub';
  types: string[];
  qos: Qos;
  /** Subscription that cannot receive this topic (incompatible QoS). */
  blocked: boolean;
  heavy: boolean;
  entry: TrafficEntry | undefined;
}

export interface NodeIo {
  inputs: IoItem[];
  outputs: IoItem[];
}

function blockedSubs(graph: GraphSnapshot, nodeId: string): Set<string> {
  return new Set(
    graph.diagnostics
      .filter((d) => d.code === 'qos_incompatible' && d.detail.subscriber === nodeId)
      .map((d) => d.topic),
  );
}

export function nodeIo(graph: GraphSnapshot | null, nodeId: string, traffic: Map<string, TrafficEntry>): NodeIo {
  if (!graph) return { inputs: [], outputs: [] };
  const blocked = blockedSubs(graph, nodeId);
  const types = new Map(graph.topics.map((tp) => [tp.name, tp.types]));
  const toItem = (e: GraphEdge): IoItem => {
    const topicTypes = types.get(e.topic) ?? [];
    return {
      key: `${e.dir}:${e.topic}`,
      topic: e.topic,
      dir: e.dir,
      types: topicTypes,
      qos: e.qos,
      blocked: e.dir === 'sub' && blocked.has(e.topic),
      heavy: topicTypes.some((tp) => HEAVY_TYPES.has(tp)),
      entry: traffic.get(e.topic),
    };
  };
  const mine = graph.edges.filter((e) => e.node === nodeId && !isHiddenTopic(e.topic));
  const byTopic = (a: IoItem, b: IoItem) => a.topic.localeCompare(b.topic);
  return {
    inputs: mine.filter((e) => e.dir === 'sub').map(toItem).sort(byTopic),
    outputs: mine.filter((e) => e.dir === 'pub').map(toItem).sort(byTopic),
  };
}

/** Keys opened initially: the first AUTO_OPEN light topics (inputs first). Heavy ones wait for a click. */
export function initialOpen(io: NodeIo): Set<string> {
  return new Set([...io.inputs, ...io.outputs].filter((item) => !item.heavy && !item.blocked).slice(0, AUTO_OPEN).map((item) => item.key));
}
