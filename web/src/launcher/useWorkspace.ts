// Workspace packages (GET /api/workspace), shared by the Launcher tab and the map menus.

import { useCallback, useEffect, useState } from 'react';
import { api, describeError } from '../api/client';
import type { WorkspaceInfo } from '../api/types';

export interface WorkspaceState {
  info: WorkspaceInfo | null;
  error: string | null;
  reload: (refresh: boolean) => void;
}

export function useWorkspace(): WorkspaceState {
  const [info, setInfo] = useState<WorkspaceInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback((refresh: boolean) => {
    (refresh ? api.refreshWorkspace() : api.workspace())
      .then((ws) => {
        setInfo(ws);
        setError(null);
      })
      .catch((err: unknown) => setError(describeError(err)));
  }, []);
  useEffect(() => reload(false), [reload]);
  return { info, error, reload };
}
