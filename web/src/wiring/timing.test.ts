import { describe, expect, it } from 'vitest';
import type { Timing } from './ports';
import { formTiming, timingDetail, timingRows, timingText, triggerChoices } from './timing';

const fn = (patch: Partial<Timing>): Timing => ({ owner: 'function', mode: 'on_message', rateHz: null, trigger: 'any', inputs: ['text'], ...patch });

describe('call timing (呼ばれ方)', () => {
  it('says when a one-input function is called', () => {
    expect(timingText(fn({}))).toBe('この入力が届くたびに呼ばれます');
  });

  it('explains the join rule of several inputs, both ways', () => {
    const multi = fn({ mode: 'multi_input', inputs: ['a', 'b', 'c'] });
    expect(timingText(multi)).toBe('どれかが届くたびに、全部の最新の値で呼ばれます');
    expect(timingText({ ...multi, trigger: 'a' })).toBe('a が届いたときだけ、b・c の最新の値と一緒に呼ばれます');
    expect(timingDetail(multi)).toBe('全部の入力が 1 回届くまでは呼ばれません');
    expect(timingRows({ ...multi, trigger: 'b' })).toEqual([{ name: 'a', triggers: false }, { name: 'b', triggers: true }, { name: 'c', triggers: false }]);
  });

  it('gives the rate of a periodic function and of input nodes', () => {
    expect(timingText(fn({ mode: 'periodic', rateHz: 10, inputs: [] }))).toBe('10 Hz で呼ばれます');
    expect(timingRows(fn({ mode: 'periodic', rateHz: 10, inputs: [] }))).toEqual([]);
    expect(timingText({ owner: 'dummy', mode: 'periodic', rateHz: 2.5, trigger: 'any', inputs: [] })).toBe('2.5 Hz で送ります');
    expect(timingText({ owner: 'dummy', mode: 'once', rateHz: null, trigger: 'any', inputs: [] })).toBe('起動したときに 1 回送ります');
  });

  it('describes transforms', () => {
    expect(timingText({ owner: 'transform', mode: 'relay', rateHz: null, trigger: 'any', inputs: ['msg'] })).toBe('届いたものを、そのまま送ります');
    expect(timingText({ owner: 'transform', mode: 'map', rateHz: null, trigger: 'any', inputs: ['msg'] })).toBe('届くたびに変換して送ります');
  });
});

describe('timing of a dialog form', () => {
  it('names the trigger by its argument, and only wired inputs can trigger', () => {
    const inputs = [{ name: 'a', topic: '/a' }, { name: 'b', topic: '' }];
    expect(formTiming('function', 'multi_input', '1', inputs, '/a')).toMatchObject({ trigger: 'a', inputs: ['a', 'b'] });
    expect(formTiming('function', 'periodic', '10', [], 'any').rateHz).toBe(10);
    expect(formTiming('function', 'periodic', 'x', [], 'any').rateHz).toBeNull();
    expect(triggerChoices(inputs).map((c) => [c.value, c.disabled])).toEqual([['any', false], ['/a', false], ['#b', true]]);
  });
});
