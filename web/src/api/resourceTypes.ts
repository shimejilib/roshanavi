// Resource monitoring (docs/design/resources.md): /api/resources, /ws/resources, /ws/live.resources.

import type { Diagnostic } from './types';

export type Confidence = 'exact' | 'heuristic';
export type ProcGroup = 'ros' | 'self' | 'other';

export interface LeakState {
  slope_mb_per_min: number | null;
  suspect: boolean;
  span_sec: number;
  warming_up: boolean;
}

export interface ConnInfo {
  pid: number;
  proto: 'tcp' | 'udp';
  laddr: string;
  raddr: string;
  rhost: string | null;
  status: string;
  local: boolean;
  group?: ProcGroup | null;
  label?: string | null;
  name?: string | null;
  nodes?: string[];
}

export interface ConnEvent extends ConnInfo {
  seq: number;
  kind: 'open' | 'close';
  t: number;
}

export interface ProcInfo {
  pid: number;
  ppid: number;
  name: string;
  exe: string;
  group: ProcGroup;
  label: string;
  role: string | null;
  target_id: string | null;
  nodes: string[];
  cpu_pct: number | null;
  cpu_norm_pct: number | null;
  rss: number;
  uss: number | null;
  threads: number | null;
  fds: number | null;
  read_bps: number | null;
  write_bps: number | null;
  gpu_mem?: number | null;
  leak?: LeakState | null;
  gpu_leak?: LeakState | null;
  connections?: ConnInfo[];
  udp_sockets?: number | null;
  listening?: number | null;
}

export interface NodeResource {
  node: string;
  pid: number | null;
  pids: number[];
  confidence: Confidence;
  source: 'launcher' | 'cmdline' | 'exe';
  target_id: string | null;
  shared: string[];
  scope: 'process' | 'target';
  name: string | null;
  cpu_pct: number | null;
  cpu_norm_pct: number | null;
  rss: number | null;
  uss: number | null;
  threads: number | null;
  fds: number | null;
  read_bps: number | null;
  write_bps: number | null;
  gpu_mem: number | null;
  connections: number;
  leak: LeakState | null;
  gpu_leak: LeakState | null;
}

export interface NicInfo {
  name: string;
  rx_bps: number | null;
  tx_bps: number | null;
  rx_pps: number | null;
  tx_pps: number | null;
  errin: number;
  errout: number;
  dropin: number;
  dropout: number;
  err_per_sec: number | null;
  drop_per_sec: number | null;
}

export interface GpuDevice {
  index: number;
  name: string | null;
  util_pct: number | null;
  mem_used: number | null;
  mem_total: number | null;
  temp_c: number | null;
}

export interface HostInfo {
  cpu: { total_pct: number | null; per_core: number[]; cores: number };
  mem: { total: number; available: number; used: number; pct: number | null; swap_total: number; swap_used: number; swap_pct: number | null };
  disk: {
    path: string;
    device?: string | null;
    free?: number;
    total?: number;
    free_pct?: number;
    level?: 'ok' | 'warn' | 'stop';
    read_bps?: number | null;
    write_bps?: number | null;
    error?: string;
  };
  nics: NicInfo[];
  udp: { rcvbuf_errors: number; sndbuf_errors: number; in_errors: number; rcvbuf_per_sec: number | null; sndbuf_per_sec: number | null; rcvbuf_recent: number; recent_sec: number } | null;
  gpu: { available: boolean; reason: string | null; wsl: boolean; devices: GpuDevice[]; per_process: boolean };
}

export interface ShareItem {
  name: string;
  cpu_norm_pct: number;
  rss: number;
  count: number;
}

export interface Breakdown {
  cpu: { ros: number; self: number; other: number | null; total: number | null; other_top: ShareItem[] };
  mem: { ros: number; self: number; other: number | null; total: number | null; other_top: ShareItem[] };
  counts: Record<ProcGroup, number>;
}

export interface SamplerCost {
  cpu_pct: number | null;
  last_ms: number;
  processes: number;
}

export interface ResourceSnapshot {
  available: boolean;
  reason?: string;
  scope?: 'this_host';
  hostname?: string;
  ncpu?: number;
  own_user_only?: boolean;
  sampled_at?: number;
  period_sec?: number;
  host?: HostInfo;
  breakdown?: Breakdown;
  processes?: ProcInfo[];
  others?: ProcInfo[];
  nodes?: Record<string, NodeResource>;
  connections?: ConnInfo[];
  events?: ConnEvent[];
  diagnostics?: Diagnostic[];
  sampler?: SamplerCost;
}

/** Compact per-node figures pushed with every /ws/live frame (map badges). */
export interface NodeBadge {
  cpu_pct: number | null;
  cpu_norm_pct: number | null;
  rss: number | null;
  confidence: Confidence;
  shared: string[];
  scope: 'process' | 'target';
  pid: number | null;
  leak: LeakState | null;
}

export interface ResourceLive {
  available: boolean;
  reason?: string;
  nodes: Record<string, NodeBadge>;
  host?: { cpu_pct: number | null; mem_pct: number | null };
  self?: { cpu_pct: number; rss: number };
  sampler?: SamplerCost | null;
  diagnostics: Diagnostic[];
}

export interface HistorySeries {
  pids: number[];
  t: number[];
  cpu_pct: (number | null)[];
  rss: (number | null)[];
  read_bps: (number | null)[];
  write_bps: (number | null)[];
  gpu_mem: (number | null)[];
  connections: (number | null)[];
}

export interface NodeHistoryResponse {
  node: string;
  history: HistorySeries | null;
  current: NodeResource | null;
  connections: ConnInfo[];
}
