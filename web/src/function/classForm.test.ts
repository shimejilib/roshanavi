import { describe, expect, it } from 'vitest';
import type { ClassInfo, ClassInitParam, ClassMethodInfo } from '../api/classTypes';
import {
  applyClass, buildClassSpec, defaultClassForm, formFromClass, paramText, parameterArgs, renameNode, setDict, setMethodCall, setMethodUse, snakeCase, updateMethod,
  type ClassForm,
} from './classForm';

const method = (over: Partial<ClassMethodInfo>): ClassMethodInfo => ({
  name: 'process', line: 3, signature: 'process(x: float) -> float', required: 1, varargs: false, returns: 'float', returns_kind: 'float', action_candidate: false, doc: '',
  params: [{ name: 'x', annotation: 'float', kind: 'float', optional: false }], ...over,
});
const param = (over: Partial<ClassInitParam>): ClassInitParam => ({
  name: 'window', annotation: 'int', has_default: true, default: 5, default_text: '5', kind: 'int', ...over,
});
const movingAverage: ClassInfo = {
  name: 'MovingAverage', line: 10, signature: 'MovingAverage(window: int = 5)', doc: '',
  init_params: [param({})],
  methods: [method({}), method({ name: 'reset', signature: 'reset() -> None', required: 0, params: [], returns: 'None', returns_kind: null, action_candidate: true })],
  hooks: { close: false, shutdown: false, get_state: true, set_state: true, on_param_change: true },
};

const ready = (patch: Partial<ClassForm> = {}): ClassForm => ({
  ...applyClass({ ...defaultClassForm(), module: 'roshanavi_examples.stateful' }, movingAverage, false),
  ...patch,
});
const withInput = (form: ClassForm, topic: string, kind: 'float' | 'string' = 'float'): ClassForm =>
  updateMethod(form, 'process', { inputs: [{ topic, kind, type: '' }] });

describe('class node form', () => {
  it('names the node after the class and suggests a first guess for each method', () => {
    expect(snakeCase('MovingAverage')).toBe('moving_average');
    expect(snakeCase('HTTPServer')).toBe('http_server');
    expect(snakeCase('2Fast')).toBe('_2_fast');
    const form = ready();
    expect(form).toMatchObject({ className: 'MovingAverage', name: 'moving_average', params: { window: '5' } });
    const process = form.methods.find((m) => m.method === 'process');
    const reset = form.methods.find((m) => m.method === 'reset');
    expect(process).toMatchObject({ use: 'topic', call: 'on_message', outputs: [{ topic: '/moving_average_out', kind: 'float' }] });
    expect(process?.inputs).toEqual([{ topic: '', kind: 'float', type: '' }]);
    expect(reset).toMatchObject({ use: 'action' });
  });

  it('moves the suggested output topic along when the node is renamed, but not one the user typed', () => {
    const form = renameNode(ready(), 'my_avg');
    expect(form.name).toBe('my_avg');
    expect(form.methods.find((m) => m.method === 'process')?.outputs[0]?.topic).toBe('/my_avg_out');
    const typed = renameNode(updateMethod(ready(), 'process', { outputs: [{ topic: '/mine', kind: 'float', type: '', key: '' }] }), 'other');
    expect(typed.methods.find((m) => m.method === 'process')?.outputs[0]?.topic).toBe('/mine');
    expect(renameNode(ready(), '').name).toBe('');
  });

  it('keeps a name the user typed', () => {
    expect(applyClass({ ...defaultClassForm(), name: 'mine' }, movingAverage, true).name).toBe('mine');
  });

  it('builds the spec: parameters only when changed, methods, actions', () => {
    const built = buildClassSpec(withInput(ready(), '/number'), movingAverage, []);
    expect(built).toEqual({ ok: true, value: {
      id: 'moving_average', name: 'moving_average', module: 'roshanavi_examples.stateful', class_name: 'MovingAverage', params: {},
      methods: [{ method: 'process', call: 'on_message', inputs: [{ topic: '/number', kind: 'float' }], outputs: [{ topic: '/moving_average_out', kind: 'float' }] }],
      actions: ['reset'], autostart: true,
    } });
    const changed = buildClassSpec(withInput(ready({ params: { window: '10' } }), '/number'), movingAverage, ['moving_average']);
    expect(changed.ok && changed.value).toMatchObject({ id: 'moving_average-2', params: { window: 10 } });
  });

  it('checks parameter values by kind and asks for required ones', () => {
    const error = (params: Record<string, string>, info: ClassInfo = movingAverage) => {
      const built = buildClassSpec(withInput(ready({ params }), '/number'), info, []);
      return built.ok ? '' : built.error;
    };
    expect(error({ window: '2.5' })).toContain('整数');
    expect(error({ window: 'abc' })).toContain('window');
    const required = { ...movingAverage, init_params: [param({ has_default: false, default: null, default_text: null })] };
    expect(error({ window: '' }, required)).toContain('必須');
    const mixed: ClassInfo = { ...movingAverage, init_params: [
      param({ name: 'gain', kind: 'float', default: 1.5, default_text: '1.5' }), param({ name: 'on', kind: 'bool', default: false, default_text: 'False' }),
      param({ name: 'gains', kind: 'numbers', default: [1, 2], default_text: '[1, 2]' }), param({ name: 'cfg', kind: 'json', default: {}, default_text: '{}' }),
      param({ name: 'label', kind: 'string', default: 'x', default_text: "'x'" }), param({ name: 'image', kind: null, default: null, default_text: null }),
    ] };
    const text = { gain: '2', on: 'true', gains: '1, 2.5', cfg: '{"a": 1}', label: 'y' };
    const built = buildClassSpec(withInput(ready({ params: text }), '/number'), mixed, []);
    expect(built.ok && built.value.params).toEqual({ gain: 2, on: true, gains: [1, 2.5], cfg: '{"a": 1}', label: 'y' });
    expect(error({ ...text, on: 'yes' }, mixed)).toContain('true か false');
    expect(error({ ...text, cfg: '{oops' }, mixed)).toContain('JSON');
    expect(parameterArgs(mixed).map((p) => p.name)).not.toContain('image');
    expect(paramText(param({ kind: 'json', default: { a: 1 } }))).toBe('{"a":1}');
    expect(paramText(param({ kind: 'numbers', default: [1, 2] }))).toBe('1, 2');
    expect(paramText(param({ default: null }))).toBe('');
  });

  it('explains what is missing in plain words', () => {
    const error = (form: ClassForm) => {
      const built = buildClassSpec(form, movingAverage, []);
      return built.ok ? '' : built.error;
    };
    expect(error(withInput(ready({ name: '1x' }), '/in'))).toContain('ノード名');
    expect(error({ ...withInput(ready(), '/in'), className: '' })).toContain('モジュールとクラス');
    expect(error(ready())).toBe('');                    // an empty input topic = a port wired on the map later
    expect(error(withInput(ready(), 'bad topic'))).toContain('bad topic');      // a malformed name is refused
    expect(error(updateMethod(ready(), 'process', { inputs: [{ topic: '/in', kind: '', type: '' }] }))).toContain('データの種類');
    expect(error(withInput(ready(), '/moving_average_out'))).toContain('同じ');
    const nothing = { ...ready(), methods: ready().methods.map((m) => ({ ...m, use: 'none' as const })) };
    expect(error(nothing)).toContain('1 つ以上');
    expect(error(updateMethod(withInput(ready(), '/in'), 'process', { call: 'periodic', rateHz: '0', inputs: [] }))).toContain('頻度');
  });

  it('lets a method with no output topic through (side effects only)', () => {
    const form = updateMethod(withInput(ready(), '/in'), 'process', { outputs: [{ topic: '', kind: '', type: '', key: '' }] });
    const built = buildClassSpec(form, movingAverage, []);
    expect(built.ok && built.value.methods[0]?.outputs).toEqual([]);
  });

  it('turns on dict output: one row per key, keys checked', () => {
    const base = withInput(ready(), '/in');
    const dict = setDict(base.methods[0]!, true, 'moving_average');
    expect(dict.outputs).toHaveLength(2);
    const filled = updateMethod(base, 'process', {
      ...dict,
      outputs: [{ topic: '/mean', kind: 'float', type: '', key: 'mean' }, { topic: '/count', kind: 'int', type: '', key: 'count' }],
    });
    const built = buildClassSpec(filled, movingAverage, []);
    expect(built.ok && built.value.methods[0]?.outputs).toEqual([{ topic: '/mean', kind: 'float', key: 'mean' }, { topic: '/count', kind: 'int', key: 'count' }]);
    const dup = updateMethod(filled, 'process', { outputs: [{ topic: '/mean', kind: 'float', type: '', key: 'k' }, { topic: '/count', kind: 'int', type: '', key: 'k' }] });
    expect(buildClassSpec(dup, movingAverage, [])).toMatchObject({ ok: false });
    const bad = updateMethod(filled, 'process', { outputs: [{ topic: '/mean', kind: 'float', type: '', key: 'a b' }] });
    expect((buildClassSpec(bad, movingAverage, []) as { error: string }).error).toContain('キー');
    expect(setDict(dict, false, 'x').outputs).toHaveLength(1);
  });

  it('marks and unmarks methods; a bound method gets an output topic', () => {
    let form = ready();
    form = setMethodUse(form, 'reset', 'none');
    expect(form.methods.find((m) => m.method === 'reset')?.use).toBe('none');
    form = setMethodUse(form, 'reset', 'topic', movingAverage);
    const reset = form.methods.find((m) => m.method === 'reset');
    expect(reset).toMatchObject({ use: 'topic', call: 'periodic' });
    expect(reset?.outputs[0]?.topic).toBe('/moving_average_reset_out');
    expect(setMethodCall(reset!, 'multi_input', 3).inputs).toHaveLength(3);
    expect(setMethodCall(reset!, 'on_message', 1).inputs).toHaveLength(1);
  });

  it('round-trips an existing spec', () => {
    const built = buildClassSpec(withInput(ready({ params: { window: '7' } }), '/number'), movingAverage, []);
    if (!built.ok) throw new Error(built.error);
    const form = formFromClass(built.value, movingAverage);
    expect(form).toMatchObject({ name: 'moving_average', className: 'MovingAverage', params: { window: '7' } });
    expect(form.methods.find((m) => m.method === 'process')).toMatchObject({ use: 'topic', inputs: [{ topic: '/number', kind: 'float' }] });
    expect(form.methods.find((m) => m.method === 'reset')?.use).toBe('action');
    const again = buildClassSpec(form, movingAverage, [], built.value.id);
    expect(again).toEqual({ ok: true, value: built.value });
    // before the class listing has loaded, the bound methods still show
    const early = formFromClass(built.value, undefined);
    expect(early.methods.map((m) => m.method)).toEqual(['process']);
  });
});
