import { describe, expect, it } from 'vitest';
import { entry } from '../test/fixtures';
import { basisHelp, basisLabel, endpointBandwidth, endpointHz, groupByNode, toggleAllTopics, toggleTopic, topicEndpoints } from './endpoints';

const chatter = entry('/chatter', {
  publishers: [{ node: '/talker', hz: 10, bps: 300, basis: 'measured' }, { node: '/a_dummy', hz: 1, bps: null, basis: 'configured' }],
  subscribers: [
    { node: '/listener', hz: 10, bps: 300, basis: 'theoretical', delivered: true, sources: ['/talker'] },
    { node: '/fussy', hz: 0, bps: 0, basis: 'not_delivered', delivered: false, sources: [] },
  ],
});
const other = entry('/other', {
  publishers: [{ node: '/listener', hz: 2, bps: 20, basis: 'measured' }],
  subscribers: [],
});

describe('traffic endpoints', () => {
  it('lists publishers then subscribers of a topic, each by node', () => {
    expect(topicEndpoints(chatter).map((r) => `${r.dir} ${r.node}`)).toEqual(['pub /a_dummy', 'pub /talker', 'sub /fussy', 'sub /listener']);
    expect(topicEndpoints(entry('/x'))).toEqual([]);
  });

  it('groups by node: sends first, then receives, topics in order', () => {
    const groups = groupByNode([other, chatter]);
    expect(groups.map((g) => g.node)).toEqual(['/a_dummy', '/fussy', '/listener', '/talker']);
    const listener = groups.find((g) => g.node === '/listener');
    expect(listener?.rows.map((r) => `${r.dir} ${r.topic}`)).toEqual(['pub /other', 'sub /chatter']);
  });

  it('formats rates, undelivered and unknown values', () => {
    const rows = topicEndpoints(chatter);
    expect(endpointHz(rows[3]!)).toBe('10.0 Hz');
    expect(endpointHz(rows[2]!)).toBe('届いていません');
    expect(endpointBandwidth(rows[0]!)).toBe('—');
    expect(endpointHz({ hz: null, delivered: true })).toBe('—');
  });

  it('labels the basis and explains theoretical values', () => {
    expect(basisLabel('theoretical')).toBe('理論値');
    expect(basisLabel('configured')).toBe('パラメータ');
    expect(basisLabel('measured')).toBe('実測');
    expect(basisLabel('probe')).toBe('probe');
    expect(basisHelp('theoretical')).toContain('受信側のノードの中で数えた値ではありません');
  });

  it('expands topics one by one or all at once', () => {
    expect([...toggleTopic(new Set(), '/a')]).toEqual(['/a']);
    expect(toggleTopic(new Set(['/a']), '/a').size).toBe(0);
    expect([...toggleAllTopics(new Set(['/a']), ['/a', '/b'])]).toEqual(['/a', '/b']);
    expect(toggleAllTopics(new Set(['/a', '/b']), ['/a', '/b']).size).toBe(0);
  });
});
