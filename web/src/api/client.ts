// REST client. Every failure becomes an ApiError with the server's error code.

import type { NodeHistoryResponse, ResourceSnapshot } from './resourceTypes';
import type { TracingStatus } from './tracingTypes';
import type {
  Measurement,
  MeasureRequest,
  RecordEvent,
  RecordStatus,
  RunResult,
  RunSummary,
  ScenarioFile,
  ScenarioList,
  ScenarioSpec,
  ValidateResult,
} from './scenarioTypes';
import type { PreviewResult, ProjectList, TransformSpec } from './transformTypes';
import { t, tDynamic } from '../i18n';
import { topicPath } from '../lib/topics';
import type { KindCatalog, TypeGroup } from '../datakind/kinds';
import type { ActionRecord, ClassSpec } from './classTypes';
import type { FunctionSpec, ModuleEntry, ModuleInfo } from './functionTypes';
import type { CodeLocationsReport, CodeSettings, DependencyHint, ScaffoldResult } from './codeTypes';
import type {
  BuildStatus,
  DataFile,
  DummySpec,
  EchoSample,
  ExportResult,
  GraphSnapshot,
  InjectRequest,
  Job,
  LogLine,
  ProjectState,
  Target,
  TargetSpec,
  WorkspaceInfo,
} from './types';
import type { MediaTypeInfo, RecordingsResponse, RecordingStatus } from './mediaTypes';
import type { InterfaceInfo, ParamSetRequest, ParamsResponse } from './nodeTypes';
import type {
  ImportCommitRequest,
  ImportCommitResult,
  ImportPlan,
  ImportSource,
  LifecycleInfo,
  LifecycleRequest,
  NodeListResponse,
} from './nodeListTypes';

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
  }
}

/** Plain-language (localized) explanation of an error, plus server detail. */
export function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    const head = err.code === 'network' ? t('error.network') : tDynamic(`error.${err.code}`, 'error.unknown');
    return err.message ? `${head}\n${t('error.detail', { message: err.message })}` : head;
  }
  if (err instanceof Error) return `${t('error.unknown')}\n${t('error.detail', { message: err.message })}`;
  return t('error.unknown');
}

function parseEnvelope(body: unknown, status: number): ApiError {
  if (typeof body === 'object' && body !== null && 'error' in body) {
    const error = (body as { error: { code?: unknown; message?: unknown } }).error;
    return new ApiError(String(error.code ?? 'unknown'), String(error.message ?? ''), status);
  }
  return new ApiError(status === 404 ? 'not_found' : 'unknown', `HTTP ${status}`, status);
}

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(path, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (err) {
    throw new ApiError('network', err instanceof Error ? err.message : String(err), 0);
  }
  let parsed: unknown = null;
  try {
    parsed = await resp.json();
  } catch {
    parsed = null;
  }
  if (!resp.ok) throw parseEnvelope(parsed, resp.status);
  return parsed as T;
}

export const api = {
  types: () => request<{ types: string[] }>('GET', '/api/types').then((r) => r.types),
  typeCatalog: () => request<{ types: string[]; groups: TypeGroup[] }>('GET', '/api/types'),
  dataKinds: () => request<KindCatalog>('GET', '/api/data-kinds'),
  graph: () => request<GraphSnapshot>('GET', '/api/graph'),
  template: (path: string) => request<{ type: string; template: Record<string, unknown> }>('GET', path),
  files: () => request<{ data_dir: string; files: DataFile[] }>('GET', '/api/files'),
  /** Latest message of an echoed topic, untruncated up to the server's size cap (transform preview). */
  echoSample: (topic: string) => request<EchoSample>('GET', `${topicPath('/api/echo', topic)}/sample`),
  startInject: (req: InjectRequest) => request<Job>('POST', '/api/inject', req),
  stopInject: (id: string) => request<Job>('DELETE', `/api/inject/${encodeURIComponent(id)}`),
  pauseInject: (id: string, paused: boolean) => request<Job>('POST', `/api/inject/${enc(id)}/${paused ? 'pause' : 'resume'}`),
  setMonitor: (topicApiPath: string, enabled: boolean) =>
    request<{ topic: string; enabled: boolean }>('PUT', topicApiPath, { enabled }),

  tracing: () => request<TracingStatus>('GET', '/api/tracing'),
  setTracing: (enabled: boolean) => request<TracingStatus>('PUT', '/api/tracing', { enabled }),

  workspace: () => request<WorkspaceInfo>('GET', '/api/workspace'),
  refreshWorkspace: () => request<WorkspaceInfo>('POST', '/api/workspace/refresh'),
  targets: () => request<{ targets: Target[] }>('GET', '/api/targets').then((r) => r.targets),
  addTarget: (spec: TargetSpec, start = false) => request<Target>('POST', `/api/targets${start ? '?start=true' : ''}`, spec),
  updateTarget: (spec: TargetSpec) => request<Target>('PUT', `/api/targets/${enc(spec.id)}`, spec),
  removeTarget: (id: string) => request<Target>('DELETE', `/api/targets/${enc(id)}`),
  targetAction: (id: string, action: 'start' | 'stop' | 'restart') =>
    request<Target>('POST', `/api/targets/${enc(id)}/${action}`),
  logs: (id: string, since = 0) =>
    request<{ lines: LogLine[]; cursor: number }>('GET', `/api/targets/${enc(id)}/logs?since=${since}`),
  clearLogs: (id: string) => request<{ cleared: string }>('DELETE', `/api/targets/${enc(id)}/logs`),
  build: (pkg: string, restartRunning: boolean) =>
    request<BuildStatus>('POST', '/api/build', { package: pkg, restart_running: restartRunning }),
  cancelBuild: () => request<BuildStatus>('DELETE', '/api/build'),
  project: () => request<ProjectState>('GET', '/api/project'),
  saveProject: () => request<ProjectState>('POST', '/api/project/save'),
  reloadProject: () => request<ProjectState>('POST', '/api/project/reload'),
  persistJob: (jobId: string, name: string, autostart: boolean) =>
    request<Target>('POST', `/api/inject/${enc(jobId)}/persist`, { name, autostart }),
  updateDummy: (spec: DummySpec) => request<Target>('PUT', `/api/dummies/${enc(spec.id)}`, spec),
  addDummy: (spec: DummySpec, start = true) => request<Target>('POST', `/api/dummies${start ? '?start=true' : ''}`, spec),
  addTransform: (spec: TransformSpec, start = true) =>
    request<Target>('POST', `/api/transforms${start ? '?start=true' : ''}`, spec),
  updateTransform: (spec: TransformSpec) => request<Target>('PUT', `/api/transforms/${enc(spec.id)}`, spec),
  functionModules: () => request<{ workspace: string; modules: ModuleEntry[] }>('GET', '/api/functions/modules'),
  functionModule: (name: string) => request<ModuleInfo>('GET', `/api/functions/module?name=${encodeURIComponent(name)}`),
  addFunction: (spec: FunctionSpec, start = true) => request<Target>('POST', `/api/functions${start ? '?start=true' : ''}`, spec),
  updateFunction: (spec: FunctionSpec) => request<Target>('PUT', `/api/functions/${enc(spec.id)}`, spec),
  codeLocations: (refresh = false) =>
    request<CodeLocationsReport>('GET', `/api/functions/locations${refresh ? '?refresh=true' : ''}`),
  putCodeLocations: (settings: CodeSettings) => request<CodeLocationsReport>('PUT', '/api/functions/locations', settings),
  scaffold: (name: string) => request<ScaffoldResult>('POST', '/api/functions/scaffold', { name }),
  dependencyHint: (missing: string, module?: string) =>
    request<DependencyHint>(
      'GET',
      `/api/functions/dependency?missing=${encodeURIComponent(missing)}${module ? `&module=${encodeURIComponent(module)}` : ''}`,
    ),
  exportFunctionCode: (id: string, directory: string) =>
    request<{ file: string; command: string }>('POST', `/api/functions/${enc(id)}/export-code`, { directory }),
  addClass: (spec: ClassSpec, start = true) => request<Target>('POST', `/api/classes${start ? '?start=true' : ''}`, spec),
  updateClass: (spec: ClassSpec) => request<Target>('PUT', `/api/classes/${enc(spec.id)}`, spec),
  callClassMethod: (id: string, method: string) =>
    request<{ method: string; topic: string; record: ActionRecord | null }>('POST', `/api/classes/${enc(id)}/call`, { method }),
  exportClassCode: (id: string, directory: string, lifecycle: boolean) =>
    request<{ file: string; command: string }>('POST', `/api/classes/${enc(id)}/export-code`, { directory, lifecycle }),
  previewTransform: (spec: TransformSpec, samples: Record<string, Record<string, unknown>>) =>
    request<PreviewResult>('POST', '/api/transforms/preview', { spec, samples }),
  projects: () => request<ProjectList>('GET', '/api/projects'),
  openProject: (id: string) => request<ProjectState>('POST', '/api/projects/open', { id }),
  exportDummies: (directory: string, ids: string[] = []) =>
    request<ExportResult>('POST', '/api/dummies/export', { directory, ids }),

  parameters: (node: string) => request<ParamsResponse>('GET', `${nodePath(node)}/parameters`),
  setParameter: (node: string, req: ParamSetRequest) =>
    request<{ node: string; parameter: unknown }>('PUT', `${nodePath(node)}/parameters`, req),
  nodeList: () => request<NodeListResponse>('GET', '/api/node-list'),
  lifecycle: (node: string) => request<LifecycleInfo>('GET', `${nodePath(node)}/lifecycle`),
  changeLifecycle: (node: string, req: LifecycleRequest) =>
    request<LifecycleInfo>('POST', `${nodePath(node)}/lifecycle`, req),
  importPreview: (source: ImportSource, args: Record<string, string>) =>
    request<ImportPlan>('POST', '/api/launch-import/preview', { source, args }),
  importCommit: (req: ImportCommitRequest) => request<ImportCommitResult>('POST', '/api/launch-import/commit', req),
  interfaceDef: (type: string) => request<InterfaceInfo>('GET', `/api/interfaces/${type.split('/').map(enc).join('/')}`),

  mediaTypes: (topic?: string) =>
    request<MediaTypeInfo>('GET', topic ? `/api/media/types?topic=${enc(topic)}` : '/api/media/types'),
  recordings: () => request<RecordingsResponse>('GET', '/api/recordings'),
  startRecording: (topics: string[], name: string) =>
    request<RecordingStatus>('POST', '/api/recordings', { topics, name }),
  stopRecording: () => request<RecordingStatus>('POST', '/api/recordings/stop'),
  deleteRecording: (name: string) => request<{ deleted: string }>('DELETE', `/api/recordings/${enc(name)}`),

  scenarios: () => request<ScenarioList>('GET', '/api/scenarios'),
  scenario: (id: string) => request<ScenarioFile>('GET', `/api/scenarios/${enc(id)}`),
  createScenario: (spec: ScenarioSpec, file?: string, overwrite = false) =>
    request<ScenarioFile>('POST', '/api/scenarios', { spec, ...(file ? { file } : {}), overwrite }),
  saveScenario: (id: string, body: { spec: ScenarioSpec } | { yaml: string }) =>
    request<ScenarioFile>('PUT', `/api/scenarios/${enc(id)}`, body),
  deleteScenario: (id: string) => request<{ deleted: string }>('DELETE', `/api/scenarios/${enc(id)}`),
  validateScenario: (body: { spec: ScenarioSpec } | { yaml: string }) =>
    request<ValidateResult>('POST', '/api/scenarios/validate', body),
  runScenario: (id: string) => request<RunResult>('POST', `/api/scenarios/${enc(id)}/run`),
  scenarioRuns: () =>
    request<{ runs: RunSummary[]; current: RunResult | null; running: boolean }>('GET', '/api/scenario-runs'),
  scenarioRun: (runId: string) => request<RunResult>('GET', `/api/scenario-runs/${enc(runId)}`),
  cancelScenarioRun: (runId: string) =>
    request<{ run_id: string; cancelling: boolean }>('POST', `/api/scenario-runs/${enc(runId)}/cancel`),
  startScenarioRecord: (watch: string[]) => request<RecordStatus>('POST', '/api/scenario-record', { watch }),
  stopScenarioRecord: (discard = false) =>
    request<RecordStatus>('DELETE', `/api/scenario-record${discard ? '?discard=true' : ''}`),
  scenarioRecord: (since = 0) =>
    request<RecordStatus & { events: RecordEvent[] }>('GET', `/api/scenario-record?since=${since}`),
  measureRecord: (req: MeasureRequest) => request<Measurement>('POST', '/api/scenario-record/measure', req),
  // resource monitoring (docs/design/resources.md)
  resources: () => request<ResourceSnapshot>('GET', '/api/resources'),
  resourceHistory: (node: string) =>
    request<NodeHistoryResponse>('GET', `/api/resources/history?node=${encodeURIComponent(node)}`),
};

/** `/ns/talker` -> `/api/nodes/ns/talker` (segments encoded). */
export function nodePath(node: string): string {
  return `/api/nodes/${node.split('/').filter(Boolean).map(enc).join('/')}`;
}

function enc(value: string): string {
  return encodeURIComponent(value);
}
