// GET /api/data-kinds and the grouped type list (GET /api/types), fetched once per page.

import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { EMPTY_CATALOG, type KindCatalog, type TypeGroup } from './kinds';

let kindsPromise: Promise<KindCatalog> | null = null;
let groupsPromise: Promise<TypeGroup[]> | null = null;

export function useDataKinds(): KindCatalog {
  const [catalog, setCatalog] = useState<KindCatalog>(EMPTY_CATALOG);
  useEffect(() => {
    let cancelled = false;
    kindsPromise ??= api.dataKinds();
    kindsPromise
      .then((body) => !cancelled && setCatalog(body))
      .catch(() => {
        kindsPromise = null; // retry next time; the picker stays empty meanwhile
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return catalog;
}

/** Type groups for 詳細設定モード (loaded only when it is on). */
export function useTypeGroups(enabled: boolean): TypeGroup[] {
  const [groups, setGroups] = useState<TypeGroup[]>([]);
  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;
    groupsPromise ??= api.typeCatalog().then((body) => body.groups);
    groupsPromise
      .then((list) => !cancelled && setGroups(list))
      .catch(() => {
        groupsPromise = null;
      });
    return () => {
      cancelled = true;
    };
  }, [enabled]);
  return groups;
}
