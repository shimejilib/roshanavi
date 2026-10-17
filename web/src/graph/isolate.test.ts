import { describe, expect, it } from 'vitest';
import type { GraphSnapshot } from '../api/types';
import { isolateSnapshot } from './isolate';

const qos = { reliability: 'reliable', durability: 'volatile' };
const snap: GraphSnapshot = {
  nodes: ['/cam', '/filter', '/detector', '/other'].map((id) => ({ id, name: id.slice(1), namespace: '/', role: 'other' })),
  topics: ['/image', '/edges', '/boxes', '/unrelated'].map((name) => ({ name, types: ['x/msg/Y'] })),
  edges: [
    { node: '/cam', topic: '/image', dir: 'pub', qos },
    { node: '/filter', topic: '/image', dir: 'sub', qos },
    { node: '/filter', topic: '/edges', dir: 'pub', qos },
    { node: '/detector', topic: '/edges', dir: 'sub', qos },
    { node: '/detector', topic: '/boxes', dir: 'pub', qos },
    { node: '/other', topic: '/unrelated', dir: 'pub', qos },
  ],
  diagnostics: [],
  hash: 'h',
};

describe('isolateSnapshot', () => {
  it('returns the snapshot unchanged without isolation', () => {
    expect(isolateSnapshot(snap, null)).toBe(snap);
  });

  it('keeps only a node and its direct topics (io)', () => {
    const out = isolateSnapshot(snap, { mode: 'io', elementId: 'n:/filter' });
    expect(out.nodes.map((n) => n.id)).toEqual(['/filter']);
    expect(out.topics.map((tp) => tp.name).sort()).toEqual(['/edges', '/image']);
    expect(out.edges).toHaveLength(2);
  });

  it('keeps everything upstream and downstream of a topic (flow)', () => {
    const out = isolateSnapshot(snap, { mode: 'flow', elementId: 't:/edges' });
    expect(out.nodes.map((n) => n.id).sort()).toEqual(['/cam', '/detector', '/filter']);
    expect(out.topics.map((tp) => tp.name)).not.toContain('/unrelated');
    expect(out.edges).toHaveLength(5);
  });
});
