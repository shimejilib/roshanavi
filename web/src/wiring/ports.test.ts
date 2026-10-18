import { describe, expect, it } from 'vitest';
import { buildElements, portBoxHeight, portBoxWidth, portFraction, type EdgeData } from '../graph/model';
import { allInputs, allOutputs, buildNodePorts, findPort, portLayouts, suggestTopic } from './ports';
import { ARGS, graph, targets } from './testFixtures';

describe('port model', () => {
  const nodes = buildNodePorts(targets(), graph(), ARGS);
  const byName = (name: string) => nodes.find((n) => n.name === name)!;

  it('gives ports only to the nodes roshanavi runs, never to a launcher / external node', () => {
    expect(nodes.map((n) => n.name).sort()).toEqual(['add', 'avg', 'hello', 'relay', 'shout']);
    expect(nodes.every((n) => n.nodeId.startsWith('/'))).toBe(true);
  });

  it('names a function argument port and its return value, with the data kind', () => {
    const shout = byName('shout');
    expect(allInputs(shout).map((p) => [p.label, p.kind, p.topic, p.canUnwire])).toEqual([['text', 'string', '', true]]);
    expect(allOutputs(shout).map((p) => [p.label, p.kind])).toEqual([['戻り値', 'string']]);
  });

  it('groups class ports by method and keeps action methods as buttons', () => {
    const avg = byName('avg');
    expect(avg.groups.map((g) => g.method)).toEqual(['process']);
    expect(avg.groups[0]!.inputs[0]!.label).toBe('x');
    expect(avg.actions).toEqual(['reset']);
  });

  it('transform and input-node ports always have a channel', () => {
    expect(allInputs(byName('relay')).map((p) => [p.label, p.type, p.canUnwire])).toEqual([['msg', 'std_msgs/msg/String', false]]);
    expect(allOutputs(byName('hello')).map((p) => [p.label, p.kind, p.topic])).toEqual([['送る値', 'string', '/hello']]);
  });

  it('falls back to numbered names when the listing has none', () => {
    const plain = buildNodePorts(targets(), graph());
    expect(allInputs(plain.find((n) => n.name === 'add')!).map((p) => p.label)).toEqual(['入力 1', '入力 2']);
  });

  it('skips nodes that are not on the map', () => {
    const g = graph();
    expect(buildNodePorts(targets(), { ...g, nodes: g.nodes.filter((n) => n.id !== '/shout') }, ARGS).map((n) => n.name)).not.toContain('shout');
    expect(buildNodePorts(targets(), null)).toEqual([]);
  });

  it('finds a port by key', () => {
    const key = allInputs(byName('add'))[1]!.key;
    expect(findPort(nodes, key)?.port.label).toBe('b');
    expect(findPort(nodes, 'nope')).toBeNull();
  });

  it('suggests /<node>/<output> for a new channel, and avoids names in use', () => {
    const shout = byName('shout');
    const out = allOutputs(shout)[0]!;
    expect(suggestTopic(shout, out, new Set())).toBe('/shout/out');
    expect(suggestTopic(shout, out, new Set(['/shout/out']))).toBe('/shout/out_2');
    const avg = byName('avg');
    expect(suggestTopic(avg, allOutputs(avg)[0]!, new Set())).toBe('/avg/process');
  });
});

describe('ports on the map model', () => {
  const nodes = buildNodePorts(targets(), graph(), ARGS);
  const slots = portLayouts(nodes);

  it('sizes the box to fit the ports and their labels', () => {
    const add = slots.get('/add')!;
    expect(add.inputs).toEqual(['/a', '/b']);
    expect(portBoxHeight(add)).toBeGreaterThanOrEqual(2 * 14);
    expect(portBoxWidth(add)).toBeGreaterThan(46);
    expect(portFraction(0, 2)).toBeCloseTo(-0.25);
    expect(portFraction(1, 2)).toBeCloseTo(0.25);
  });

  it('ends each edge at its port', () => {
    const g = graph();
    const snap = { ...g, edges: [
      { node: '/add', topic: '/b', dir: 'sub' as const, qos: { reliability: 'RELIABLE', durability: 'VOLATILE', depth: 10 } },
      { node: '/add', topic: '/sum', dir: 'pub' as const, qos: { reliability: 'RELIABLE', durability: 'VOLATILE', depth: 10 } },
      { node: '/talker', topic: '/chatter', dir: 'pub' as const, qos: { reliability: 'RELIABLE', durability: 'VOLATILE', depth: 10 } },
    ] } as unknown as typeof g;
    const edges = buildElements(snap, new Map(), 0, {}, slots).filter((e) => e.group === 'edges').map((e) => e.data as EdgeData);
    const sub = edges.find((e) => e.topic === '/b')!;
    expect(sub.tep).toBe('-50% 25.00%');
    expect(sub.port).toBe(slots.get('/add')!.inputKeys![1]);
    expect(edges.find((e) => e.topic === '/sum')!.sep).toBe('50% 0.00%');
    expect(edges.find((e) => e.topic === '/chatter')!.port).toBeUndefined();
  });
});
