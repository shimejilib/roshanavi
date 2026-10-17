import { describe, expect, it } from 'vitest';
import {
  conditions,
  move,
  parseLike,
  parsePayload,
  payloadText,
  removeAt,
  setField,
  stepBody,
  stepKind,
  updateCondition,
} from './editSteps';
import { mergeEvents } from './ScenarioLive';

describe('step editing', () => {
  it('reads and writes scalar and mapping forms without mutating', () => {
    const wait = { wait: 1 };
    expect(stepKind(wait)).toBe('wait');
    expect(stepBody(wait)).toEqual({ seconds: 1 });
    expect(setField(wait, 'seconds', 2.5)).toEqual({ wait: 2.5 });
    expect(wait).toEqual({ wait: 1 });
    expect(stepBody({ stop: 'cam' })).toEqual({ id: 'cam' });
    const expectStep = { expect: { topic: '/a', within: 1 } };
    expect(setField(expectStep, 'within', 2)).toEqual({ expect: { topic: '/a', within: 2 } });
    expect(setField(expectStep, 'count', undefined)).toEqual(expectStep);
    expect(expectStep.expect.within).toBe(1);
  });

  it('edits where conditions', () => {
    const step = { expect: { topic: '/a', within: 1, where: [{ field: 'data', op: 'eq' as const, value: 'X' }] } };
    const changed = updateCondition(step, 0, { value: 'Y' });
    expect(conditions(changed)).toEqual([{ field: 'data', op: 'eq', value: 'Y' }]);
    expect(conditions(step)[0]?.value).toBe('X');
    const approx = updateCondition(step, 0, { op: 'approx', value: 1, tol: 0.1 });
    expect(conditions(approx)[0]).toEqual({ field: 'data', op: 'approx', value: 1, tol: 0.1 });
    const cleared = updateCondition(approx, 0, { tol: undefined });
    expect(conditions(cleared)[0]).not.toHaveProperty('tol');
  });

  it('moves and removes', () => {
    expect(move([1, 2, 3], 0, 1)).toEqual([2, 1, 3]);
    expect(move([1, 2, 3], 0, -1)).toEqual([1, 2, 3]);
    expect(removeAt([1, 2, 3], 1)).toEqual([1, 3]);
  });

  it('parses typed text like the previous value', () => {
    expect(parseLike('3', 1)).toBe(3);
    expect(parseLike('x', 1)).toBe('x');
    expect(parseLike('false', true)).toBe(false);
    expect(parseLike('12', 'a')).toBe('12');
  });

  it('send payload text', () => {
    expect(payloadText({ send: { topic: '/a', kind: 'string', value: 'hi' } })).toEqual({ key: 'value', text: 'hi' });
    expect(payloadText({ send: { topic: '/a', data: { data: 1 } } })).toEqual({ key: 'data', text: '{"data":1}' });
    expect(parsePayload('data', '{"a": 1}')).toEqual({ ok: true, value: { a: 1 } });
    expect(parsePayload('data', '[1]')).toEqual({ ok: false });
    expect(parsePayload('value', 'hello')).toEqual({ ok: true, value: 'hello' });
    expect(parsePayload('value', '2.5')).toEqual({ ok: true, value: 2.5 });
  });
});

describe('scenario socket frames', () => {
  const frame = (sessionId: string | null, seqs: number[]) => ({
    running: false,
    record: {
      active: sessionId !== null,
      session: sessionId ? { id: sessionId, watch: [], started_at: 0, elapsed_sec: 0, types: {}, counts: {}, dropped: 0 } : null,
      events: seqs.map((seq) => ({ seq, t: seq, kind: 'op' as const, op: { kind: 'inject_stop' as const, job_id: 'x' } })),
    },
  });
  const empty = { run: null, running: false, record: { active: false, session: null }, events: [] };

  it('appends new events and restarts the timeline for a new session', () => {
    const a = mergeEvents(empty, frame('s1', [1, 2]));
    const b = mergeEvents(a, frame('s1', [2, 3]));
    expect(b.events.map((e) => e.seq)).toEqual([1, 2, 3]);
    const c = mergeEvents(b, frame('s2', [1]));
    expect(c.events.map((e) => e.seq)).toEqual([1]);
    expect(mergeEvents(c, frame('s2', [])).events).toBe(c.events);
  });
});

describe('describeStep', () => {
  it('plain lines for the record-mode preview', async () => {
    const { describeStep } = await import('./editSteps');
    expect(describeStep({ send: { topic: '/chatter', data: { data: 'hi' } } })).toBe('送る: /chatter ← {"data":"hi"}');
    expect(describeStep({ wait: 2.5 })).toBe('待つ: 2.5 秒');
    expect(describeStep({ expect: { topic: '/s', within: 0.5, where: [{ field: 'data', op: 'eq', value: 'A' }] } }))
      .toBe('届くはず: /s に 0.5 秒以内 (data = "A")');
    expect(describeStep({ stop: { target: 'x' } })).toBe('停止: x');
    expect(describeStep({ start: { target: 'x' } })).toBe('起動: x');
    expect(describeStep({ latency: { input: '/a', output: '/b', for: 2, p95_ms: 40, match: 'order' } }))
      .toBe('処理時間: /a → /b の p95 ≤ 40 ms (2 秒、受信順の近似)');
  });
});
