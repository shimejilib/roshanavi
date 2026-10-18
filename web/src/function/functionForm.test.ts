import { describe, expect, it } from 'vitest';
import type { FunctionInfo } from '../api/functionTypes';
import { applyFunction, buildFunctionSpec, callModeFor, defaultFunctionForm, formFromFunction, rowsFor, suggestNodeName, type FunctionForm } from './functionForm';

const info = (over: Partial<FunctionInfo> = {}): FunctionInfo => ({
  name: 'shout', line: 3, signature: 'shout(text: str) -> str', required: 1, returns: 'str', returns_kind: 'string', doc: '', varargs: false,
  params: [{ name: 'text', annotation: 'str', kind: 'string', optional: false }], ...over,
});

const ready = (patch: Partial<FunctionForm> = {}): FunctionForm => ({
  ...applyFunction({ ...defaultFunctionForm('/chatter'), module: 'roshanavi_examples.logic' }, info(), false),
  ...patch,
});

describe('function node form', () => {
  it('picks the call mode from the parameters', () => {
    expect(callModeFor({ params: [], required: 0 })).toBe('periodic');
    expect(callModeFor(info())).toBe('on_message');
    const two = info({ required: 2, params: [{ name: 'a', annotation: 'float', kind: 'float', optional: false }, { name: 'b', annotation: null, kind: null, optional: false }] });
    expect(callModeFor(two)).toBe('multi_input');
    const form = applyFunction(defaultFunctionForm('/a'), two, false);
    expect(form.inputs).toEqual([{ topic: '/a', kind: 'float', type: '' }, { topic: '', kind: '', type: '' }]);
  });

  it('fills kinds and names from annotations without overwriting user choices', () => {
    const form = ready();
    expect(form).toMatchObject({ fn: 'shout', name: 'shout', call: 'on_message', output: { topic: '/shout_out', kind: 'string' } });
    expect(form.inputs[0]).toEqual({ topic: '/chatter', kind: 'string', type: '' });
    const kept = applyFunction({ ...form, name: 'mine', output: { topic: '/x', kind: 'json', type: '' } }, info(), true);
    expect(kept.name).toBe('mine');
    expect(kept.output).toEqual({ topic: '/x', kind: 'json', type: '' });
    expect(suggestNodeName('2fast')).toBe('_2fast');
  });

  it('builds the spec for each call mode', () => {
    const built = buildFunctionSpec(ready(), ['shout']);
    expect(built).toEqual({ ok: true, value: expect.objectContaining({
      id: 'shout-2', name: 'shout', module: 'roshanavi_examples.logic', function: 'shout', call: 'on_message',
      inputs: [{ topic: '/chatter', kind: 'string' }], output: { topic: '/shout_out', kind: 'string' },
    }) });
    const periodic = buildFunctionSpec(ready({ call: 'periodic', inputs: [], rateHz: '5' }), []);
    expect(periodic.ok && periodic.value).toMatchObject({ call: 'periodic', inputs: [], rate_hz: 5 });
    const multi = buildFunctionSpec(ready({ call: 'multi_input', trigger: '/b',
      inputs: [{ topic: '/a', kind: 'float', type: '' }, { topic: 'b', kind: 'int', type: 'std_msgs/msg/Int32' }] }), []);
    expect(multi.ok && multi.value).toMatchObject({ trigger: '/b', inputs: [{ topic: '/a', kind: 'float' }, { topic: '/b', kind: 'int', type: 'std_msgs/msg/Int32' }] });
  });

  it('explains what is missing in plain words', () => {
    const error = (patch: Partial<FunctionForm>) => {
      const built = buildFunctionSpec(ready(patch), []);
      return built.ok ? '' : built.error;
    };
    expect(error({ name: '1x' })).toContain('ノード名');
    expect(error({ fn: '' })).toContain('モジュールと関数');
    expect(error({ output: { topic: '/out', kind: '', type: '' } })).toContain('データの種類');
    expect(error({ output: { topic: '/chatter', kind: 'string', type: '' } })).toContain('同じ');
    expect(error({ call: 'periodic', inputs: [], rateHz: '0' })).toContain('頻度');
    expect(error({ call: 'multi_input' })).toContain('2 つ以上');
  });

  it('builds ports that are not wired yet (empty topics: wired on the map later)', () => {
    const built = buildFunctionSpec(ready({ inputs: [{ topic: '', kind: 'string', type: '' }], output: { topic: '', kind: 'string', type: '' } }), []);
    expect(built.ok && [built.value.inputs, built.value.output]).toEqual([[{ topic: '', kind: 'string' }], { topic: '', kind: 'string' }]);
    expect(buildFunctionSpec(ready({ output: { topic: 'a b', kind: 'string', type: '' } }), []).ok).toBe(false);
  });

  it('round-trips an existing spec and resizes rows per call mode', () => {
    const built = buildFunctionSpec(ready(), []);
    if (!built.ok) throw new Error(built.error);
    expect(formFromFunction(built.value)).toMatchObject({ module: 'roshanavi_examples.logic', fn: 'shout', inputs: [{ topic: '/chatter', kind: 'string', type: '' }] });
    expect(rowsFor('periodic', ready().inputs)).toEqual([]);
    expect(rowsFor('multi_input', ready().inputs)).toHaveLength(2);
    expect(rowsFor('on_message', [])).toHaveLength(1);
  });
});
