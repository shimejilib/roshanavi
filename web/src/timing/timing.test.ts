import { describe, expect, it } from 'vitest';
import { formatClock, hzBasisNote, isWindowSec, lastUpdate, LATE_AFTER_SEC, rateText, windowLabel } from './timing';

describe('timing labels', () => {
  it('names the averaging window', () => {
    expect(windowLabel(5)).toBe('直近 5 秒の平均');
    expect(isWindowSec(10)).toBe(true);
    expect(isWindowSec(3)).toBe(false);
  });

  it('formats the last update with its age', () => {
    const at = new Date(2026, 9, 17, 9, 5, 7).getTime();
    expect(formatClock(at)).toBe('09:05:07');
    const fresh = lastUpdate(at, at + 2_400);
    expect(fresh.text).toBe('最終更新 09:05:07 (2 秒前)');
    expect(fresh.late).toBe(false);
    expect(lastUpdate(at, at + (LATE_AFTER_SEC + 1) * 1000).late).toBe(true);
    expect(lastUpdate(at, at + LATE_AFTER_SEC * 1000).late).toBe(false);
  });

  it('reports "never" before the first frame', () => {
    const none = lastUpdate(0, Date.now());
    expect(none.late).toBe(true);
    expect(none.ageSec).toBeNull();
  });

  it('only notes the receive-time basis', () => {
    expect(hzBasisNote('source')).toBe('');
    expect(hzBasisNote(undefined)).toBe('');
    expect(hzBasisNote('receive')).toBe('(受信時刻で概算)');
  });
});

describe('paused view and slow topics', () => {
  it('shows 一時停止中 instead of the warning colour while paused', () => {
    const at = new Date(2026, 9, 17, 9, 5, 7).getTime();
    const paused = lastUpdate(at, at + 60_000, true);
    expect(paused.late).toBe(false);
    expect(paused.paused).toBe(true);
    expect(paused.text).toBe('一時停止中 (09:05:07 の表示)');
    expect(lastUpdate(0, at, true).text).toBe('一時停止中');
  });

  it('never shows 0 Hz for a live topic slower than the window', () => {
    const base = { hz: 0.5, hz_basis: 'source' as const, window_sec: 1 };
    expect(rateText({ ...base, rate_note: 'extended', rate_window_sec: 10 })).toBe('0.50 Hz (直近 10 秒で計算)');
    expect(rateText({ ...base, hz: 0, rate_note: 'too_few', rate_window_sec: 1 })).toBe('— (1 秒窓では測定不可)');
    expect(rateText({ ...base, hz: 10, rate_note: null, rate_window_sec: 1 })).toBe('10.0 Hz');
    expect(rateText({ ...base, hz: 10, hz_basis: 'receive' })).toBe('10.0 Hz (受信時刻で概算)');
  });
});
