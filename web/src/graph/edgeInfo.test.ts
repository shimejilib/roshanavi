import { describe, expect, it } from 'vitest';
import type { GraphSnapshot } from '../api/types';
import { edgeDetails, qosCells } from './edgeInfo';

const reliable = { reliability: 'reliable', durability: 'volatile', depth: 10 };
const graph: GraphSnapshot = {
  nodes: [],
  topics: [{ name: '/scan', types: ['sensor_msgs/msg/LaserScan'] }],
  edges: [
    { node: '/viewer', topic: '/scan', dir: 'sub', qos: reliable },
    { node: '/lidar', topic: '/scan', dir: 'pub', qos: { reliability: 'best_effort', durability: 'volatile', depth: 5 } },
  ],
  diagnostics: [
    { code: 'qos_incompatible', severity: 'error', topic: '/scan', nodes: ['/lidar', '/viewer'], detail: { publisher: '/lidar', subscriber: '/viewer', reasons: [{ policy: 'reliability', pub: 'best_effort', sub: 'reliable' }] } },
  ],
  hash: 'h',
};

describe('edgeDetails', () => {
  it('lists publishers first and explains a QoS mismatch', () => {
    const info = edgeDetails(graph, '/scan', '/viewer', 'sub', undefined);
    expect(info.edge?.node).toBe('/viewer');
    expect(info.endpoints.map((e) => e.dir)).toEqual(['pub', 'sub']);
    expect(info.reasons).toHaveLength(1);
    expect(info.reasons[0]).toContain('BEST_EFFORT');
  });

  it('says when nobody publishes or nothing flows', () => {
    const lonely: GraphSnapshot = { ...graph, edges: [graph.edges[0]!], diagnostics: [] };
    expect(edgeDetails(lonely, '/scan', '/viewer', 'sub', undefined).reasons[0]).toContain('送信しているノードがありません');
    const quiet: GraphSnapshot = { ...graph, diagnostics: [] };
    const entry = { stale: true, total_count: 3 } as never;
    expect(edgeDetails(quiet, '/scan', '/viewer', 'sub', entry).reasons[0]).toContain('流れていません');
    expect(edgeDetails(quiet, '/scan', '/viewer', 'sub', undefined).reasons).toEqual([]);
  });

  it('formats QoS cells', () => {
    expect(qosCells(graph.edges[1]!)).toEqual(['best_effort', 'volatile', '5', '無制限', '—']);
  });
});
