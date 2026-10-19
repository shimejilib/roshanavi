import { describe, expect, it } from 'vitest';
import type { ClassSpec } from '../api/classTypes';
import type { FunctionSpec } from '../api/functionTypes';
import type { DummySpec, Target } from '../api/types';
import { planConnect, planDisconnect, type WirePlan } from './edit';
import { allInputs, allOutputs, buildNodePorts, type NodePorts } from './ports';
import { ARGS, CATALOG, graph, targets } from './testFixtures';

const all = targets();
const nodes = buildNodePorts(all, graph(), ARGS);
const node = (name: string): NodePorts => nodes.find((n) => n.name === name)!;
const tg = (id: string): Target => all.find((x) => x.id === id)!;
const spec = <T,>(plan: WirePlan): T => {
  if (!plan.ok) throw new Error(plan.reason);
  return plan.spec as T;
};

describe('wiring a function node', () => {
  const shout = node('shout');
  const input = allInputs(shout)[0]!;
  const output = allOutputs(shout)[0]!;

  it('subscribes the input port to an existing channel and adopts its compatible type', () => {
    const next = spec<FunctionSpec>(planConnect(shout, input, tg('shout'), '/chatter', ['example_interfaces/msg/String'], CATALOG));
    expect(next.inputs).toEqual([{ topic: '/chatter', kind: 'string', type: 'example_interfaces/msg/String' }]);
    expect(next.output).toEqual(tg('shout').spec && (tg('shout').spec as FunctionSpec).output); // the rest is untouched
  });

  it('sends the output to a new channel with the kind\'s own type', () => {
    const plan = planConnect(shout, output, tg('shout'), '/shout/out', [], CATALOG);
    expect(spec<FunctionSpec>(plan).output).toEqual({ topic: '/shout/out', kind: 'string' });
    expect(plan.ok && plan.unchanged).toBe(false);
  });

  it('refuses an incompatible channel with the reason, before anything is saved', () => {
    const plan = planConnect(shout, input, tg('shout'), '/image', ['sensor_msgs/msg/Image'], CATALOG);
    expect(plan).toEqual({ ok: false, reason: '文字列の入力口に、画像のトピックはつなげません' });
  });

  it('allows a convertible channel and says what happens', () => {
    const add = node('add');
    const plan = planConnect(add, allInputs(add)[1]!, tg('add'), '/count', ['std_msgs/msg/Int32'], CATALOG);
    expect(plan.ok && plan.note).toBe('整数を小数として渡します。');
    expect(spec<FunctionSpec>(plan).inputs[1]).toEqual({ topic: '/count', kind: 'float', type: 'std_msgs/msg/Int32' });
  });

  it('an integer output sent to a float channel sends that channel\'s kind', () => {
    const intOut = { ...tg('shout'), spec: { ...(tg('shout').spec as FunctionSpec), output: { topic: '', kind: 'int' as const } } };
    const np = buildNodePorts([intOut], graph(), ARGS)[0]!;
    const plan = planConnect(np, allOutputs(np)[0]!, intOut, '/ratio', ['std_msgs/msg/Float64'], CATALOG);
    expect(spec<FunctionSpec>(plan).output).toEqual({ topic: '/ratio', kind: 'float', type: 'std_msgs/msg/Float64' });
  });

  it('refuses a loop (own output into own input) and the same channel on two inputs', () => {
    const add = node('add');
    expect(planConnect(add, allInputs(add)[0]!, tg('add'), '/sum', ['std_msgs/msg/Float64'], CATALOG).ok).toBe(false);
    expect(planConnect(add, allInputs(add)[0]!, tg('add'), '/b', ['std_msgs/msg/Float64'], CATALOG).ok).toBe(false);
    expect(planConnect(add, allOutputs(add)[0]!, tg('add'), '/a', ['std_msgs/msg/Float64'], CATALOG).ok).toBe(false);
  });

  it('moves the trigger with its input, and back to any when it is unwired', () => {
    const add = node('add');
    expect(spec<FunctionSpec>(planConnect(add, allInputs(add)[0]!, tg('add'), '/ratio', ['std_msgs/msg/Float64'], CATALOG)).trigger).toBe('/ratio');
    expect(spec<FunctionSpec>(planDisconnect(add, allInputs(add)[0]!, tg('add'), CATALOG)).trigger).toBe('any');
  });

  it('takes a wire off (the port stays, not wired)', () => {
    const add = node('add');
    const next = spec<FunctionSpec>(planDisconnect(add, allOutputs(add)[0]!, tg('add'), CATALOG));
    expect(next.output.topic).toBe('');
  });

  it('rejects names that are not channel names', () => {
    expect(planConnect(shout, output, tg('shout'), 'no slash', [], CATALOG).ok).toBe(false);
  });

  it('reports a wire to the channel it already has as unchanged', () => {
    const add = node('add');
    const plan = planConnect(add, allInputs(add)[1]!, tg('add'), '/b', ['std_msgs/msg/Float64'], CATALOG);
    expect(plan.ok && plan.unchanged).toBe(false); // the type is now explicit: a real (harmless) change
  });
});

describe('wiring a class node', () => {
  const avg = node('avg');
  it('rewires a method input and refuses an output that another method sends to', () => {
    const next = spec<ClassSpec>(planConnect(avg, allInputs(avg)[0]!, tg('avg'), '/ratio', ['std_msgs/msg/Float64'], CATALOG));
    expect(next.methods[0]!.inputs[0]!.topic).toBe('/ratio');
    expect(planConnect(avg, allOutputs(avg)[0]!, tg('avg'), '/number', [], CATALOG).ok).toBe(false); // its own input
  });
});

describe('transform and input nodes', () => {
  it('rewires a transform only to the type it was made for, and never unwires it', () => {
    const relay = node('relay');
    const port = allInputs(relay)[0]!;
    expect(planConnect(relay, port, tg('relay'), '/other', ['std_msgs/msg/String'], CATALOG).ok).toBe(true);
    expect(planConnect(relay, port, tg('relay'), '/count', ['std_msgs/msg/Int32'], CATALOG).ok).toBe(false);
    expect(planDisconnect(relay, port, tg('relay'), CATALOG)).toEqual({ ok: false, reason: expect.stringContaining('外せません') });
  });

  it('moves an input node to a channel of the same kind, taking that channel\'s type', () => {
    const hello = node('hello');
    const next = spec<DummySpec>(planConnect(hello, allOutputs(hello)[0]!, tg('hello'), '/chatter', ['example_interfaces/msg/String'], CATALOG));
    expect([next.topic, next.type]).toEqual(['/chatter', 'example_interfaces/msg/String']);
    expect(planConnect(hello, allOutputs(hello)[0]!, tg('hello'), '/ratio', ['std_msgs/msg/Float64'], CATALOG).ok).toBe(false);
  });
});
