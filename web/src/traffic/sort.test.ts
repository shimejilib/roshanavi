import { describe, expect, it } from 'vitest';
import { entry } from '../test/fixtures';
import { sortTraffic, toggleSort } from './sort';

describe('sortTraffic', () => {
  const rows = [entry('/b', { hz: 5, latency_ms: null }), entry('/a', { hz: 50, latency_ms: 2 }), entry('/c', { hz: 1, latency_ms: 1 })];

  it('sorts by name and by number', () => {
    expect(sortTraffic(rows, { key: 'topic', desc: false }).map((r) => r.topic)).toEqual(['/a', '/b', '/c']);
    expect(sortTraffic(rows, { key: 'hz', desc: true }).map((r) => r.topic)).toEqual(['/a', '/b', '/c']);
    expect(sortTraffic(rows, { key: 'hz', desc: false }).map((r) => r.topic)).toEqual(['/c', '/b', '/a']);
  });

  it('keeps nulls last in both directions and does not mutate input', () => {
    expect(sortTraffic(rows, { key: 'latency_ms', desc: false }).map((r) => r.topic)).toEqual(['/c', '/a', '/b']);
    expect(sortTraffic(rows, { key: 'latency_ms', desc: true }).map((r) => r.topic)).toEqual(['/a', '/c', '/b']);
    expect(rows.map((r) => r.topic)).toEqual(['/b', '/a', '/c']);
  });

  it('toggles direction; numbers default to descending', () => {
    expect(toggleSort({ key: 'topic', desc: false }, 'topic')).toEqual({ key: 'topic', desc: true });
    expect(toggleSort({ key: 'topic', desc: false }, 'hz')).toEqual({ key: 'hz', desc: true });
  });
});
