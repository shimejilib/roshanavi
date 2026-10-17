// Shapes of the scenario API (docs/design/scenarios.md, docs/design/api.md).

export type StepKind =
  | 'send'
  | 'start'
  | 'stop'
  | 'play'
  | 'wait'
  | 'expect'
  | 'always'
  | 'never'
  | 'rate'
  | 'throughput'
  | 'latency'
  | 'resources'
  | 'mem_growth'
  | 'call';

export type Op =
  | 'eq'
  | 'ne'
  | 'lt'
  | 'le'
  | 'gt'
  | 'ge'
  | 'range'
  | 'approx'
  | 'regex'
  | 'contains'
  | 'exists'
  | 'len_eq'
  | 'len_range';

export interface Condition {
  field: string;
  op: Op;
  value?: unknown;
  tol?: number;
  min?: number;
  max?: number;
}

/** One step as written in the YAML: `{expect: {...}}`, `{wait: 1.0}`, `{stop: 'cam'}`. */
export type StepRaw = Partial<Record<StepKind, unknown>>;

export interface ScenarioSpec {
  version?: number;
  name: string;
  description?: string;
  setup?: Record<string, unknown>[];
  guards?: Record<string, unknown>[];
  steps: StepRaw[];
}

export interface SchemaError {
  path: string;
  line: number | null;
  message: string;
}

export type RunStatus = 'pending' | 'running' | 'passed' | 'failed' | 'error' | 'skipped' | 'cancelled';

export interface RunSummary {
  run_id: string;
  scenario_id: string | null;
  name: string;
  file: string;
  status: RunStatus;
  started_at: number;
  duration_sec: number;
  message: string;
  failed: { index: number; kind: string; message: string } | null;
}

export interface ScenarioItem {
  id: string;
  source: 'project' | 'example';
  file: string;
  read_only: boolean;
  name: string;
  description: string | null;
  steps: number;
  setup?: number;
  guards?: number;
  error: string | null;
  errors: SchemaError[];
  last_result?: RunSummary | null;
}

export interface ScenarioList {
  project_dir: string;
  items: ScenarioItem[];
  running: boolean;
}

export interface ScenarioFile extends ScenarioItem {
  yaml: string;
  spec: ScenarioSpec | null;
}

export interface Hint {
  code: string;
  topic: string;
  message: string;
}

export interface StepResult {
  index: number;
  kind: string;
  summary: string;
  line: number | null;
  status: RunStatus;
  message: string;
  details: Record<string, unknown>;
  hints: Hint[];
  approx: boolean;
  started_sec: number | null;
  duration_sec: number | null;
}

export interface SetupResult {
  index: number;
  kind: string;
  summary: string;
  status: RunStatus;
  message: string;
  log_tail: string[];
}

export interface RunResult {
  run_id: string;
  scenario_id: string | null;
  name: string;
  file: string;
  status: RunStatus;
  message: string;
  started_at: number;
  duration_sec: number;
  setup: SetupResult[];
  guards: StepResult[];
  steps: StepResult[];
  schema_errors: SchemaError[];
  passed: boolean;
  current_step: number | null;
}

export interface ValidateResult {
  ok: boolean;
  errors: SchemaError[];
  message?: string;
  spec?: ScenarioSpec;
  yaml?: string;
}

/** What the server saw in record mode: an operation of the UI, or a watched message. */
export type RecordEvent =
  | { seq: number; t: number; kind: 'op'; op: RecordedOp }
  | { seq: number; t: number; kind: 'msg'; topic: string; type: string; data: unknown };

export type RecordedOp =
  | { kind: 'inject'; job_id: string; request: Record<string, unknown> }
  | { kind: 'inject_stop'; job_id: string }
  | { kind: 'class_call'; node: string; method: string }
  | { kind: 'target_start' | 'target_stop' | 'target_restart'; target_id: string; target_kind?: string };

export interface RecordSession {
  id: string;
  watch: string[];
  started_at: number;
  elapsed_sec: number | null;
  types: Record<string, string>;
  counts: Record<string, number>;
  dropped: number;
}

export interface RecordStatus {
  active: boolean;
  session: RecordSession | null;
}

export interface MeasureRequest {
  kind: 'rate' | 'throughput' | 'latency';
  start: number;
  end: number;
  topic?: string;
  input?: string;
  output?: string;
  match?: 'header.stamp' | 'order';
}

export interface Measurement {
  kind: string;
  hz?: number | null;
  count?: number;
  inputs?: number;
  outputs?: number;
  ratio?: number | null;
  pairs?: number;
  p50_ms?: number | null;
  p95_ms?: number | null;
  max_ms?: number | null;
}

export interface ScenarioFrame {
  record: RecordStatus & { events: RecordEvent[] };
  running: boolean;
  run?: RunResult;
}
