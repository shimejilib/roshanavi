// Polls GET /api/node-list while the tab is visible (and on demand after an action).

import { useCallback, useEffect, useState } from 'react';
import { api, describeError } from '../api/client';
import type { NodeListResponse } from '../api/nodeListTypes';

const POLL_MS = 2000;

export interface NodeListState {
  data: NodeListResponse | null;
  error: string | null;
  reload: () => void;
}

export function useNodeList(active: boolean): NodeListState {
  const [data, setData] = useState<NodeListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(() => {
    api
      .nodeList()
      .then((body) => {
        setData(body);
        setError(null);
      })
      .catch((err: unknown) => setError(describeError(err)));
  }, []);
  useEffect(() => {
    if (!active) return undefined;
    reload();
    const timer = setInterval(reload, POLL_MS);
    return () => clearInterval(timer);
  }, [active, reload]);
  return { data, error, reload };
}
