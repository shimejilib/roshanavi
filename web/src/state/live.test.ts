import { describe, expect, it } from 'vitest';
import { chatterGraph, entry } from '../test/fixtures';
import { applyLive, EMPTY_LIVE, isLiveMessage } from './live';

describe('live reducer', () => {
  it('validates frames', () => {
    expect(isLiveMessage({ traffic: [], jobs: [] })).toBe(true);
    expect(isLiveMessage({ traffic: [] })).toBe(false);
    expect(isLiveMessage(null)).toBe(false);
  });

  it('keeps the last graph when a frame has none', () => {
    const graph = chatterGraph();
    const first = applyLive(EMPTY_LIVE, { traffic: [entry('/chatter')], jobs: [], graph }, 1);
    const second = applyLive(first, { traffic: [], jobs: [] }, 2);
    expect(second.graph).toEqual(graph);
    expect(second.traffic.size).toBe(0);
    expect(second.tick).toBe(2);
    expect(first.traffic.get('/chatter')?.hz).toBe(10);
  });
});
