import { describe, expect, it, vi } from 'vitest';
import { onRefocus } from './refocus';

describe('onRefocus', () => {
  it('refreshes on window focus and when the tab becomes visible, until unsubscribed', () => {
    const win = new EventTarget();
    const doc = Object.assign(new EventTarget(), { visibilityState: 'hidden' });
    const refresh = vi.fn();
    const stop = onRefocus(win, doc, refresh);

    win.dispatchEvent(new Event('focus'));
    expect(refresh).toHaveBeenCalledTimes(1);

    doc.dispatchEvent(new Event('visibilitychange'));
    expect(refresh).toHaveBeenCalledTimes(1); // still hidden
    doc.visibilityState = 'visible';
    doc.dispatchEvent(new Event('visibilitychange'));
    expect(refresh).toHaveBeenCalledTimes(2);

    stop();
    win.dispatchEvent(new Event('focus'));
    expect(refresh).toHaveBeenCalledTimes(2);
  });
});
