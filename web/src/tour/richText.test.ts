import { describe, expect, it } from 'vitest';
import { richSegments } from './richText';

describe('richSegments', () => {
  it('marks backticked parts as code and keeps the rest as text', () => {
    expect(richSegments('送り先に `/hello` と入力')).toEqual([
      { text: '送り先に ', code: false },
      { text: '/hello', code: true },
      { text: ' と入力', code: false },
    ]);
  });

  it('never produces markup: tags stay literal text', () => {
    expect(richSegments('<img src=x onerror=1>')).toEqual([{ text: '<img src=x onerror=1>', code: false }]);
  });
});
