import { describe, expect, it } from 'vitest';
import { dbfs, meterPercent, rms, smoothLevel } from './level';
import { downmix, floatToInt16, PcmChunker, samplesFor } from './pcm';
import { int16ToFloat, peaks, SampleRing } from './waveform';

describe('pcm', () => {
  it('converts float to int16 with clipping', () => {
    expect([...floatToInt16(new Float32Array([0, 1, -1, 2, -2, 0.5]))]).toEqual([0, 32767, -32768, 32767, -32768, 16384]);
  });

  it('downmixes channels', () => {
    expect([...downmix([new Float32Array([1, 0]), new Float32Array([0, -1])])]).toEqual([0.5, -0.5]);
    expect(downmix([])).toHaveLength(0);
  });

  it('chunks a stream into fixed sizes and keeps the remainder', () => {
    const chunker = new PcmChunker(4);
    expect(chunker.push(new Int16Array([1, 2, 3]))).toEqual([]);
    const out = chunker.push(new Int16Array([4, 5, 6, 7, 8, 9]));
    expect(out.map((c) => [...c])).toEqual([[1, 2, 3, 4], [5, 6, 7, 8]]);
    expect(chunker.pending).toBe(1);
    expect(() => new PcmChunker(0)).toThrow();
    expect(samplesFor(20, 16000)).toBe(320);
  });
});

describe('level meter', () => {
  it('computes rms, dBFS and meter percent', () => {
    expect(rms([1, -1, 1, -1])).toBe(1);
    expect(rms([])).toBe(0);
    expect(dbfs(1)).toBe(0);
    expect(dbfs(0.1)).toBeCloseTo(-20);
    expect(dbfs(0)).toBe(-Infinity);
    expect(meterPercent(0)).toBe(100);
    expect(meterPercent(-30)).toBe(50);
    expect(meterPercent(-80)).toBe(0);
    expect(meterPercent(-Infinity)).toBe(0);
    expect(smoothLevel(80, 20)).toBe(77);
    expect(smoothLevel(10, 20)).toBe(20);
  });
});

describe('waveform', () => {
  it('computes min/max per bucket', () => {
    const p = peaks(new Int16Array([0, 16384, -16384, 0, 32767, -32768]), 3);
    expect(p).toEqual([{ min: 0, max: 0.5 }, { min: -0.5, max: 0 }, { min: -1, max: 32767 / 32768 }]);
    expect(peaks(new Int16Array(4), 0)).toEqual([]);
  });

  it('keeps the latest samples in a ring', () => {
    const ring = new SampleRing(4);
    ring.push(new Int16Array([1, 2, 3]));
    ring.push(new Int16Array([4, 5]));
    expect([...ring.values()]).toEqual([2, 3, 4, 5]);
    ring.push(new Int16Array([6, 7, 8, 9, 10]));
    expect([...ring.values()]).toEqual([7, 8, 9, 10]);
    expect([...int16ToFloat(new Int16Array([16384]))]).toEqual([0.5]);
  });
});
