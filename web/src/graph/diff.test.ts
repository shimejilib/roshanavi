import { describe, expect, it } from 'vitest';
import { chatterGraph, entry, NOW_MS } from '../test/fixtures';
import { diffElements, indexElements } from './diff';
import { buildElements } from './model';

describe('diffElements', () => {
  const graph = chatterGraph();
  const base = buildElements(graph, new Map([['/chatter', entry('/chatter')]]), NOW_MS);

  it('reports everything as added from empty', () => {
    const patch = diffElements(new Map(), base);
    expect(patch.added).toHaveLength(base.length);
    expect(patch.topologyChanged).toBe(true);
  });

  it('only updates data when traffic changes (no relayout)', () => {
    const next = buildElements(graph, new Map([['/chatter', entry('/chatter', { hz: 20, bytes_per_sec: 2000 })]]), NOW_MS);
    const patch = diffElements(indexElements(base), next);
    expect(patch.added).toEqual([]);
    expect(patch.removed).toEqual([]);
    expect(patch.topologyChanged).toBe(false);
    expect(patch.updated.map((e) => e.data.id).sort()).toEqual(
      ['e:pub:/talker:/chatter', 'e:sub:/listener:/chatter', 'n:/listener', 'n:/talker', 't:/chatter'].sort(),
    );
  });

  it('is empty for identical input', () => {
    const patch = diffElements(indexElements(base), buildElements(graph, new Map([['/chatter', entry('/chatter')]]), NOW_MS));
    expect(patch).toEqual({ added: [], removed: [], updated: [], topologyChanged: false });
  });

  it('detects removed topics', () => {
    const smaller = { ...graph, topics: graph.topics.slice(0, 1), edges: graph.edges.slice(0, 2) };
    const patch = diffElements(indexElements(base), buildElements(smaller, new Map(), NOW_MS));
    expect(patch.removed).toContain('t:/rosout');
    expect(patch.topologyChanged).toBe(true);
  });
});
