// Level meter math (pure, unit-tested).

export const METER_FLOOR_DB = -60;

/** Root mean square of samples in [-1, 1]. */
export function rms(samples: ArrayLike<number>): number {
  if (samples.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < samples.length; i += 1) {
    const v = samples[i] ?? 0;
    sum += v * v;
  }
  return Math.sqrt(sum / samples.length);
}

/** dB relative to full scale; silence -> -Infinity. */
export function dbfs(value: number): number {
  return value > 0 ? 20 * Math.log10(value) : -Infinity;
}

/** dBFS -> 0..100 % of the meter (floor at -60 dB). */
export function meterPercent(db: number, floorDb: number = METER_FLOOR_DB): number {
  if (!Number.isFinite(db) || db <= floorDb) return 0;
  return Math.min(100, ((db - floorDb) / -floorDb) * 100);
}

/** Meter that falls back slowly (peak hold feel): new = max(level, prev - decay). */
export function smoothLevel(previous: number, level: number, decay = 3): number {
  return Math.max(level, previous - decay);
}
