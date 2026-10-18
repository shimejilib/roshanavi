// Argument names of the functions / bound methods on the map (from the static listing,
// GET /api/functions/module; the specs only keep topics). Fetched once per module.

import { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import type { ClassSpec } from '../api/classTypes';
import type { FunctionSpec, ModuleInfo } from '../api/functionTypes';
import type { Target } from '../api/types';
import type { ArgNames } from './ports';

/** Pure: names from a module listing (undefined when the listing does not have them). */
export function argNamesFrom(info: ModuleInfo | undefined, target: Target, group: number): string[] | undefined {
  if (!info) return undefined;
  if (target.kind === 'function') {
    const spec = target.spec as FunctionSpec;
    return info.functions.find((f) => f.name === spec.function)?.params.map((p) => p.name);
  }
  if (target.kind === 'class') {
    const spec = target.spec as ClassSpec;
    const method = (spec.methods ?? [])[group]?.method;
    const cls = info.classes?.find((c) => c.name === spec.class_name);
    return cls?.methods.find((m) => m.name === method)?.params.map((p) => p.name);
  }
  return undefined;
}

export function useArgNames(targets: readonly Target[]): ArgNames {
  const modules = useMemo(() => {
    const names = targets
      .filter((tg) => tg.kind === 'function' || tg.kind === 'class')
      .map((tg) => (tg.spec as FunctionSpec | ClassSpec).module);
    return [...new Set(names)].sort().join('\n');
  }, [targets]);
  const [infos, setInfos] = useState<Record<string, ModuleInfo>>({});

  useEffect(() => {
    let cancelled = false;
    const wanted = modules ? modules.split('\n') : [];
    for (const module of wanted) {
      if (infos[module]) continue;
      api.functionModule(module)
        .then((info) => !cancelled && setInfos((prev) => ({ ...prev, [module]: info })))
        .catch(() => undefined); // names fall back to 「入力 1」…; the ports still work
    }
    return () => {
      cancelled = true;
    };
    // `infos` is a cache: fetching again when it changes would loop.
  }, [modules]);

  return useMemo<ArgNames>(
    () => (target, group) => argNamesFrom(infos[(target.spec as FunctionSpec | ClassSpec).module], target, group),
    [infos],
  );
}
