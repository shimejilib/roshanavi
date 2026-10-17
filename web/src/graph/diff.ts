// Incremental patch between two element lists (pure, unit-tested).

import type { Element } from './model';

export interface ElementPatch {
  added: Element[];
  removed: string[];
  updated: Element[];
  /** True when the layout must be recomputed: nodes/edges were added or removed, or a ROS
   *  node's label gained / lost a line (the resource badge `CPU 12% · 45 MB` appeared). */
  topologyChanged: boolean;
}

function lineCount(el: Element): number {
  return el.group === 'nodes' && el.data.kind === 'node' ? el.data.label.split('\n').length : 0;
}

function sameData(a: Element['data'], b: Element['data']): boolean {
  const ka = Object.keys(a) as (keyof typeof a)[];
  if (ka.length !== Object.keys(b).length) return false;
  return ka.every((k) => a[k] === (b as typeof a)[k]);
}

export function diffElements(prev: ReadonlyMap<string, Element>, next: readonly Element[]): ElementPatch {
  const added: Element[] = [];
  const updated: Element[] = [];
  const nextIds = new Set<string>();
  let labelsResized = false;
  for (const el of next) {
    nextIds.add(el.data.id);
    const old = prev.get(el.data.id);
    if (!old) added.push(el);
    else if (!sameData(old.data, el.data)) {
      updated.push(el);
      labelsResized ||= lineCount(old) !== lineCount(el);
    }
  }
  const removed = [...prev.keys()].filter((id) => !nextIds.has(id));
  return { added, removed, updated, topologyChanged: added.length > 0 || removed.length > 0 || labelsResized };
}

export function indexElements(elements: readonly Element[]): Map<string, Element> {
  return new Map(elements.map((el) => [el.data.id, el]));
}
