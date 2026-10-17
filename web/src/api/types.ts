// Shapes of the roshanavi REST / WebSocket API (docs/DESIGN.md §4.8).

export type Role = 'mine' | 'dependency' | 'dummy' | 'other';

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
}

export type InjectMode = 'once' | 'periodic' | 'stream' | 'bag';

export interface Job {
  id: string;
  mode: InjectMode;
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
}

export interface LiveMessage {
  traffic: TrafficEntry[];
  jobs: Job[];
  graph?: GraphSnapshot;
  targets?: Target[];
  build?: BuildStatus;
}

// ---- Launcher (DESIGN §4.9) ------------------------------------------------

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
}

export interface DummySpec {
  id: string;
  name: string;
  namespace?: string;
  topic: string;
  type: string;
  mode: 'once' | 'periodic' | 'stream';
  payload?: Record<string, unknown>;
  rate_hz?: number;
  count?: number;
  source?: string;
  loop?: boolean;
  qos?: { reliability: string; durability: string; depth: number };
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
  kind: 'run' | 'launch' | 'dummy';
  role: 'mine' | 'dependency' | 'dummy';
  spec: TargetSpec | DummySpec;
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
  project: { version: number; targets?: TargetSpec[]; dummies?: DummySpec[]; watch_topics?: string[] };
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
