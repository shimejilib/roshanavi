import { describe, expect, it } from 'vitest';
import { ageSec, edgeLabel, formatBytes, formatHz, formatMs, formatPercent, formatRate } from './format';

describe('format', () => {
  it('formats bytes with SI units', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(1200)).toBe('1.2 KB');
    expect(formatBytes(1_234_567)).toBe('1.2 MB');
    expect(formatBytes(null)).toBe('0 B');
    expect(formatRate(2500)).toBe('2.5 KB/s');
  });

  it('formats hz with precision by magnitude', () => {
    expect(formatHz(0)).toBe('0 Hz');
    expect(formatHz(0.5)).toBe('0.50 Hz');
    expect(formatHz(10)).toBe('10.0 Hz');
    expect(formatHz(1000)).toBe('1000 Hz');
  });

  it('formats ms, percent and missing values', () => {
    expect(formatMs(null)).toBe('—');
    expect(formatMs(1.234)).toBe('1.2 ms');
    expect(formatMs(250)).toBe('250 ms');
    expect(formatPercent(0.05)).toBe('5.0%');
    expect(formatPercent(null)).toBe('—');
  });

  it('computes age and edge labels', () => {
    expect(ageSec(null)).toBeNull();
    expect(ageSec(100, 103_000)).toBe(3);
    expect(edgeLabel(0, 0)).toBe('');
    expect(edgeLabel(10, 1200)).toBe('10.0 Hz · 1.2 KB/s');
  });
});
