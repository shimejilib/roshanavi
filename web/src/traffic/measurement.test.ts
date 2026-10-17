import { describe, expect, it } from 'vitest';
import type { Measurement } from '../api/types';
import { basisHelp, basisLabel } from './endpoints';
import { measurementNote, trafficErrorText } from './measurement';

const PROBE: Measurement = {
  mode: 'probe', reason: null, state: 'running', pid: 12, restarts: 0, receiving: true,
  cpu_percent: 0.42, rss_bytes: 1, rmw: 'rmw_fastrtps_cpp', gid_resolution: 'matched',
};

describe('measurementNote', () => {
  it('shows the probe and its CPU', () => {
    expect(measurementNote(PROBE)).toMatchObject({ text: '計測: C++ 計測ノード (CPU 0.4%)', level: 'info' });
    expect(measurementNote({ ...PROBE, cpu_percent: null })?.text).toBe('計測: C++ 計測ノード');
  });

  it('warns while the probe restarts or cannot tell publishers apart', () => {
    expect(measurementNote({ ...PROBE, receiving: false })).toMatchObject({ level: 'warn', text: '計測ノードを再起動しています…' });
    expect(measurementNote({ ...PROBE, gid_resolution: 'unmatched', rmw: 'rmw_cyclonedds_cpp' })?.text).toContain('rmw_cyclonedds_cpp');
  });

  it('explains the Python fallback', () => {
    const python: Measurement = { ...PROBE, mode: 'python', reason: 'not_built', state: null };
    expect(measurementNote(python)).toMatchObject({ level: 'warn' });
    expect(measurementNote(python)?.text).toContain('ビルドされていない');
    expect(measurementNote({ ...python, reason: 'crashed' })?.text).toContain('異常終了');
    expect(measurementNote({ ...python, reason: 'disabled' })?.level).toBe('info');
    expect(measurementNote(null)).toBeNull();
  });
});

describe('measured basis badge', () => {
  it('reads 実測 and explains per-publisher counting', () => {
    expect(basisLabel('measured')).toBe('実測');
    expect(basisHelp('measured')).toContain('送信元を区別して');
  });
});

describe('trafficErrorText', () => {
  it('translates the probe outage code', () => {
    expect(trafficErrorText('probe_unavailable')).toContain('計測ノード');
    expect(trafficErrorText('boom')).toBe('boom');
    expect(trafficErrorText(null)).toBeUndefined();
  });
});
