// The path of the project that is open now (keys per-project UI state such as pinned map positions).
// Refetched when the project is switched from ⚙ 設定 (`notifyProjectChanged`).

import { useEffect, useState } from 'react';
import { api } from '../api/client';

const listeners = new Set<() => void>();

export function notifyProjectChanged(): void {
  listeners.forEach((fn) => fn());
}

/** null until known (or when /api/project fails): callers then keep their state in memory only. */
export function useProjectKey(): string | null {
  const [key, setKey] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    const load = () => {
      api.project()
        .then((state) => !cancelled && setKey(state.path))
        .catch(() => undefined);
    };
    load();
    listeners.add(load);
    return () => {
      cancelled = true;
      listeners.delete(load);
    };
  }, []);
  return key;
}
