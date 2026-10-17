// Workspace modules and one module's functions (static signatures from the server).

import { useEffect, useState } from 'react';
import { api, describeError } from '../api/client';
import type { ModuleEntry, ModuleInfo } from '../api/functionTypes';

export function useFunctionModules(): { modules: ModuleEntry[]; error: string | null } {
  const [modules, setModules] = useState<ModuleEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    api
      .functionModules()
      .then((body) => !cancelled && setModules(body.modules))
      .catch((err: unknown) => !cancelled && setError(describeError(err)));
    return () => {
      cancelled = true;
    };
  }, []);
  return { modules, error };
}

export function useModuleInfo(module: string): { info: ModuleInfo | null; error: string | null } {
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
  }, [module]);
  return { info, error };
}
