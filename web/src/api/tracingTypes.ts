// 詳細計測モード (LTTng tracing, backend roshanavi/tracing) — GET/PUT /api/tracing, /ws/live `tracing`.

export interface CallbackMs {
  avg: number;
  p95: number;
  max: number;
}

/** Trace values added to a subscriber row when the trace covers that node (basis `measured`). */
export interface SubscriberTrace {
  /** What the QoS-compatible senders sent (the former theoretical value). */
  hz_expected?: number | null;
  /** Messages the node took out of its queue (rmw_take). */
  hz_recv?: number | null;
  /** Callbacks that finished (rclcpp only; null for rclpy). */
  hz_processed?: number | null;
  cb_ms?: CallbackMs | null;
  lang?: 'cpp' | 'py';
  intra?: boolean;
  /** Callback function name as registered by rclcpp (may be a lambda signature). */
  symbol?: string | null;
  behind?: Behind | null;
}

export interface Behind {
  incoming_hz: number;
  processed_hz: number;
  /** sent = what the senders sent (measured per publisher); received = what was taken. */
  basis: 'sent' | 'received';
  cb_avg_ms?: number;
}

export type UnsupportedReason = 'rclpy' | 'intra_process' | 'restart_needed' | 'not_traced';

export interface UnsupportedNode {
  node: string;
  reason: UnsupportedReason;
  pid: number | null;
}

export interface BehindDiagnostic extends Behind {
  code: 'processing_behind';
  node: string;
  topic: string;
}

export interface TracingStatus {
  available: boolean;
  /** Why it cannot run: disabled = --tracing off, not_installed = lttng-tools missing,
   * bt2_missing = python3-bt2 missing, failed = the worker could not start. */
  reason: 'disabled' | 'not_installed' | 'bt2_missing' | 'failed' | null;
  active: boolean;
  active_sec: number | null;
  /** Active and a fresh result arrived. */
  receiving: boolean;
  error: { code: string; message: string } | null;
  events_per_sec: number | null;
  /** Events LTTng dropped because a buffer was full (since the mode was turned on). */
  discarded: number;
  disk_bytes: number | null;
  parse_ms: number | null;
  buffer_per_cpu: number | null;
  skipped_chunks: number;
  cpu_percent: { server: number | null; worker: number | null; lttng: number | null; total: number | null };
  restarts: number;
  unsupported: UnsupportedNode[];
  diagnostics: BehindDiagnostic[];
}
