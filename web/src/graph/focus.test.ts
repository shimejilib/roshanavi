import { describe, expect, it } from 'vitest';
import { focusSet } from './focus';

// cam -> /img -> filter -> /edges -> viewer ; other -> /x
const EDGES = [
  { id: 'e1', source: 'cam', target: '/img' },
  { id: 'e2', source: '/img', target: 'filter' },
  { id: 'e3', source: 'filter', target: '/edges' },
  { id: 'e4', source: '/edges', target: 'viewer' },
  { id: 'e5', source: 'other', target: '/x' },
];

describe('focusSet', () => {
  it('includes upstream and downstream paths', () => {
    const set = focusSet('filter', EDGES);
    expect([...set].sort()).toEqual(['/edges', '/img', 'cam', 'e1', 'e2', 'e3', 'e4', 'filter', 'viewer'].sort());
    expect(set.has('other')).toBe(false);
  });

  it('handles cycles and isolated vertices', () => {
    const cyclic = [...EDGES, { id: 'e6', source: 'viewer', target: '/img' }];
    expect(focusSet('cam', cyclic).has('e6')).toBe(true);
    expect([...focusSet('lonely', EDGES)]).toEqual(['lonely']);
  });
});
