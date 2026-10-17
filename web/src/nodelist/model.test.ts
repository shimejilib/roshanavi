import { describe, expect, it } from 'vitest';
import type { NodeGroup } from '../api/nodeListTypes';
import { row } from './testRows';
import {
  allState, DEFAULT_FILTER, externalCount, filterRows, pruneSelection, sectionRows, statusBucket, toggleAll, toggleGroup, toggleKey,
} from './model';

const rows = [
  row('/talker'),
  row('/listener', { role: 'dependency', target_id: 'listener', origin: { kind: 'run', package: 'demo_nodes_cpp', executable: 'listener' } }),
  row('target:cam', { name: 'dummy_cam', role: 'dummy', running: false, status: 'stopped', target_id: 'cam', origin: { kind: 'dummy', topic: '/cam' } }),
  row('target:bad', { status: 'invalid', running: false, control: 'none', reason: 'invalid', target_id: 'bad' }),
  row('/external_talker', { role: 'other', target_id: null, control: 'none', reason: 'external', origin: { kind: 'external' } }),
  row('/lc_talker', { role: 'other', target_id: null, control: 'lifecycle', lifecycle: { state: 'active' }, origin: { kind: 'external' } }),
];

describe('node list filters', () => {
  it('filters by role, status and search words', () => {
    expect(filterRows(rows, { ...DEFAULT_FILTER, role: 'other' }).map((r) => r.key)).toEqual(['/external_talker', '/lc_talker']);
    expect(filterRows(rows, { ...DEFAULT_FILTER, status: 'stopped' }).map((r) => r.key)).toEqual(['target:cam']);
    expect(filterRows(rows, { ...DEFAULT_FILTER, status: 'problem' }).map((r) => r.key)).toEqual(['target:bad']);
    expect(filterRows(rows, { ...DEFAULT_FILTER, query: 'LISTENER demo' }).map((r) => r.key)).toEqual(['/listener']);
    expect(filterRows(rows, { ...DEFAULT_FILTER, query: '/cam' }).map((r) => r.key)).toEqual(['target:cam']);
    expect(statusBucket({ status: 'starting', running: false })).toBe('running');
  });
});

describe('selection', () => {
  it('select-all takes only controllable visible rows and toggles off when all are selected', () => {
    const all = toggleAll(rows, new Set());
    expect([...all].sort()).toEqual(['/lc_talker', '/listener', '/talker', 'target:cam']);
    expect(allState(rows, all)).toBe('all');
    expect(allState(rows, new Set(['/talker']))).toBe('some');
    expect(toggleAll(rows, all).size).toBe(0);
    expect(toggleKey(new Set(['/talker']), '/talker').size).toBe(0);
  });

  it('prunes keys that vanished or became uncontrollable', () => {
    expect([...pruneSelection(new Set(['/talker', '/gone', '/external_talker']), rows)]).toEqual(['/talker']);
  });

  it('counts external rows for the import hint', () => {
    expect(externalCount(rows)).toBe(1);
  });
});

describe('grouping', () => {
  const group: NodeGroup = { id: 'pair', kind: 'launch', label: 'pair.launch.py', target_id: 'pair', nodes: ['/a', '/b'], status: 'running' };
  const grouped = [row('/a', { group: 'pair', target_id: 'pair' }), row('/b', { group: 'pair', target_id: 'pair' }), row('/c'), row('/d')];

  it('puts each group under one header and keeps ungrouped rows together', () => {
    const sections = sectionRows(grouped, [group]);
    expect(sections.map((s) => [s.group?.id ?? null, s.rows.map((r) => r.key)])).toEqual([
      ['pair', ['/a', '/b']],
      [null, ['/c', '/d']],
    ]);
  });

  it('selects a whole group at once', () => {
    expect([...toggleGroup(grouped, 'pair', new Set())].sort()).toEqual(['/a', '/b']);
    expect(toggleGroup(grouped, 'pair', new Set(['/a', '/b'])).size).toBe(0);
  });
});
