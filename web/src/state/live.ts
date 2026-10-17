// Pure reducer for /ws/live frames (unit-tested).

import type { BuildStatus, GraphSnapshot, Job, LiveMessage, Target, TrafficEntry } from '../api/types';

export interface LiveData {
  graph: GraphSnapshot | null;
  traffic: Map<string, TrafficEntry>;
  jobs: Job[];
  targets: Target[];
  build: BuildStatus | null;
  /** Increments on every applied frame (drives particle pulses). */
  tick: number;
  receivedAt: number;
}

export const EMPTY_LIVE: LiveData = {
  graph: null,
  traffic: new Map(),
  jobs: [],
  targets: [],
  build: null,
  tick: 0,
  receivedAt: 0,
};

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
    targets: msg.targets ?? prev.targets,
    build: msg.build ?? prev.build,
    tick: prev.tick + 1,
    receivedAt: nowMs,
  };
}
