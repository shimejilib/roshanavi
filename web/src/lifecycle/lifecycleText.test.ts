import { describe, expect, it } from 'vitest';
import { confirmTransitionText, offeredTransitions, transitionLabel } from './lifecycleText';

describe('lifecycle text', () => {
  it('orders offered transitions and hides unknown ones', () => {
    const info = { transitions: [{ id: 4, label: 'deactivate' as const, goal: 'inactive' }, { id: 2, label: 'cleanup' as const, goal: 'unconfigured' }] };
    expect(offeredTransitions(info)).toEqual(['deactivate', 'cleanup']);
    expect(transitionLabel('activate')).toBe('有効にする (activate)');
  });

  it('warns about nodes roshanavi did not start', () => {
    expect(confirmTransitionText('/lc', 'deactivate', false)).not.toContain('roshanavi が起動していない');
    const text = confirmTransitionText('/lc', 'deactivate', true);
    expect(text).toContain('/lc を「無効にする (deactivate)」します。');
    expect(text).toContain('roshanavi が起動していないノード');
  });
});
