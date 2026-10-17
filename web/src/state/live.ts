// Pure reducer for /ws/live frames (unit-tested).

import type { RecordingStatus } from '../api/mediaTypes';
import type { ResourceLive } from '../api/resourceTypes';
import type { TracingStatus } from '../api/tracingTypes';
import type { BuildStatus, GraphSnapshot, Job, LiveMessage, Measurement, Target, TrafficEntry } from '../api/types';

export interface LiveData {
  graph: GraphSnapshot | null;
  traffic: Map<string, TrafficEntry>;
  jobs: Job[];
  targets: Target[];
  build: BuildStatus | null;
  recording: RecordingStatus | null;
  measurement: Measurement | null;
  tracing: TracingStatus | null;
  /** Per-node CPU / memory for the map badges, plus resource warnings (docs/design/resources.md). */
  resources: ResourceLive | null;
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
  recording: null,
  measurement: null,
  tracing: null,
  resources: null,
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
    recording: msg.recording === undefined ? prev.recording : msg.recording,
    measurement: msg.measurement ?? prev.measurement,
    tracing: msg.tracing ?? prev.tracing,
    resources: msg.resources ?? prev.resources,
    tick: prev.tick + 1,
    receivedAt: nowMs,
  };
}
