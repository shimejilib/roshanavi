import { describe, expect, it } from 'vitest';
import type { GraphSnapshot } from '../api/types';
import { initialOpen, nodeIo } from './nodeIO';

const qos = { reliability: 'reliable', durability: 'volatile' };
const graph: GraphSnapshot = {
  nodes: [{ id: '/n', name: 'n', namespace: '/', role: 'mine' }],
  topics: [
    { name: '/cam', types: ['sensor_msgs/msg/Image'] },
    { name: '/cmd', types: ['std_msgs/msg/String'] },
    { name: '/a', types: ['std_msgs/msg/String'] },
    { name: '/b', types: ['std_msgs/msg/String'] },
    { name: '/c', types: ['std_msgs/msg/String'] },
  ],
  edges: [
    { node: '/n', topic: '/cam', dir: 'sub', qos },
    { node: '/n', topic: '/cmd', dir: 'sub', qos },
    { node: '/n', topic: '/rosout', dir: 'pub', qos },
    { node: '/n', topic: '/parameter_events', dir: 'sub', qos },
    { node: '/n', topic: '/c', dir: 'pub', qos },
    { node: '/n', topic: '/a', dir: 'pub', qos },
    { node: '/n', topic: '/b', dir: 'pub', qos },
    { node: '/other', topic: '/cmd', dir: 'pub', qos },
  ],
  diagnostics: [
    { code: 'qos_incompatible', severity: 'error', topic: '/cmd', nodes: ['/other', '/n'], detail: { publisher: '/other', subscriber: '/n', reasons: [] } },
  ],
  hash: 'h',
};

describe('nodeIo', () => {
  const io = nodeIo(graph, '/n', new Map());

  it('splits inputs and outputs and hides infrastructure topics', () => {
    expect(io.inputs.map((i) => i.topic)).toEqual(['/cam', '/cmd']);
    expect(io.outputs.map((i) => i.topic)).toEqual(['/a', '/b', '/c']);
  });

  it('flags heavy types and QoS-blocked subscriptions', () => {
    expect(io.inputs.find((i) => i.topic === '/cam')?.heavy).toBe(true);
    expect(io.inputs.find((i) => i.topic === '/cmd')?.blocked).toBe(true);
    expect(io.outputs.every((i) => !i.blocked)).toBe(true);
  });

  it('opens the first three light, deliverable topics only', () => {
    expect([...initialOpen(io)]).toEqual(['pub:/a', 'pub:/b', 'pub:/c']);
  });

  it('is empty without a graph', () => {
    expect(nodeIo(null, '/n', new Map())).toEqual({ inputs: [], outputs: [] });
  });
});
