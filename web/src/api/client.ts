// REST client. Every failure becomes an ApiError with the server's error code.

import { t, tDynamic } from '../i18n';
import type {
  BuildStatus,
  DataFile,
  DummySpec,
  ExportResult,
  InjectRequest,
  Job,
  LogLine,
  ProjectState,
  Target,
  TargetSpec,
  WorkspaceInfo,
} from './types';

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

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
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
  template: (path: string) => request<{ type: string; template: Record<string, unknown> }>('GET', path),
  files: () => request<{ data_dir: string; files: DataFile[] }>('GET', '/api/files'),
  startInject: (req: InjectRequest) => request<Job>('POST', '/api/inject', req),
  stopInject: (id: string) => request<Job>('DELETE', `/api/inject/${encodeURIComponent(id)}`),
  setMonitor: (topicApiPath: string, enabled: boolean) =>
    request<{ topic: string; enabled: boolean }>('PUT', topicApiPath, { enabled }),

  workspace: () => request<WorkspaceInfo>('GET', '/api/workspace'),
  refreshWorkspace: () => request<WorkspaceInfo>('POST', '/api/workspace/refresh'),
  targets: () => request<{ targets: Target[] }>('GET', '/api/targets').then((r) => r.targets),
  addTarget: (spec: TargetSpec) => request<Target>('POST', '/api/targets', spec),
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
  exportDummies: (directory: string, ids: string[] = []) =>
    request<ExportResult>('POST', '/api/dummies/export', { directory, ids }),
};

function enc(value: string): string {
  return encodeURIComponent(value);
}
