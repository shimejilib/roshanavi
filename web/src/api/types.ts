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

export interface GraphNode {
  id: string;
  name: string;
  namespace: string;
  role: Role;
  job_id?: string;
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
