// How the parameter dialog lists a node's parameters: the node's own settings first (a class
// node in the order of its `__init__` arguments, other nodes alphabetically), and the settings
// ROS adds to every node folded into a collapsed 「ROS の内部のパラメータ」 section.

import type { ParamInfo } from '../api/nodeTypes';

const INTERNAL_NAMES: ReadonlySet<string> = new Set(['use_sim_time', 'start_type_description_service']);
const INTERNAL_PREFIXES: readonly string[] = ['qos_overrides.'];

/** Parameters ROS itself declares on (almost) every node. */
export function isInternalParam(name: string): boolean {
  return INTERNAL_NAMES.has(name) || INTERNAL_PREFIXES.some((prefix) => name.startsWith(prefix));
}

const byName = (a: ParamInfo, b: ParamInfo): number => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0);

export interface ParamLayout {
  /** The node's own settings, in display order. */
  main: ParamInfo[];
  /** ROS-internal settings (folded away), alphabetical. */
  internal: ParamInfo[];
}

/**
 * @param initOrder `__init__` argument names of a class node, in signature order (null/absent
 *   for other nodes). Listed ones come first in that order; any other setting follows alphabetically.
 */
export function arrangeParams(params: readonly ParamInfo[], initOrder?: readonly string[] | null): ParamLayout {
  const rank = new Map((initOrder ?? []).map((name, index) => [name, index] as const));
  const own = params.filter((p) => !isInternalParam(p.name));
  const main = [...own].sort((a, b) => {
    const ra = rank.get(a.name);
    const rb = rank.get(b.name);
    if (ra !== undefined && rb !== undefined) return ra - rb;
    if (ra !== undefined) return -1;
    if (rb !== undefined) return 1;
    return byName(a, b);
  });
  const internal = params.filter((p) => isInternalParam(p.name)).sort(byName);
  return { main, internal };
}
