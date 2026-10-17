// Pure reducer for /ws/live frames (unit-tested).

import type { GraphSnapshot, Job, LiveMessage, TrafficEntry } from '../api/types';

export interface LiveData {
  graph: GraphSnapshot | null;
  traffic: Map<string, TrafficEntry>;
  jobs: Job[];
  /** Increments on every applied frame (drives particle pulses). */
  tick: number;
  receivedAt: number;
}

export const EMPTY_LIVE: LiveData = { graph: null, traffic: new Map(), jobs: [], tick: 0, receivedAt: 0 };

export function isLiveMessage(value: unknown): value is LiveMessage {
  if (typeof value !== 'object' || value === null) return false;
  const v = value as Record<string, unknown>;
  return Array.isArray(v.traffic) && Array.isArray(v.jobs);
}

export function applyLive(prev: LiveData, msg: LiveMessage, nowMs: number): LiveData {
  const graph = msg.graph ? { ...msg.graph, diagnostics: msg.graph.diagnostics ?? [] } : prev.graph;
  return {
    graph,
    traffic: new Map(msg.traffic.map((e) => [e.topic, e])),
    jobs: msg.jobs,
    tick: prev.tick + 1,
    receivedAt: nowMs,
  };
}
