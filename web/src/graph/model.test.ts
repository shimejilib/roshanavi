import { describe, expect, it } from 'vitest';
import type { Diagnostic } from '../api/types';
import { chatterGraph, entry, heavyOffEntry, NOW_MS } from '../test/fixtures';
import { borderWidth, buildElements, edgeRate, edgeState, edgeWidth, filterSnapshot, type EdgeData } from './model';

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

  it('hides the ros2 CLI daemon and transient nodes with the internal topics, keeps them when shown', () => {
    const graph = chatterGraph();
    const withCli = {
      ...graph,
      nodes: [...graph.nodes, { id: '/_ros2cli_daemon_0_ab', name: '_ros2cli_daemon_0_ab', namespace: '/', role: 'other' as const }],
      edges: [...graph.edges, { ...graph.edges[1]!, node: '/_ros2cli_daemon_0_ab' }],
    };
    const hidden = filterSnapshot(withCli, { query: '', hideHidden: true });
    expect(hidden.nodes.map((n) => n.id)).toEqual(['/talker', '/listener']);
    expect(hidden.edges.every((e) => !e.node.startsWith('/_ros2cli'))).toBe(true);
    expect(filterSnapshot(withCli, { query: '', hideHidden: false }).nodes).toHaveLength(3);
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

  it('shows info diagnostics quietly: a note under the topic, no warning glow', () => {
    const graph = chatterGraph();
    const info: Diagnostic = { code: 'no_subscriber', severity: 'info', topic: '/chatter', nodes: ['/talker'], detail: {} };
    const els = buildElements({ ...graph, diagnostics: [info] }, new Map(), NOW_MS);
    const topic = els.find((e) => e.data.id === 't:/chatter');
    expect(topic?.group === 'nodes' && topic.data.warn).toBe(false);
    expect(topic?.group === 'nodes' && topic.data.label).toBe('/chatter\n受信なし');
  });

  it('glows the developer node and its topic for mine_no_input', () => {
    const graph = chatterGraph();
    const warn: Diagnostic = { code: 'mine_no_input', severity: 'warning', topic: '/chatter', nodes: ['/listener'], detail: { node: '/listener' } };
    const els = buildElements({ ...graph, diagnostics: [warn] }, new Map(), NOW_MS);
    const flags = (id: string) => {
      const el = els.find((e) => e.data.id === id);
      return el?.group === 'nodes' && el.data.warn;
    };
    expect(flags('n:/listener')).toBe(true);
    expect(flags('n:/talker')).toBe(false);
    expect(flags('t:/chatter')).toBe(true);
  });

  it('drops edges whose node is unknown and dedupes duplicates', () => {
    const graph = chatterGraph();
    const extra = { ...graph, edges: [...graph.edges, graph.edges[0]!, { ...graph.edges[0]!, node: '/ghost' }] };
    const edges = edgesOf(buildElements(extra, new Map(), NOW_MS));
    expect(edges.filter((e) => e.node === '/ghost')).toHaveLength(0);
    expect(new Set(edges.map((e) => e.id)).size).toBe(edges.length);
  });
});

describe('launcher roles', () => {
  it('keeps the role from the snapshot and labels real vs virtual dummies', () => {
    const snap = chatterGraph();
    snap.nodes = [
      { id: '/talker', name: 'talker', namespace: '/', role: 'mine', target_id: 'tk', confidence: 'exact' },
      { id: '/dummy_cam', name: 'dummy_cam', namespace: '/', role: 'dummy', target_id: 'cam', confidence: 'exact' },
      { id: 'dummy:abc', name: 'inject periodic', namespace: '', role: 'dummy', job_id: 'abc' },
    ];
    const nodes = buildElements(snap, new Map(), NOW_MS).flatMap((e) => (e.group === 'nodes' && e.data.kind === 'node' ? [e.data] : []));
    expect(nodes.map((n) => [n.label, n.role])).toEqual([
      ['/talker', 'mine'],
      ['/dummy_cam', 'dummy'],
      ['inject periodic\nabc', 'dummy'],
    ]);
  });
});

describe('per-publisher rates on edges', () => {
  const graphWithDummy = () => {
    const g = chatterGraph();
    g.nodes.push({ id: 'dummy:j1', name: 'inject periodic', namespace: '', role: 'dummy', job_id: 'j1' });
    g.edges.push({ node: 'dummy:j1', topic: '/chatter', dir: 'pub', qos: { reliability: 'reliable', durability: 'volatile' } });
    return g;
  };
  const byId = (els: ReturnType<typeof buildElements>, id: string) => edgesOf(els).find((e) => e.id === id);

  it('labels the talker as estimated and the dummy as exact; subscribers get the total', () => {
    const traffic = new Map([[
      '/chatter',
      entry('/chatter', {
        hz: 2, bytes_per_sec: 60, source_count: 2,
        publishers: [
          { node: '/talker', hz: 1, bps: 30, basis: 'estimated' },
          { node: 'dummy:j1', hz: 1, bps: 30, basis: 'exact' },
        ],
      }),
    ]]);
    const els = buildElements(graphWithDummy(), traffic, NOW_MS);
    const talker = byId(els, 'e:pub:/talker:/chatter');
    expect(talker?.label).toBe('1.00 Hz · 30 B/s (推定)');
    expect(talker?.rateNote).toContain('推定');
    expect(byId(els, 'e:pub:dummy:j1:/chatter')?.label).toBe('1.00 Hz · 30 B/s');
    expect(byId(els, 'e:sub:/listener:/chatter')?.label).toBe('2.00 Hz · 60 B/s');
    const topic = els.find((e) => e.data.id === 't:/chatter');
    expect(topic?.data.label).toBe('/chatter\n合計 2.00 Hz / 送信元 2');
  });

  it('leaves edges unlabeled when the split is unknown', () => {
    const traffic = new Map([[
      '/chatter',
      entry('/chatter', {
        hz: 4, source_count: 2,
        publishers: [
          { node: '/talker', hz: null, bps: null, basis: 'unknown' },
          { node: 'dummy:j1', hz: null, bps: null, basis: 'unknown' },
        ],
      }),
    ]]);
    const talker = byId(buildElements(graphWithDummy(), traffic, NOW_MS), 'e:pub:/talker:/chatter');
    expect(talker?.label).toBe('');
    expect(talker?.hz).toBe(2);
  });

  it('falls back to the topic total without per-publisher data', () => {
    const els = buildElements(chatterGraph(), new Map([['/chatter', entry('/chatter')]]), NOW_MS);
    expect(byId(els, 'e:pub:/talker:/chatter')?.rateBasis).toBe('total');
  });
});

describe('subscriber edge rate', () => {
  it('uses the theoretical rate when only some publishers are QoS-compatible', () => {
    const e = entry('/chatter', {
      hz: 3, bytes_per_sec: 300,
      subscribers: [{ node: '/picky', hz: 1, bps: 100, basis: 'theoretical', delivered: true, sources: ['/a'] }],
    });
    expect(edgeRate({ node: '/picky', dir: 'sub' }, e)).toMatchObject({ hz: 1, bw: 100 });
    expect(edgeRate({ node: '/other', dir: 'sub' }, e)).toMatchObject({ hz: 3, bw: 300 });
  });
});

describe('a heavy topic that is not measured (#61)', () => {
  const graph = () => {
    const g = chatterGraph();
    return { ...g, topics: [{ name: '/chatter', types: ['sensor_msgs/msg/Image'] }] };
  };

  it('has no rate label and a note that it is not measured; the edge is dotted (not_monitored)', () => {
    const off = heavyOffEntry('/chatter', {
      publishers: [{ node: '/talker', hz: null, bps: null, basis: 'not_monitored' }],
      subscribers: [{ node: '/listener', hz: null, bps: null, basis: 'not_monitored', delivered: true, sources: ['/talker'] }],
    });
    const edges = edgesOf(buildElements(graph(), new Map([['/chatter', off]]), NOW_MS));
    const pub = edges.find((e) => e.dir === 'pub')!;
    expect(pub).toMatchObject({ label: '', state: 'not_monitored', rateBasis: 'not_monitored' });
    expect(pub.rateNote).toContain('計測していません');
    expect(edges.find((e) => e.dir === 'sub')).toMatchObject({ label: '', state: 'not_monitored' });
  });

  it('shows the traced send rate of the publisher in 詳細計測モード, without bandwidth', () => {
    const traced = heavyOffEntry('/chatter', {
      publishers: [{ node: '/talker', hz: 30, bps: null, basis: 'traced', hz_traced: 30 }],
      subscribers: [],
    });
    const pub = edgesOf(buildElements(graph(), new Map([['/chatter', traced]]), NOW_MS)).find((e) => e.dir === 'pub')!;
    expect(pub.label).toBe('30.0 Hz');
    expect(pub.rateNote).toContain('詳細計測モード');
  });

  it('a real subscriber is not turned into 受信なし by the traffic state (that marker comes from the graph only)', () => {
    const off = heavyOffEntry('/chatter');
    const els = buildElements(graph(), new Map([['/chatter', off]]), NOW_MS);
    const topic = els.find((e) => e.group === 'nodes' && e.data.kind === 'topic')!;
    expect(topic.data.label).toBe('/chatter');
    // The graph diagnostics are the only source of the marker: with a diagnostic it appears.
    const quiet: Diagnostic = { code: 'no_subscriber', severity: 'info', topic: '/chatter', nodes: [], detail: {} };
    const withMarker = buildElements({ ...graph(), diagnostics: [quiet] }, new Map([['/chatter', off]]), NOW_MS);
    expect(withMarker.find((e) => e.group === 'nodes' && e.data.kind === 'topic')!.data.label).toBe('/chatter\n受信なし');
  });
});
