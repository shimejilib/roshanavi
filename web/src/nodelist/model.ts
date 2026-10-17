// Node list (ノード一覧) table logic: filters, search, selection and grouping (pure, DESIGN §6.6).

import type { NodeGroup, NodeRow, RowRole } from '../api/nodeListTypes';

export type RoleFilter = 'all' | RowRole;
export type StatusFilter = 'all' | 'running' | 'stopped' | 'problem';

export interface RowFilter {
  role: RoleFilter;
  status: StatusFilter;
  query: string;
}

export const DEFAULT_FILTER: RowFilter = { role: 'all', status: 'all', query: '' };

const PROBLEM_STATUSES = new Set(['crashed', 'invalid']);

export function statusBucket(row: Pick<NodeRow, 'status' | 'running'>): Exclude<StatusFilter, 'all'> {
  if (PROBLEM_STATUSES.has(row.status)) return 'problem';
  return row.running || row.status === 'starting' || row.status === 'running' ? 'running' : 'stopped';
}

function haystack(row: NodeRow): string {
  const o = row.origin;
  return [row.name, row.node, row.target_id, o.package, o.executable, o.launch_file, o.imported_from, o.topic]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
}

export function matchesFilter(row: NodeRow, filter: RowFilter): boolean {
  if (filter.role !== 'all' && row.role !== filter.role) return false;
  if (filter.status !== 'all' && statusBucket(row) !== filter.status) return false;
  const words = filter.query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const text = haystack(row);
  return words.every((w) => text.includes(w));
}

export function filterRows(rows: readonly NodeRow[], filter: RowFilter): NodeRow[] {
  return rows.filter((row) => matchesFilter(row, filter));
}

export function isSelectable(row: Pick<NodeRow, 'control'>): boolean {
  return row.control !== 'none';
}

/** Drop selected keys that are no longer present or controllable (after a refresh). */
export function pruneSelection(selected: ReadonlySet<string>, rows: readonly NodeRow[]): Set<string> {
  const valid = new Set(rows.filter(isSelectable).map((r) => r.key));
  return new Set([...selected].filter((key) => valid.has(key)));
}

export function toggleKey(selected: ReadonlySet<string>, key: string): Set<string> {
  const next = new Set(selected);
  if (next.has(key)) next.delete(key);
  else next.add(key);
  return next;
}

export type AllState = 'none' | 'some' | 'all';

/** State of the header "select all" checkbox for the visible rows. */
export function allState(visible: readonly NodeRow[], selected: ReadonlySet<string>): AllState {
  const keys = visible.filter(isSelectable).map((r) => r.key);
  const count = keys.filter((k) => selected.has(k)).length;
  if (count === 0) return 'none';
  return count === keys.length ? 'all' : 'some';
}

/** Header checkbox: select every visible controllable row, or clear them when all are selected. */
export function toggleAll(visible: readonly NodeRow[], selected: ReadonlySet<string>): Set<string> {
  const keys = visible.filter(isSelectable).map((r) => r.key);
  const next = new Set(selected);
  if (allState(visible, selected) === 'all') keys.forEach((k) => next.delete(k));
  else keys.forEach((k) => next.add(k));
  return next;
}

/** Select / clear every controllable row of one group (they stop together anyway). */
export function toggleGroup(rows: readonly NodeRow[], groupId: string, selected: ReadonlySet<string>): Set<string> {
  return toggleAll(rows.filter((r) => r.group === groupId), selected);
}

export interface RowSection {
  group: NodeGroup | null;
  rows: NodeRow[];
}

/** Consecutive sections: each group's rows under one header, ungrouped rows in between. */
export function sectionRows(rows: readonly NodeRow[], groups: readonly NodeGroup[]): RowSection[] {
  const byId = new Map(groups.map((g) => [g.id, g]));
  const sections: RowSection[] = [];
  const index = new Map<string, RowSection>();
  for (const row of rows) {
    const group = row.group ? (byId.get(row.group) ?? null) : null;
    if (group) {
      const existing = index.get(group.id);
      if (existing) {
        existing.rows.push(row);
        continue;
      }
      const section = { group, rows: [row] };
      index.set(group.id, section);
      sections.push(section);
    } else {
      const last = sections[sections.length - 1];
      if (last && last.group === null) last.rows.push(row);
      else sections.push({ group: null, rows: [row] });
    }
  }
  return sections;
}

/** How many rows are external and not controllable (for the import hint). */
export function externalCount(rows: readonly NodeRow[]): number {
  return rows.filter((r) => r.control === 'none' && r.reason === 'external').length;
}
