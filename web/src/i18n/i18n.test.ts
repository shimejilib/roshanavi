import { describe, expect, it } from 'vitest';
import { format, t, tDynamic } from './index';

describe('i18n', () => {
  it('interpolates and leaves unknown placeholders', () => {
    expect(format('{a} / {b}', { a: 1 })).toBe('1 / {b}');
    expect(t('inject.sent', { n: 3 })).toBe('送信 3 件');
  });

  it('falls back for unknown dynamic keys', () => {
    expect(tDynamic('error.nope', 'error.unknown')).toBe('エラーが発生しました');
    expect(tDynamic('error.unknown_type', 'error.unknown')).toContain('メッセージ型');
  });
});
