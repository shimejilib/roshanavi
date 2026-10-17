import { describe, expect, it } from 'vitest';
import type { RecordEvent } from '../api/scenarioTypes';
import {
  buildSteps,
  conditionsFrom,
  defaultName,
  type Expectation,
  isVolatilePath,
  lastOpBefore,
  numberedPattern,
  OpConverter,
  pickFields,
  shortValue,
  suggestLatencyMs,
  suggestRate,
  suggestRatio,
  withinFor,
} from './record';

const byPath = (choices: ReturnType<typeof pickFields>) => Object.fromEntries(choices.map((c) => [c.path, c]));

describe('pickFields', () => {
  it('scalars eq, floats approx, stamps and counters unchecked', () => {
    const msg = {
      header: { stamp: { sec: 5, nanosec: 7 }, frame_id: 'cam' },
      count: 12,
      state: 'RUNNING',
      ok: true,
      level: 3,
      gain: 0.25,
    };
    const c = byPath(pickFields(msg));
    expect(c['header.stamp.sec']).toMatchObject({ checked: false, reason: 'volatile' });
    expect(c['header.stamp.nanosec']?.checked).toBe(false);
    expect(c['header.frame_id']).toMatchObject({ op: 'eq', value: 'cam', checked: true });
    expect(c.count).toMatchObject({ checked: false, reason: 'volatile' });
    expect(c.state).toMatchObject({ op: 'eq', value: 'RUNNING', checked: true });
    expect(c.ok).toMatchObject({ op: 'eq', value: true, checked: true });
    expect(c.level).toMatchObject({ op: 'eq', checked: true });
    expect(c.gain).toMatchObject({ op: 'approx', checked: true });
    expect(c.gain?.tol).toBeCloseTo(0.0025);
  });

  it('fields that change between messages are unchecked; numbered strings become a regex', () => {
    const msg = { data: 'Hello World: 12', seq_like: 4, mode: 'auto' };
    const others = [{ data: 'Hello World: 13', seq_like: 5, mode: 'auto' }];
    const c = byPath(pickFields(msg, others));
    expect(c.data).toMatchObject({ op: 'regex', value: '^Hello World: \\d+$', checked: true });
    expect(c.seq_like).toMatchObject({ checked: false, reason: 'changes' });
    expect(c.mode?.checked).toBe(true);
    // Other messages on the topic say something else: the clicked text is still what is expected.
    const text = byPath(pickFields({ data: 'HELLO E2E!' }, [{ data: 'HELLO WORLD: 3!' }]));
    expect(text.data).toMatchObject({ op: 'eq', value: 'HELLO E2E!', checked: true });
    const level = byPath(pickFields({ level: 2, v: 0.5 }, [{ level: 2, v: 0.7 }, { level: 3, v: 0.1 }]));
    expect(level.level?.checked).toBe(true); // repeats: a value, not a counter
    expect(level.v).toMatchObject({ op: 'approx', checked: true });
  });

  it('arrays: length checked, elements of long arrays unchecked, big arrays not checked', () => {
    const msg = {
      detections: [{ id: 'a' }, { id: 'b' }, { id: 'c' }, { id: 'd' }, { id: 'e' }],
      pair: [1, 2],
      data: { _truncated: true, length: 230400, head: [1, 2, 3] },
    };
    const c = byPath(pickFields(msg));
    expect(c.detections).toMatchObject({ op: 'len_eq', value: 5, checked: true });
    expect(c['detections.0.id']).toMatchObject({ checked: false, reason: 'element' });
    expect(c.pair).toMatchObject({ op: 'len_eq', value: 2, checked: true });
    expect(c['pair.1']).toMatchObject({ op: 'eq', value: 2, checked: true });
    expect(c.data).toMatchObject({ op: 'len_eq', value: 230400, checked: false, reason: 'big' });
    const varying = byPath(pickFields({ items: [1] }, [{ items: [1, 2] }]));
    expect(varying.items).toMatchObject({ checked: false, reason: 'changes' });
  });

  it('conditionsFrom keeps only checked fields, with tol for approx', () => {
    const conds = conditionsFrom([
      { path: 'a', value: 1, op: 'eq', checked: true, reason: null },
      { path: 'b', value: 0.5, op: 'approx', tol: 0.01, checked: true, reason: null },
      { path: 'c', value: 2, op: 'eq', checked: false, reason: 'volatile' },
    ]);
    expect(conds).toEqual([
      { field: 'a', op: 'eq', value: 1 },
      { field: 'b', op: 'approx', value: 0.5, tol: 0.01 },
    ]);
  });

  it('volatile names and numbered patterns', () => {
    expect(isVolatilePath('header.stamp')).toBe(true);
    expect(isVolatilePath('status.0.counter')).toBe(true);
    expect(isVolatilePath('header.frame_id')).toBe(false);
    expect(numberedPattern('frame 7 of 9', ['frame 8 of 9'])).toBe('^frame \\d+ of \\d+$');
    expect(numberedPattern('a.b 1', ['a.b 2'])).toBe('^a\\.b \\d+$');
    expect(numberedPattern('no digits', ['x'])).toBeNull();
    expect(numberedPattern('v1', ['w2'])).toBeNull();
  });
});

describe('withinFor', () => {
  it('is 3 x the response, at least 0.5 s, rounded up to 0.1 s', () => {
    expect(withinFor(0.01)).toBe(0.5);
    expect(withinFor(0.2)).toBe(0.6);
    expect(withinFor(0.34)).toBe(1.1);
    expect(withinFor(1)).toBe(3);
    expect(withinFor(-1)).toBe(0.5);
  });
});

const op = (t: number, o: Extract<RecordEvent, { kind: 'op' }>['op'], seq = 0): RecordEvent => ({ seq, t, kind: 'op', op: o });
const sendOp = (t: number, data: string, jobId = `j${t}`) =>
  op(t, { kind: 'inject', job_id: jobId, request: { mode: 'once', topic: '/cmd', type: 'std_msgs/msg/String', payload: { data }, qos: { reliability: 'reliable', durability: 'volatile', depth: 10 } } });

describe('OpConverter', () => {
  it('maps every operation to steps and stops to the started id', () => {
    const conv = new OpConverter();
    expect(conv.convert({ kind: 'inject', job_id: 'a', request: { mode: 'periodic', topic: '/scan', type: 'x/msg/Y', payload: { v: 1 }, rate_hz: 5 } }))
      .toEqual([{ start: { id: 'scan', topic: '/scan', type: 'x/msg/Y', data: { v: 1 }, rate_hz: 5 } }]);
    expect(conv.convert({ kind: 'inject', job_id: 'b', request: { mode: 'periodic', topic: '/scan', type: 'x/msg/Y', payload: {}, rate_hz: 1 } })[0])
      .toMatchObject({ start: { id: 'scan_2' } });
    expect(conv.convert({ kind: 'inject_stop', job_id: 'b' })).toEqual([{ stop: 'scan_2' }]);
    expect(conv.convert({ kind: 'inject_stop', job_id: 'zzz' })).toEqual([]);
    expect(conv.convert({ kind: 'inject', job_id: 'c', request: { mode: 'bag', source: 'bags/x', topics: ['/a'], bag_rate: 2, loop: false } }))
      .toEqual([{ play: { id: 'bag', bag: 'bags/x', topics: ['/a'], rate: 2 } }]);
    expect(conv.convert({ kind: 'inject', job_id: 'd', request: { mode: 'media', topic: '/cam', source: 'v.mp4', loop: true, media: { kind: 'video' } } }))
      .toEqual([{ start: { id: 'cam', topic: '/cam', media: { kind: 'video', source: 'v.mp4' }, loop: true } }]);
    expect(conv.convert({ kind: 'inject', job_id: 'e', request: { mode: 'stream', topic: '/s', type: 't/msg/T', source: 's.jsonl', rate_hz: 10, loop: true } }))
      .toEqual([{ start: { id: 's', topic: '/s', type: 't/msg/T', stream: 's.jsonl', rate_hz: 10, loop: true } }]);
    expect(conv.convert({ kind: 'target_start', target_id: 'text_shout' })).toEqual([{ start: { target: 'text_shout' } }]);
    expect(conv.convert({ kind: 'target_stop', target_id: 'text_shout' })).toEqual([{ stop: { target: 'text_shout' } }]);
    expect(conv.convert({ kind: 'target_restart', target_id: 't' })).toEqual([{ stop: { target: 't' } }, { start: { target: 't' } }]);
  });

  it('keeps a non-default QoS', () => {
    const conv = new OpConverter();
    const qos = { reliability: 'best_effort', durability: 'volatile', depth: 10 };
    expect(conv.convert({ kind: 'inject', job_id: 'a', request: { mode: 'once', topic: '/a', type: 't/msg/T', payload: {}, qos } }))
      .toEqual([{ send: { topic: '/a', type: 't/msg/T', qos, data: {} } }]);
  });
});

describe('buildSteps', () => {
  const expectAt = (t: number, within = 0.5): Expectation => ({
    id: `e${t}`, kind: 'expect', topic: '/state', type: 'std_msgs/msg/String', t, duration: 0, within,
    where: [{ field: 'data', op: 'eq', value: 'RUNNING' }],
  });

  it('operations with measured waits and expects right after the operation that caused them', () => {
    const events = [sendOp(2.0, 'start'), sendOp(5.0, 'stop')];
    const steps = buildSteps(events, [expectAt(2.1), { ...expectAt(5.05), where: [] }]);
    expect(steps).toEqual([
      { send: { topic: '/cmd', type: 'std_msgs/msg/String', data: { data: 'start' } } },
      { expect: { topic: '/state', type: 'std_msgs/msg/String', within: 0.5, where: [{ field: 'data', op: 'eq', value: 'RUNNING' }] } },
      { wait: 2.9 },
      { send: { topic: '/cmd', type: 'std_msgs/msg/String', data: { data: 'stop' } } },
      { expect: { topic: '/state', type: 'std_msgs/msg/String', within: 0.5 } },
    ]);
  });

  it('range expectations wait for their range and consume their duration', () => {
    const start = op(1.0, { kind: 'inject', job_id: 'p', request: { mode: 'periodic', topic: '/in', type: 't/msg/T', payload: {}, rate_hz: 10 } });
    const stop = op(10.0, { kind: 'inject_stop', job_id: 'p' });
    const rate: Expectation = { id: 'r', kind: 'rate', topic: '/out', t: 3.0, duration: 4.0, within: 0, where: [], minHz: 8, maxHz: 12 };
    const steps = buildSteps([start, stop], [rate]);
    expect(steps).toEqual([
      { start: { id: 'in', topic: '/in', type: 't/msg/T', data: {}, rate_hz: 10 } },
      { wait: 2 },
      { rate: { topic: '/out', for: 4, min_hz: 8, max_hz: 12 } },
      { wait: 3 },
      { stop: 'in' },
    ]);
  });

  it('throughput / latency / always / never steps', () => {
    const base = { id: 'x', topic: '/out', t: 0, duration: 2, within: 0, where: [] };
    expect(buildSteps([], [{ ...base, kind: 'throughput', input: '/in', minRatio: 0.9 }]))
      .toEqual([{ throughput: { input: '/in', output: '/out', for: 2, min_ratio: 0.9 } }]);
    expect(buildSteps([], [{ ...base, kind: 'latency', input: '/in', match: 'order', p95Ms: 40 }]))
      .toEqual([{ latency: { input: '/in', output: '/out', for: 2, match: 'order', p95_ms: 40 } }]);
    expect(buildSteps([], [{ ...base, kind: 'never' }])).toEqual([{ never: { topic: '/out', for: 2 } }]);
    expect(buildSteps([], [{ ...base, kind: 'always', where: [{ field: 'a', op: 'eq', value: 1 }] }]))
      .toEqual([{ always: { topic: '/out', for: 2, where: [{ field: 'a', op: 'eq', value: 1 }] } }]);
  });

  it('a stop of a job started before the recording is dropped; tiny waits are omitted', () => {
    const steps = buildSteps([op(0.05, { kind: 'inject_stop', job_id: 'old' }), sendOp(0.05, 'x')], []);
    expect(steps).toEqual([{ send: { topic: '/cmd', type: 'std_msgs/msg/String', data: { data: 'x' } } }]);
  });

  it('lastOpBefore gives the response reference', () => {
    const events = [sendOp(1, 'a'), sendOp(3, 'b')];
    expect(lastOpBefore(events, 2.5)).toBe(1);
    expect(lastOpBefore(events, 0.5)).toBe(0);
    expect(lastOpBefore(events, 3)).toBe(3);
  });
});

describe('suggestions and labels', () => {
  it('thresholds from measurements', () => {
    expect(suggestRate(10)).toEqual({ minHz: 8, maxHz: 12.01 });
    expect(suggestRatio(1)).toBe(0.9);
    expect(suggestRatio(0.5)).toBe(0.45);
    expect(suggestLatencyMs(5)).toBe(25);
    expect(suggestLatencyMs(100)).toBe(200);
  });

  it('short values and default names', () => {
    expect(shortValue({ data: 'HELLO' })).toBe('"HELLO"');
    expect(shortValue({ a: 1, b: 2 })).toBe('{"a":1,"b":2}');
    expect(shortValue({ data: 'x'.repeat(200) }, 10)).toHaveLength(10);
    expect(defaultName(new Date(2026, 0, 2, 3, 4))).toBe('recorded_20260102_0304');
  });
});
