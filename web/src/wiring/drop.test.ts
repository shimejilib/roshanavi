import { describe, expect, it } from 'vitest';
import { dropOutcome, notesOf, refusalOf, type DropContext } from './drop';
import { allInputs, allOutputs, buildNodePorts } from './ports';
import { ARGS, CATALOG, graph, targets } from './testFixtures';

const all = targets();
const nodes = buildNodePorts(all, graph(), ARGS);
const ctx: DropContext = { nodes, targets: all, topics: graph().topics, catalog: CATALOG };
const shout = nodes.find((n) => n.name === 'shout')!;
const avg = nodes.find((n) => n.name === 'avg')!;
const inKey = allInputs(shout)[0]!.key;
const outKey = allOutputs(shout)[0]!.key;

describe('dropping a wire', () => {
  it('connects a port dropped on a channel', () => {
    const outcome = dropOutcome(ctx, { kind: 'port', key: inKey }, { kind: 'topic', topic: '/chatter' });
    expect(outcome.kind).toBe('steps');
    expect(refusalOf(outcome)).toBe('');
  });

  it('asks for a name when an output is dropped on a blank part (suggesting /<node>/<output>)', () => {
    expect(dropOutcome(ctx, { kind: 'port', key: outKey }, { kind: 'blank' })).toEqual({ kind: 'ask', port: outKey, suggestion: '/shout/out' });
  });

  it('an input dropped on a blank part, or on a node, explains what to do', () => {
    expect(refusalOf(dropOutcome(ctx, { kind: 'port', key: inKey }, { kind: 'blank' }))).toContain('楕円');
    expect(refusalOf(dropOutcome(ctx, { kind: 'port', key: inKey }, { kind: 'node', nodeId: '/talker' }))).toContain('コードの中で決まっている');
    expect(refusalOf(dropOutcome(ctx, { kind: 'port', key: inKey }, { kind: 'node', nodeId: '/avg' }))).toContain('小さな丸');
  });

  it('a channel handle dropped on an input port subscribes it', () => {
    const outcome = dropOutcome(ctx, { kind: 'topic', topic: '/chatter' }, { kind: 'port', key: inKey });
    expect(outcome.kind === 'steps' && outcome.steps[0]!.topic).toBe('/chatter');
  });

  it('output to input port goes through a new channel named after the output', () => {
    const outcome = dropOutcome(ctx, { kind: 'port', key: outKey }, { kind: 'port', key: allInputs(avg)[0]!.key });
    // shout returns 文字列, avg.process takes 数値 (小数): refused with the reason.
    expect(refusalOf(outcome)).toContain('つなげません');
    const add = nodes.find((n) => n.name === 'add')!;
    const ok = dropOutcome(ctx, { kind: 'port', key: allOutputs(add)[0]!.key }, { kind: 'port', key: allInputs(avg)[0]!.key });
    expect(ok.kind === 'steps' && ok.steps.map((s) => s.topic)).toEqual(['/sum']); // add already sends to /sum
    expect(notesOf(ok)).toBe('');
  });

  it('refuses port pairs on the same side', () => {
    expect(refusalOf(dropOutcome(ctx, { kind: 'port', key: inKey }, { kind: 'port', key: allInputs(avg)[0]!.key }))).toContain('入力口と出力口');
  });
});
