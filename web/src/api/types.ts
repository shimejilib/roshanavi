// Shapes of the roshanavi REST / WebSocket API (docs/design/api.md).

import type { PortKind } from '../datakind/kinds';
import type { SubscriberTrace, TracingStatus } from './tracingTypes';
import type { MediaOptions, RecordingStatus } from './mediaTypes';
import type { TransformSpec } from './transformTypes';
import type { FunctionSpec, FunctionStatus } from './functionTypes';

export type Role = 'mine' | 'dependency' | 'dummy' | 'transform' | 'function' | 'other';

export interface Qos {
  reliability: string;
  durability: string;
  history?: string;
  depth?: number;
  deadline_ms?: number | null;
  liveliness?: string;
  lease_ms?: number | null;
}

export type MappingConfidence = 'exact' | 'heuristic';

export interface GraphNode {
  id: string;
  name: string;
  namespace: string;
  role: Role;
  job_id?: string;
  /** Launcher target that owns this node (when mapped). */
  target_id?: string;
  /** Managed (lifecycle) node: offers lifecycle_msgs services. */
  lifecycle?: boolean;
  confidence?: MappingConfidence;
}

export interface GraphTopic {
  name: string;
  types: string[];
}

export interface GraphEdge {
  node: string;
  topic: string;
  dir: 'pub' | 'sub';
  qos: Qos;
}

export type DiagnosticCode =
  | 'qos_incompatible'
  | 'no_subscriber'
  | 'no_publisher'
  | 'similar_names'
  | 'type_mismatch';

export interface QosReason {
  policy: 'reliability' | 'durability' | 'deadline' | 'liveliness' | 'liveliness_lease';
  pub: string | number | null;
  sub: string | number | null;
}

export interface Diagnostic {
  code: DiagnosticCode;
  severity: 'error' | 'warning' | 'info';
  topic: string;
  nodes: string[];
  detail: {
    publisher?: string;
    subscriber?: string;
    reasons?: QosReason[];
    published?: string;
    subscribed?: string;
    types?: string[];
  };
}

export interface GraphSnapshot {
  nodes: GraphNode[];
  topics: GraphTopic[];
  edges: GraphEdge[];
  diagnostics: Diagnostic[];
  hash: string;
}

export type TrafficStatus = 'ok' | 'not_monitored' | 'unsupported' | 'error';

export interface TrafficEntry {
  topic: string;
  type: string;
  status: TrafficStatus;
  monitored: boolean;
  collapsed: boolean;
  hz: number;
  hz_basis: 'source' | 'receive';
  hz_recv: number;
  hz_source: number | null;
  bytes_per_sec: number;
  avg_size: number;
  jitter_ms: number;
  jitter_recv_ms: number;
  dropped: number | null;
  drop_ratio: number | null;
  latency_ms: number | null;
  last_seen: number | null;
  total_count: number;
  recent_count: number;
  history: number[];
  error?: string | null;
  /** Averaging window of hz / bytes_per_sec (1, 5 or 10 s). */
  window_sec?: number;
  /** Nothing arrived for max(3 x expected period, 1 s): rates are reported as 0. */
  stale?: boolean;
  /** Span the rate was actually computed over (longer than window_sec when extended). */
  rate_window_sec?: number | null;
  /** extended = slower than the window, measured over the longest one; too_few = not measurable. */
  rate_note?: 'extended' | 'too_few' | null;
  /** Publishers of this topic (non-self) and their share of the rate (backend rates.py). */
  source_count?: number;
  publishers?: PublisherRate[];
  /** Subscribers and their theoretical rate (sum of QoS-compatible publishers, backend sub_rates.py). */
  subscribers?: SubscriberRate[];
  /** probe = C++ measurement node (per publisher), python = fallback monitor (per topic). */
  measurement?: 'probe' | 'python';
  /** Probe only: one row per publisher gid (node is null when the RMW gid did not match). */
  endpoints?: ProbeEndpoint[];
}

export interface ProbeEndpoint {
  gid: string;
  node: string | null;
  resolved: boolean;
  hz: number;
  bps: number;
  count: number;
  bytes: number;
  dropped: number | null;
  stale: boolean;
  rate_note: 'extended' | 'too_few' | null;
}

/** How traffic is measured right now (GET /api/traffic `measurement`, /ws/live). */
export interface Measurement {
  mode: 'probe' | 'python';
  /** python only: why the probe is not used. */
  reason: 'disabled' | 'not_built' | 'crashed' | 'unavailable' | null;
  state: 'running' | 'restarting' | 'stopped' | 'failed' | null;
  pid: number | null;
  restarts: number;
  receiving: boolean;
  cpu_percent: number | null;
  rss_bytes: number | null;
  rmw: string | null;
  /** matched = publisher gids map to graph nodes; unmatched = this RMW cannot tell them apart. */
  gid_resolution: 'matched' | 'unmatched' | 'unknown';
}

/** exact = counted by roshanavi, configured = dummy node setting, measured = counted per
 * publisher by the probe (or the only publisher: topic total), estimated = total minus
 * known, unknown = cannot split. */
export type RateBasis = 'exact' | 'configured' | 'measured' | 'estimated' | 'unknown';

/** theoretical = what compatible publishers send (not measured inside the subscriber);
 * not_delivered = no QoS-compatible publisher; measured = counted inside the node by the trace
 * (詳細計測モード). */
export type SubscriberBasis = 'theoretical' | 'not_delivered' | 'measured';

export interface SubscriberRate extends SubscriberTrace {
  node: string;
  hz: number | null;
  bps: number | null;
  basis: SubscriberBasis;
  delivered: boolean;
  sources: string[];
}

export interface PublisherRate {
  node: string;
  hz: number | null;
  bps: number | null;
  basis: RateBasis;
  /** 詳細計測モード: sends counted by the trace (rmw_publish), a cross-check of `hz`. */
  hz_traced?: number | null;
}

export type InjectMode = 'once' | 'periodic' | 'stream' | 'bag' | 'media';
/** Modes that only appear in job lists (browser capture is started over /ws/capture). */
export type JobMode = InjectMode | 'capture';

export interface Job {
  id: string;
  mode: JobMode;
  topic: string | null;
  type: string | null;
  rate_hz: number | null;
  count: number | null;
  source: string | null;
  state: 'running' | 'done' | 'stopped' | 'error';
  sent: number;
  error: string | null;
  created_at: number;
  finished_at: number | null;
  send_hz?: number | null;
  paused?: boolean;
  /** periodic / stream / media jobs can be paused (sending skipped, timing kept). */
  pausable?: boolean;
  /** media / capture jobs */
  dropped?: number;
  companions?: string[];
  /** media jobs: wakes later than one chunk (real-time pacing) */
  late_events?: number;
  max_lateness_ms?: number;
  late_policy?: 'shift' | 'catch_up' | 'drop';
}

export interface LiveMessage {
  traffic: TrafficEntry[];
  jobs: Job[];
  graph?: GraphSnapshot;
  targets?: Target[];
  build?: BuildStatus;
  recording?: RecordingStatus | null;
  /** Server clock (epoch seconds) when the frame was built. */
  server_time?: number;
  measurement?: Measurement;
  tracing?: TracingStatus;
}

// ---- Launcher (docs/design/launcher.md) ------------------------------------------------

export type ParamValue = string | number | boolean;

export interface TargetSpec {
  id: string;
  kind: 'run' | 'launch';
  package: string;
  executable?: string;
  launch_file?: string;
  args?: string[];
  params?: Record<string, ParamValue>;
  params_file?: string;
  remaps?: Record<string, string>;
  namespace?: string;
  name?: string;
  role?: 'mine' | 'dependency';
  autostart?: boolean;
  auto_restart?: boolean;
  /** The launch file this target was decomposed from (informational). */
  imported_from?: string;
}

export interface DummySpec {
  id: string;
  name: string;
  namespace?: string;
  topic: string;
  type: string;
  /** データの種類 chosen in the UI (informational; fits `type`). */
  kind?: PortKind;
  mode: 'once' | 'periodic' | 'stream' | 'media';
  payload?: Record<string, unknown>;
  rate_hz?: number;
  count?: number;
  source?: string;
  loop?: boolean;
  qos?: { reliability: string; durability: string; depth: number };
  media?: MediaOptions;
  autostart?: boolean;
  auto_restart?: boolean;
}

export type TargetStatus = 'stopped' | 'starting' | 'running' | 'exited' | 'crashed' | 'invalid';

export interface TargetNode {
  node: string;
  confidence: MappingConfidence;
  pid: number | null;
}

export interface Target {
  id: string;
  kind: 'run' | 'launch' | 'dummy' | 'transform' | 'function';
  role: 'mine' | 'dependency' | 'dummy' | 'transform' | 'function';
  spec: TargetSpec | DummySpec | TransformSpec | FunctionSpec;
  status: TargetStatus;
  exit_code: number | null;
  problem: string | null;
  pid: number | null;
  pids: number[];
  command: string[] | null;
  started_at: number | null;
  uptime_sec: number | null;
  restart_count: number;
  pending_restart: boolean;
  nodes?: TargetNode[];
  /** Function nodes: the running node's status (null when stopped / not reported yet). */
  function_status?: FunctionStatus | null;
}

export interface WorkspacePackage {
  name: string;
  origin: 'workspace' | 'system';
  prefix: string | null;
  sourced: boolean;
  built: boolean;
  source_dir: string | null;
  executables: string[];
  launch_files: string[];
}

export interface WorkspaceInfo {
  root: string;
  scanned_at: number;
  packages: WorkspacePackage[];
}

export interface BuildStatus {
  state: 'idle' | 'running' | 'succeeded' | 'failed';
  package?: string;
  exit_code?: number | null;
  started_at?: number;
  finished_at?: number | null;
  error_lines?: string[];
  needs_resource?: boolean;
  restarted?: string[];
  log_id?: string;
}

export interface LogLine {
  seq: number;
  ts: number;
  stream: 'stdout' | 'stderr' | 'system';
  text: string;
}

export interface ProjectState {
  path: string;
  exists: boolean;
  dirty: boolean;
  error: string | null;
  /** Last autosave failure (null when the last save worked). */
  save_error?: string | null;
  /** False while a project file that failed to load is protected from overwriting. */
  autosave?: boolean;
  project: {
    version: number;
    targets?: TargetSpec[];
    dummies?: DummySpec[];
    transforms?: TransformSpec[];
    functions?: FunctionSpec[];
    watch_topics?: string[];
  };
}

export interface ExportResult {
  directory: string;
  launch_file: string;
  files: string[];
  command: string;
}

export interface InjectRequest {
  mode: InjectMode;
  topic?: string;
  type?: string;
  payload?: Record<string, unknown>;
  rate_hz?: number;
  count?: number;
  source?: string;
  loop?: boolean;
  qos?: { reliability: 'reliable' | 'best_effort'; durability: 'volatile' | 'transient_local'; depth: number };
  bag_rate?: number;
  topics?: string[];
  media?: MediaOptions;
}

export interface DataFile {
  path: string;
  size: number;
  kind: string;
}

export interface EchoMessage {
  topic: string;
  type: string;
  seq: number;
  msg: unknown;
}
