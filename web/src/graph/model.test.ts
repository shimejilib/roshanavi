import { describe, expect, it } from 'vitest';
import type { Diagnostic } from '../api/types';
import { chatterGraph, entry, NOW_MS } from '../test/fixtures';
import { borderWidth, buildElements, edgeState, edgeWidth, filterSnapshot, type EdgeData } from './model';

const edgesOf = (els: ReturnType<typeof buildElements>): EdgeData[] =>
  els.filter((e) => e.group === 'edges').map((e) => e.data as EdgeData);

describe('edge style mapping', () => {
  it('grows edge width logarithmically and caps it', () => {
    expect(edgeWidth(0)).toBe(1.5);
    expect(edgeWidth(1_000_000)).toBeCloseTo(5.1, 1);
    expect(edgeWidth(1e15)).toBe(10);
    expect(edgeWidth(1000)).toBeLessThan(edgeWidth(10_000));
    expect(borderWidth(0)).toBe(1);
  });

  it('derives the edge state from traffic', () => {
    expect(edgeState(undefined, NOW_MS)).toBe('idle');
    expect(edgeState(entry('/a'), NOW_MS)).toBe('active');
    expect(edgeState(entry('/a', { last_seen: NOW_MS / 1000 - 5 }), NOW_MS)).toBe('stale');
    expect(edgeState(entry('/a', { last_seen: null }), NOW_MS)).toBe('stale');
    expect(edgeState(entry('/a', { drop_ratio: 0.1 }), NOW_MS)).toBe('drops');
    expect(edgeState(entry('/a', { monitored: false, status: 'not_monitored' }), NOW_MS)).toBe('not_monitored');
    expect(edgeState(entry('/a', { status: 'unsupported' }), NOW_MS)).toBe('idle');
  });
});

describe('filterSnapshot', () => {
  it('hides infrastructure topics', () => {
    const snap = filterSnapshot(chatterGraph(), { query: '', hideHidden: true });
    expect(snap.topics.map((t) => t.name)).toEqual(['/chatter']);
    expect(snap.edges).toHaveLength(2);
    expect(snap.nodes).toHaveLength(2);
  });

  it('keeps neighbours of matches', () => {
    const snap = filterSnapshot(chatterGraph(), { query: 'talk', hideHidden: true });
    expect(snap.nodes.map((n) => n.id)).toEqual(['/talker']);
    expect(snap.topics.map((t) => t.name)).toEqual(['/chatter']);
    expect(snap.edges.map((e) => e.node)).toEqual(['/talker']);
    const byTopic = filterSnapshot(chatterGraph(), { query: 'CHATTER', hideHidden: false });
    expect(byTopic.nodes.map((n) => n.id).sort()).toEqual(['/listener', '/talker']);
  });
});

describe('buildElements', () => {
  it('builds pub node->topic and sub topic->node edges with labels', () => {
    const graph = filterSnapshot(chatterGraph(), { query: '', hideHidden: true });
    const els = buildElements(graph, new Map([['/chatter', entry('/chatter')]]), NOW_MS);
    const edges = edgesOf(els);
    expect(edges.map((e) => [e.source, e.target])).toEqual([
      ['n:/talker', 't:/chatter'],
      ['t:/chatter', 'n:/listener'],
    ]);
    expect(edges[0]?.label).toBe('10.0 Hz · 1.0 KB/s');
    expect(edges[0]?.state).toBe('active');
    expect(els.filter((e) => e.group === 'nodes')).toHaveLength(3);
  });

  it('marks QoS-incompatible subscriber edges with a reason', () => {
    const graph = chatterGraph();
    const diag: Diagnostic = {
      code: 'qos_incompatible',
      severity: 'error',
      topic: '/chatter',
      nodes: ['/listener', '/talker'],
      detail: { publisher: '/talker', subscriber: '/listener', reasons: [{ policy: 'reliability', pub: 'best_effort', sub: 'reliable' }] },
    };
    const els = buildElements({ ...graph, diagnostics: [diag] }, new Map(), NOW_MS);
    const sub = edgesOf(els).find((e) => e.dir === 'sub' && e.topic === '/chatter');
    expect(sub?.qosBad).toBe(true);
    expect(sub?.qosReason).toContain('BEST_EFFORT');
    const topic = els.find((e) => e.data.id === 't:/chatter');
    expect(topic?.group === 'nodes' && topic.data.warn).toBe(true);
  });

  it('drops edges whose node is unknown and dedupes duplicates', () => {
    const graph = chatterGraph();
    const extra = { ...graph, edges: [...graph.edges, graph.edges[0]!, { ...graph.edges[0]!, node: '/ghost' }] };
    const edges = edgesOf(buildElements(extra, new Map(), NOW_MS));
    expect(edges.filter((e) => e.node === '/ghost')).toHaveLength(0);
    expect(new Set(edges.map((e) => e.id)).size).toBe(edges.length);
  });
});
