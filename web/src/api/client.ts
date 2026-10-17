// REST client. Every failure becomes an ApiError with the server's error code.

import { t, tDynamic } from '../i18n';
import type { DataFile, InjectRequest, Job } from './types';

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
};
