// Launch takeover (GET /api/takeover), leftover processes and registry delete shapes
// (docs/design/integration.md, docs/design/api.md).

import { request } from './client';

export interface ReportItem {
  code: string;
  nodes?: string[];
  detail?: string;
}

export interface TakeoverReport {
  mode: 'node' | 'whole';
  notes: string[];
  carried: ReportItem[];
  lost: ReportItem[];
  rest: ReportItem[];
  separate: number;
  suggest_whole: boolean;
}

export interface DiffEntry {
  id: string;
  label: string;
  kind: 'node' | 'rest' | 'whole';
  fields?: string[];
}

export interface TakeoverPending {
  preview_id: string;
  reason: 'file_changed' | 'changed_since_last' | 'manual';
  files: string[];
  added: DiffEntry[];
  removed: DiffEntry[];
  changed: DiffEntry[];
  unchanged: DiffEntry[];
  report: TakeoverReport;
}

export interface TakeoverStatus {
  active: boolean;
  state: 'off' | 'starting' | 'ready' | 'error' | 'inactive';
  package: string | null;
  launch_file: string | null;
  args: Record<string, string>;
  mode: 'node' | 'whole' | null;
  mine: string[];
  error: { code: string; message: string } | null;
  report: TakeoverReport | null;
  pending: TakeoverPending | null;
  targets: string[];
  watched: number;
}

export interface ApplyResult {
  added: string[];
  removed: string[];
  changed: string[];
  restarted: string[];
  errors: { id: string; code: string; message: string }[];
  status: TakeoverStatus;
}

export interface LeftoverProcess {
  pid: number;
  pgid: number;
  target: string;
  cmd: string;
}

export interface LeftoverState {
  count: number;
  processes: LeftoverProcess[];
}

export interface LeftoverStopResult {
  stopped: LeftoverProcess[];
  survivors: LeftoverProcess[];
}

export interface DeleteResult {
  removed: { id: string; kind: string; was_running: boolean }[];
  undo_id: string;
  undo_sec: number;
}

export interface UndoResult {
  restored: string[];
  started: string[];
  errors: { id: string; code: string; message: string }[];
}

export const takeoverApi = {
  status: () => request<TakeoverStatus>('GET', '/api/takeover'),
  check: () => request<TakeoverStatus>('POST', '/api/takeover/check'),
  apply: (previewId: string) => request<ApplyResult>('POST', '/api/takeover/apply', { preview_id: previewId }),
  dismiss: (previewId: string) => request<TakeoverStatus>('POST', '/api/takeover/dismiss', { preview_id: previewId }),
  leftovers: () => request<LeftoverState>('GET', '/api/leftovers'),
  stopLeftovers: () => request<LeftoverStopResult>('POST', '/api/leftovers/stop', {}),
  deleteEntries: (ids: string[]) => request<DeleteResult>('POST', '/api/registry/delete', { ids }),
  undoDelete: (undoId: string) => request<UndoResult>('POST', '/api/registry/undo', { undo_id: undoId }),
};
