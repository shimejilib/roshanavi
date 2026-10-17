// "入出力だけ表示" / "上流・下流だけ表示": cut the snapshot down to one node's
// direct topics, or to everything on a path through one topic (pure).

import type { GraphEdge, GraphSnapshot } from '../api/types';
import type { Isolation } from '../state/AppState';
import { focusSet, type DirectedEdge } from './focus';
import { nodeElementId, topicElementId } from './model';

function directed(e: GraphEdge): DirectedEdge {
  const node = nodeElementId(e.node);
  const topic = topicElementId(e.topic);
  return e.dir === 'pub'
    ? { id: `${node}>${topic}`, source: node, target: topic }
    : { id: `${topic}>${node}`, source: topic, target: node };
}

function keepIds(snap: GraphSnapshot, isolation: NonNullable<Isolation>): Set<string> {
  const { elementId } = isolation;
  if (isolation.mode === 'flow') return focusSet(elementId, snap.edges.map(directed));
  const keep = new Set([elementId]);
  for (const e of snap.edges) {
    if (nodeElementId(e.node) === elementId) keep.add(topicElementId(e.topic));
  }
  return keep;
}

export function isolateSnapshot(snap: GraphSnapshot, isolation: Isolation): GraphSnapshot {
  if (!isolation) return snap;
  const keep = keepIds(snap, isolation);
  const nodes = snap.nodes.filter((n) => keep.has(nodeElementId(n.id)));
  const topics = snap.topics.filter((tp) => keep.has(topicElementId(tp.name)));
  const edges = snap.edges.filter((e) => keep.has(nodeElementId(e.node)) && keep.has(topicElementId(e.topic)));
  return { ...snap, nodes, topics, edges };
}
