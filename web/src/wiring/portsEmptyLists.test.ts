// A sink-only method (no outputs), a periodic source (no inputs), and specs that arrive without
// their empty lists at all must still give ports (the map used to crash on `undefined.map`).

import { describe, expect, it } from 'vitest';
import type { ClassSpec } from '../api/classTypes';
import type { FunctionSpec } from '../api/functionTypes';
import type { TransformSpec } from '../api/transformTypes';
import type { GraphSnapshot } from '../api/types';
import { argNamesFrom } from './useArgNames';
import { planConnect } from './edit';
import { allInputs, allOutputs, buildNodePorts } from './ports';
import { CATALOG, graph, target } from './testFixtures';

const CANVAS: ClassSpec = {
  id: 'canvas', name: 'canvas', module: 'turtle_viz', class_name: 'TrajectoryCanvas', params: {},
  methods: [
    { method: 'on_pose', call: 'on_message', inputs: [{ topic: '', kind: 'message', type: 'turtlesim/msg/Pose' }], outputs: [] },
    { method: 'render', call: 'periodic', rate_hz: 10, inputs: [], outputs: [{ topic: '/turtle_viz/image', kind: 'image' }] },
  ],
  actions: ['reset'],
};

const TICK: FunctionSpec = {
  id: 'tick', name: 'tick', module: 'm', function: 'tick', call: 'periodic', rate_hz: 1,
  inputs: [], output: { topic: '/tick', kind: 'float' },
};

const g = (...ids: string[]): GraphSnapshot => ({
  ...graph(),
  nodes: ids.map((id) => ({ id: `/${id}`, name: id, namespace: '/', role: 'function' as const, target_id: id })),
});

/** What an old server sent: empty lists and maps dropped. */
const stripped = <T extends object>(spec: T, keys: string[]): T => {
  const copy = { ...spec } as Record<string, unknown>;
  for (const key of keys) delete copy[key];
  return copy as T;
};

describe('ports of methods without inputs or outputs', () => {
  const nodes = buildNodePorts([target('class', CANVAS)], g('canvas'));
  const canvas = nodes[0]!;

  it('shows the sink method with inputs only and the periodic source with outputs only', () => {
    expect(canvas.groups.map((grp) => [grp.method, grp.inputs.length, grp.outputs.length])).toEqual([['on_pose', 1, 0], ['render', 0, 1]]);
    expect(allInputs(canvas).map((p) => [p.method, p.kind])).toEqual([['on_pose', 'message']]);
    expect(allOutputs(canvas).map((p) => [p.method, p.kind, p.topic])).toEqual([['render', 'image', '/turtle_viz/image']]);
    expect(canvas.actions).toEqual(['reset']);
  });

  it('does not crash when the lists are missing from the spec', () => {
    const lean: ClassSpec = {
      ...CANVAS,
      methods: [
        stripped(CANVAS.methods[0]!, ['outputs']),
        stripped(CANVAS.methods[1]!, ['inputs']),
      ],
    };
    const [np] = buildNodePorts([target('class', lean)], g('canvas'));
    expect(np!.groups.map((grp) => [grp.inputs.length, grp.outputs.length])).toEqual([[1, 0], [0, 1]]);
  });

  it('copes with a class that has no methods and no actions (everything dropped)', () => {
    const bare = stripped(CANVAS, ['methods', 'actions', 'params']);
    const [np] = buildNodePorts([target('class', bare)], g('canvas'));
    expect(np!.groups).toEqual([]);
    expect(np!.actions).toEqual([]);
    expect(argNamesFrom({ functions: [], classes: [] } as never, target('class', bare), 0)).toBeUndefined();
  });

  it('a periodic function without inputs and a transform without a list get ports', () => {
    const [fn] = buildNodePorts([target('function', stripped(TICK, ['inputs']))], g('tick'));
    expect(allInputs(fn!)).toEqual([]);
    expect(allOutputs(fn!).map((p) => p.topic)).toEqual(['/tick']);

    const transform: TransformSpec = { id: 'relay', name: 'relay', inputs: [], output: { topic: '/copy' }, mode: 'map' };
    const [tr] = buildNodePorts([target('transform', stripped(transform, ['inputs']))], {
      ...graph(), nodes: [{ id: '/relay', name: 'relay', namespace: '/', role: 'transform', target_id: 'relay' }],
    });
    expect(allInputs(tr!)).toEqual([]);
  });

  it('wiring the sink input and the source output writes a valid spec', () => {
    const tg = target('class', CANVAS);
    const [np] = buildNodePorts([tg], g('canvas'));
    const sinkIn = allInputs(np!)[0]!;
    const plan = planConnect(np!, sinkIn, tg, '/turtle1/pose', ['turtlesim/msg/Pose'], CATALOG);
    expect(plan.ok).toBe(true);
    const spec = (plan as { spec: ClassSpec }).spec;
    expect(spec.methods[0]!.inputs[0]!.topic).toBe('/turtle1/pose');
    expect(spec.methods[0]!.outputs).toEqual([]);
    expect(spec.methods[1]!.inputs).toEqual([]);

    const lean = target('class', { ...CANVAS, methods: [stripped(CANVAS.methods[0]!, ['outputs']), CANVAS.methods[1]!] });
    const [lnp] = buildNodePorts([lean], g('canvas'));
    expect(planConnect(lnp!, allInputs(lnp!)[0]!, lean, '/turtle1/pose', ['turtlesim/msg/Pose'], CATALOG).ok).toBe(true);
  });
});
