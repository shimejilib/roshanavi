// Traffic table sorting (pure, unit-tested).

import type { TrafficEntry } from '../api/types';

export type SortKey =
  | 'topic'
  | 'type'
  | 'hz'
  | 'bytes_per_sec'
  | 'avg_size'
  | 'jitter_ms'
  | 'drop_ratio'
  | 'latency_ms'
  | 'last_seen';

export interface SortState {
  key: SortKey;
  desc: boolean;
}

/** Nulls always sort last regardless of direction. */
export function sortTraffic(rows: readonly TrafficEntry[], sort: SortState): TrafficEntry[] {
  const sign = sort.desc ? -1 : 1;
  return [...rows].sort((a, b) => {
    const va = a[sort.key];
    const vb = b[sort.key];
    if (va == null && vb == null) return a.topic.localeCompare(b.topic);
    if (va == null) return 1;
    if (vb == null) return -1;
    const cmp = typeof va === 'string' ? va.localeCompare(String(vb)) : (va as number) - (vb as number);
    return cmp !== 0 ? sign * cmp : a.topic.localeCompare(b.topic);
  });
}

export function toggleSort(current: SortState, key: SortKey): SortState {
  if (current.key === key) return { key, desc: !current.desc };
  return { key, desc: key !== 'topic' && key !== 'type' };
}
