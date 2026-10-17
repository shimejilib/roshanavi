// Upstream / downstream reachability for focus mode (pure, unit-tested).

export interface DirectedEdge {
  id: string;
  source: string;
  target: string;
}

function walk(start: string, edges: readonly DirectedEdge[], forward: boolean, into: Set<string>): void {
  const adjacency = new Map<string, DirectedEdge[]>();
  for (const e of edges) {
    const from = forward ? e.source : e.target;
    adjacency.set(from, [...(adjacency.get(from) ?? []), e]);
  }
  const queue = [start];
  const visited = new Set([start]);
  while (queue.length > 0) {
    const current = queue.shift() as string;
    for (const e of adjacency.get(current) ?? []) {
      into.add(e.id);
      const next = forward ? e.target : e.source;
      if (!visited.has(next)) {
        visited.add(next);
        into.add(next);
        queue.push(next);
      }
    }
  }
}

/** Ids (vertices + edges) on any path into or out of `start`, including `start`. */
export function focusSet(start: string, edges: readonly DirectedEdge[]): Set<string> {
  const result = new Set([start]);
  walk(start, edges, true, result);
  walk(start, edges, false, result);
  return result;
}
