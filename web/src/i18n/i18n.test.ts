import { describe, expect, it } from 'vitest';
import type { Role } from '../api/types';
import { format, t, tDynamic, type MessageKey } from './index';
import { ja } from './messages';

describe('i18n', () => {
  it('interpolates and leaves unknown placeholders', () => {
    expect(format('{a} / {b}', { a: 1 })).toBe('1 / {b}');
    expect(t('inject.sent', { n: 3 })).toBe('送信 3 件');
  });

  it('falls back for unknown dynamic keys', () => {
    expect(tDynamic('error.nope', 'error.unknown')).toBe('エラーが発生しました');
    expect(tDynamic('error.unknown_type', 'error.unknown')).toContain('メッセージ型');
  });

  it('shows the key instead of throwing for a message that does not exist', () => {
    expect(t('no.such.key' as MessageKey)).toBe('no.such.key');
  });

  it('has a detail / list / launcher label for every node role (a missing one blanked the UI)', () => {
    const roles: Role[] = ['mine', 'dependency', 'dummy', 'transform', 'other'];
    for (const role of roles) {
      expect(ja[`detail.role.${role}` as MessageKey], `detail.role.${role}`).toBeTruthy();
      expect(ja[`nodes.role.${role}` as MessageKey], `nodes.role.${role}`).toBeTruthy();
    }
    for (const role of ['mine', 'dependency', 'dummy', 'transform'] as const) {
      expect(ja[`launcher.role.${role}` as MessageKey], `launcher.role.${role}`).toBeTruthy();
    }
  });
});
