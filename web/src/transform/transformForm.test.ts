import { describe, expect, it } from 'vitest';
import type { TransformSpec } from '../api/transformTypes';
import { templateToYaml } from '../inject/buildRequest';
import {
  buildTransformSpec,
  defaultTransformForm,
  formFromTransform,
  isHeavy,
  mappingFromTemplate,
  suggestTransformName,
  withInputs,
  type TransformForm,
} from './transformForm';

const STRING = 'std_msgs/msg/String';
const form = (patch: Partial<TransformForm> = {}): TransformForm => ({
  ...defaultTransformForm('/chatter', STRING),
  mappingYaml: 'data: ${upper(msg.data)}\n',
  ...patch,
});

describe('defaults', () => {
  it('starts from the topic: name, output topic, map mode', () => {
    const f = defaultTransformForm('chatter', STRING);
    expect(f.name).toBe('chatter_transform');
    expect(f.inputs).toEqual([{ topic: '/chatter', type: STRING, alias: 'msg' }]);
    expect(f.outputTopic).toBe('/chatter_out');
    expect(f.mode).toBe('map');
    expect(suggestTransformName('/a/1b')).toBe('_1b_transform');
  });

  it('uses relay for heavy types', () => {
    expect(defaultTransformForm('/cam', 'sensor_msgs/msg/Image').mode).toBe('relay');
    expect(isHeavy('sensor_msgs/msg/PointCloud2')).toBe(true);
    expect(isHeavy(STRING)).toBe(false);
  });

  it('builds a starting mapping from the output template, reading matching input fields', () => {
    const out = { linear: { x: 0, y: 0 }, angular: { z: 0 }, extra: [] };
    const input = { linear: { x: 0, y: 0 }, angular: { z: 0 } };
    expect(mappingFromTemplate(out, input, 'msg')).toEqual({
      linear: { x: '${msg.linear.x}', y: '${msg.linear.y}' },
      angular: { z: '${msg.angular.z}' },
      extra: [],
    });
    expect(mappingFromTemplate({ data: 0 }, { data: '' }, 'src')).toEqual({ data: '${src.data}' });
    expect(mappingFromTemplate({ data: 0 }, null, 'msg')).toEqual({ data: 0 });
  });
});

describe('buildTransformSpec', () => {
  it('builds a map spec with condition and timing', () => {
    const built = buildTransformSpec(form({ condition: " msg.data != '' ", delayMinMs: '100', delayMaxMs: '300', throttleHz: '5', dropPercent: '10' }), []);
    expect(built.ok).toBe(true);
    if (!built.ok) return;
    const spec = built.value;
    expect(spec.id).toBe('chatter_transform');
    expect(spec.mapping).toEqual({ data: '${upper(msg.data)}' });
    expect(spec.condition).toBe("msg.data != ''");
    expect(spec.output).toMatchObject({ topic: '/chatter_out', type: STRING });
    expect(spec.delay).toEqual({ min_ms: 100, max_ms: 300 });
    expect(spec.throttle_hz).toBe(5);
    expect(spec.drop_ratio).toBeCloseTo(0.1);
    expect(spec.trigger).toBe('any');
  });

  it('fixed delay when max is empty or equal', () => {
    const built = buildTransformSpec(form({ delayMinMs: '250' }), []);
    expect(built.ok && built.value.delay).toEqual({ min_ms: 250 });
  });

  it('relay drops mapping and output type', () => {
    const built = buildTransformSpec(form({ mode: 'relay', condition: 'x' }), ['chatter_transform']);
    expect(built.ok).toBe(true);
    if (!built.ok) return;
    expect(built.value.id).toBe('chatter_transform-2');
    expect(built.value.mapping).toBeUndefined();
    expect(built.value.condition).toBeUndefined();
    expect(built.value.output.type).toBeUndefined();
  });

  it.each([
    [{ name: '1bad' }, 'ノード名'],
    [{ outputTopic: '/chatter' }, '入力トピックと同じ'],
    [{ outputTopic: 'bad topic' }, '出力トピック'],
    [{ outputType: 'nope' }, '出力の型'],
    [{ inputs: [{ topic: '/a', type: STRING, alias: 'now' }] }, '予約語'],
    [{ inputs: [{ topic: '/a', type: '', alias: 'msg' }] }, '型を指定'],
    [{ inputs: [{ topic: '/img', type: 'sensor_msgs/msg/Image', alias: 'msg' }] }, '大きい型'],
    [{ delayMinMs: '50', delayMaxMs: '10' }, '遅延'],
    [{ throttleHz: '0' }, '間引き'],
    [{ dropPercent: '150' }, '取りこぼし'],
    [{ mappingYaml: 'a: [' }, 'YAML'],
  ])('rejects %o with a plain message', (patch, needle) => {
    const built = buildTransformSpec(form(patch as Partial<TransformForm>), []);
    expect(built.ok).toBe(false);
    if (!built.ok) expect(built.error).toContain(needle);
  });

  it('lenient mode (preview) accepts an unfinished name', () => {
    expect(buildTransformSpec(form({ name: '' }), [], undefined, true).ok).toBe(true);
    expect(buildTransformSpec(form({ name: '' }), []).ok).toBe(false);
  });

  it('multi-input needs a mapping and keeps a valid trigger', () => {
    const multi = withInputs(form(), [...form().inputs, { topic: '/b', type: STRING, alias: 'msg2' }]);
    expect(multi.inputs.map((row) => row.alias)).toEqual(['msg1', 'msg2']);
    expect(buildTransformSpec({ ...multi, mappingYaml: '' }, []).ok).toBe(false);
    const built = buildTransformSpec({ ...multi, trigger: 'msg2', mappingYaml: 'data: ${msg1.data + msg2.data}' }, []);
    expect(built.ok && built.value.trigger).toBe('msg2');
    const single = withInputs({ ...multi, trigger: 'msg2' }, multi.inputs.slice(0, 1));
    expect(single.inputs[0]?.alias).toBe('msg');
    expect(single.trigger).toBe('any');
  });
});

describe('formFromTransform', () => {
  it('round-trips a spec', () => {
    const spec: TransformSpec = {
      id: 'tf', name: 'tf', mode: 'map', inputs: [{ topic: '/a', type: STRING, alias: 'msg' }],
      output: { topic: '/b', type: STRING }, mapping: { data: '${lower(msg.data)}' }, condition: 'len(msg.data) > 0',
      delay: { min_ms: 10, max_ms: 20 }, throttle_hz: 2, drop_ratio: 0.25, autostart: true,
    };
    const f = formFromTransform(spec, templateToYaml);
    expect(f.dropPercent).toBe('25');
    const rebuilt = buildTransformSpec(f, [], 'tf');
    expect(rebuilt.ok && rebuilt.value).toMatchObject({ mapping: spec.mapping, condition: spec.condition, delay: spec.delay, throttle_hz: 2, drop_ratio: 0.25 });
  });
});
