// Log viewer logic (pure): bounded append, filtering, line classification.

import type { LogLine } from '../api/types';

export const MAX_VIEW_LINES = 5000;

/** Append lines newer than the last one we have; keep at most `max`. */
export function mergeLines(prev: LogLine[], incoming: LogLine[], max = MAX_VIEW_LINES): LogLine[] {
  const last = prev.at(-1)?.seq ?? 0;
  const fresh = incoming.filter((line) => line.seq > last);
  if (!fresh.length) return prev;
  const merged = prev.concat(fresh);
  return merged.length > max ? merged.slice(merged.length - max) : merged;
}

export type LineLevel = 'error' | 'warn' | 'info' | 'system';

const ERROR_RE = /\[(ERROR|FATAL)\]|\berror\b:|Traceback|Exception|\bfailed\b/i;
const WARN_RE = /\[WARN(ING)?\]/i;

export function lineLevel(line: LogLine): LineLevel {
  if (line.stream === 'system') return 'system';
  if (ERROR_RE.test(line.text)) return 'error';
  if (WARN_RE.test(line.text)) return 'warn';
  return line.stream === 'stderr' ? 'warn' : 'info';
}

export interface LogFilter {
  query: string;
  problemsOnly: boolean;
}

export function filterLines(lines: LogLine[], filter: LogFilter): LogLine[] {
  const q = filter.query.trim().toLowerCase();
  return lines.filter((line) => {
    if (filter.problemsOnly && line.stream !== 'stderr' && lineLevel(line) !== 'error') return false;
    return !q || line.text.toLowerCase().includes(q);
  });
}
