// Number / time formatting for the UI (pure, unit-tested).

const UNITS = ['B', 'KB', 'MB', 'GB'] as const;

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || !Number.isFinite(bytes) || bytes <= 0) return '0 B';
  let value = bytes;
  let unit = 0;
  while (value >= 1000 && unit < UNITS.length - 1) {
    value /= 1000;
    unit += 1;
  }
  const digits = value >= 100 || unit === 0 ? 0 : 1;
  return `${value.toFixed(digits)} ${UNITS[unit]}`;
}

export function formatRate(bytesPerSec: number | null | undefined): string {
  return `${formatBytes(bytesPerSec)}/s`;
}

export function formatHz(hz: number | null | undefined): string {
  if (hz == null || !Number.isFinite(hz) || hz <= 0) return '0 Hz';
  if (hz >= 100) return `${hz.toFixed(0)} Hz`;
  if (hz >= 10) return `${hz.toFixed(1)} Hz`;
  return `${hz.toFixed(2)} Hz`;
}

export function formatMs(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return '—';
  return ms >= 100 ? `${ms.toFixed(0)} ms` : `${ms.toFixed(1)} ms`;
}

export function formatPercent(ratio: number | null | undefined): string {
  if (ratio == null || !Number.isFinite(ratio)) return '—';
  return `${(ratio * 100).toFixed(ratio < 0.1 ? 1 : 0)}%`;
}

/** Seconds since `epochSec` (wall clock), or null if never seen. */
export function ageSec(epochSec: number | null | undefined, nowMs: number = Date.now()): number | null {
  if (epochSec == null) return null;
  return Math.max(0, nowMs / 1000 - epochSec);
}

/** Edge label like `10.0 Hz · 1.2 KB/s` (empty when idle). */
export function edgeLabel(hz: number, bytesPerSec: number): string {
  if (!(hz > 0)) return '';
  return `${formatHz(hz)} · ${formatRate(bytesPerSec)}`;
}
