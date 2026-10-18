import { describe, expect, it } from 'vitest';
import { flowStep, initialFlow, wireOptions, type FlowResult, type FlowState } from './keyboard';
import { allInputs, allOutputs, buildNodePorts } from './ports';
import { ARGS, CATALOG, graph, targets } from './testFixtures';

const all = targets();
const nodes = buildNodePorts(all, graph(), ARGS);
const shout = nodes.find((n) => n.name === 'shout')!;
const shoutTarget = all.find((x) => x.id === 'shout')!;
const topics = graph().topics;

const asState = (r: FlowResult): FlowState => {
  if (r === 'cancel' || 'done' in r) throw new Error('flow ended');
  return r;
};

describe('wiring options (the list the keyboard path shows)', () => {
  it('lists every channel; incompatible ones are disabled with the reason, last', () => {
    const options = wireOptions(shout, allInputs(shout)[0]!, shoutTarget, topics, CATALOG);
    const chatter = options.find((o) => o.label === '/chatter')!;
    const image = options.find((o) => o.label === '/image')!;
    expect(chatter.disabled).toBe(false);
    expect(image).toMatchObject({ disabled: true, status: 'refuse', detail: '文字列の入力口に、画像のチャンネル (トピック) はつなげません' });
    expect(options.indexOf(chatter)).toBeLessThan(options.indexOf(image));
    expect(options.some((o) => o.choice.kind === 'new')).toBe(false); // inputs do not create channels
  });

  it('offers a new channel first for an output port, and taking the wire off when wired', () => {
    const add = nodes.find((n) => n.name === 'add')!;
    const options = wireOptions(add, allOutputs(add)[0]!, all.find((x) => x.id === 'add')!, topics, CATALOG);
    expect(options[0]).toMatchObject({ choice: { kind: 'new', topic: '/add/out' } });
    expect(options.at(-1)).toMatchObject({ choice: { kind: 'disconnect' } });
    expect(options.find((o) => o.label === '/sum')).toMatchObject({ current: true, disabled: true });
  });
});

describe('keyboard flow: select port -> choose -> confirm', () => {
  const options = wireOptions(shout, allInputs(shout)[0]!, shoutTarget, topics, CATALOG);

  it('moves over the enabled options only, then confirms with Enter', () => {
    let state = initialFlow(options);
    expect(options[state.focus]!.disabled).toBe(false);
    const enabled = options.filter((o) => !o.disabled).length;
    for (let i = 0; i < options.length + 2; i += 1) state = asState(flowStep(state, { type: 'key', key: 'ArrowDown' }, options));
    expect(options[state.focus]!.disabled).toBe(false); // never parks on a disabled option
    state = asState(flowStep(state, { type: 'key', key: 'Home' }, options));
    expect(state.focus).toBe(options.findIndex((o) => !o.disabled));
    const target = options.findIndex((o) => o.label === '/chatter');
    while (state.focus !== target) state = asState(flowStep(state, { type: 'key', key: 'ArrowDown' }, options));
    state = asState(flowStep(state, { type: 'key', key: 'Enter' }, options));
    expect(state.step).toBe('confirm');
    expect(flowStep(state, { type: 'key', key: 'Enter' }, options)).toEqual({ done: { kind: 'topic', topic: '/chatter' } });
    expect(enabled).toBeGreaterThan(0);
  });

  it('Escape goes back from confirm, and closes from the list', () => {
    let state = asState(flowStep(initialFlow(options), { type: 'key', key: 'Enter' }, options));
    state = asState(flowStep(state, { type: 'key', key: 'Escape' }, options));
    expect(state.step).toBe('choose');
    expect(flowStep(state, { type: 'key', key: 'Escape' }, options)).toBe('cancel');
  });

  it('a disabled option cannot be picked, even by click', () => {
    const image = options.findIndex((o) => o.label === '/image');
    expect(flowStep(initialFlow(options), { type: 'pick', index: image }, options)).toEqual(initialFlow(options));
  });

  it('a new channel takes the edited name', () => {
    const out = wireOptions(shout, allOutputs(shout)[0]!, shoutTarget, topics, CATALOG);
    let state = initialFlow(out);
    expect(state.newName).toBe('/shout/out');
    state = asState(flowStep(state, { type: 'key', key: 'Enter' }, out));
    state = asState(flowStep(state, { type: 'rename', name: ' /loud ' }, out));
    expect(flowStep(state, { type: 'key', key: 'Enter' }, out)).toEqual({ done: { kind: 'new', topic: '/loud' } });
  });
});
