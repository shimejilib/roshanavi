// Pure helpers for "how fresh is this data" (DESIGN §6.5): averaging window
// label, the global last-update line and the hz-basis note.

import type { TrafficEntry } from '../api/types';
import { t } from '../i18n';
import { formatHz } from '../lib/format';

export const WINDOW_CHOICES = [1, 5, 10] as const;
export type WindowSec = (typeof WINDOW_CHOICES)[number];
export const DEFAULT_WINDOW: WindowSec = 5;
/** The live frame is considered late (warning colour) after this many seconds. */
export const LATE_AFTER_SEC = 5;

export function isWindowSec(value: number): value is WindowSec {
  return (WINDOW_CHOICES as readonly number[]).includes(value);
}

/** 「直近 5 秒の平均」 */
export function windowLabel(sec: number): string {
  return t('timing.window', { n: sec });
}

/** Local wall-clock time as HH:MM:SS. */
export function formatClock(ms: number): string {
  const d = new Date(ms);
  return [d.getHours(), d.getMinutes(), d.getSeconds()].map((n) => String(n).padStart(2, '0')).join(':');
}

export interface LastUpdate {
  text: string;
  late: boolean;
  ageSec: number | null;
  paused: boolean;
}

/**
 * 「最終更新 12:34:56 (2 秒前)」; late when no frame for more than LATE_AFTER_SEC.
 * While the view is paused the shown data is frozen on purpose, so it is never "late":
 * 「一時停止中 (12:34:56 の表示)」.
 */
export function lastUpdate(receivedAtMs: number, nowMs: number, paused = false): LastUpdate {
  if (paused) {
    const text = receivedAtMs ? t('timing.paused', { time: formatClock(receivedAtMs) }) : t('timing.pausedNever');
    return { text, late: false, ageSec: null, paused: true };
  }
  if (!receivedAtMs) return { text: t('timing.never'), late: true, ageSec: null, paused: false };
  const age = Math.max(0, Math.floor((nowMs - receivedAtMs) / 1000));
  return {
    text: t('timing.lastUpdate', { time: formatClock(receivedAtMs), n: age }),
    late: age > LATE_AFTER_SEC,
    ageSec: age,
    paused: false,
  };
}

/** Shown next to Hz only when it fell back to receive times (less accurate). */
export function hzBasisNote(basis: 'source' | 'receive' | undefined): string {
  return basis === 'receive' ? t('timing.basisReceive') : '';
}

/** Tooltip (ⓘ) explaining how Hz was measured. */
export function hzBasisHelp(basis: 'source' | 'receive' | undefined): string {
  return basis === 'receive' ? t('traffic.basis.receiveHelp') : t('traffic.basis.sourceHelp');
}

type RateFields = Pick<TrafficEntry, 'hz' | 'hz_basis' | 'rate_note' | 'rate_window_sec' | 'window_sec'>;

/**
 * Hz with its notes. A live topic slower than the window is measured over the
 * longest window (「(直近 10 秒で計算)」); with too few messages even there it
 * shows a dash instead of a misleading 0 Hz.
 */
export function rateText(entry: RateFields): string {
  if (entry.rate_note === 'too_few') return t('timing.tooFew', { n: entry.window_sec ?? '?' });
  const base = formatHz(entry.hz);
  if (entry.rate_note === 'extended') return `${base} ${t('timing.extended', { n: entry.rate_window_sec ?? '?' })}`;
  return `${base} ${hzBasisNote(entry.hz_basis)}`.trim();
}
