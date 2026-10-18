// Workspace modules and one module's functions (static signatures from the server).

import { useEffect, useState } from 'react';
import { api, describeError } from '../api/client';
import type { ModuleEntry, ModuleInfo } from '../api/functionTypes';

/** The module list of every scope; read again whenever `refreshKey` changes (scope B / C edited,
 * a package was scaffolded). */
export function useFunctionModules(refreshKey = 0): { modules: ModuleEntry[]; error: string | null } {
  const [modules, setModules] = useState<ModuleEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    api
      .functionModules()
      .then((body) => {
        if (cancelled) return;
        setModules(body.modules);
        setError(null);
      })
      .catch((err: unknown) => !cancelled && setError(describeError(err)));
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);
  return { modules, error };
}

export function useModuleInfo(module: string, refreshKey = 0): { info: ModuleInfo | null; error: string | null } {
  const [info, setInfo] = useState<ModuleInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setInfo(null);
    setError(null);
    if (!module) return undefined;
    let cancelled = false;
    api
      .functionModule(module)
      .then((body) => !cancelled && setInfo(body))
      .catch((err: unknown) => !cancelled && setError(describeError(err)));
    return () => {
      cancelled = true;
    };
  }, [module, refreshKey]);
  return { info, error };
}
