import type { GraphSnapshot, TrafficEntry } from '../api/types';

export const NOW_MS = 1_700_000_000_000;

export function entry(topic: string, over: Partial<TrafficEntry> = {}): TrafficEntry {
  return {
    topic,
    type: 'std_msgs/msg/String',
    status: 'ok',
    monitored: true,
    collapsed: false,
    hz: 10,
    hz_basis: 'source',
    hz_recv: 10,
    hz_source: 10,
    bytes_per_sec: 1000,
    avg_size: 100,
    jitter_ms: 1,
    jitter_recv_ms: 1,
    dropped: 0,
    drop_ratio: 0,
    latency_ms: 0.5,
    last_seen: NOW_MS / 1000 - 0.2,
    total_count: 100,
    recent_count: 10,
    history: [10, 10],
    ...over,
  };
}

const QOS = { reliability: 'reliable', durability: 'volatile', depth: 10 };

export function chatterGraph(): GraphSnapshot {
  return {
    hash: 'h',
    nodes: [
      { id: '/talker', name: 'talker', namespace: '/', role: 'other' },
      { id: '/listener', name: 'listener', namespace: '/', role: 'other' },
    ],
    topics: [
      { name: '/chatter', types: ['std_msgs/msg/String'] },
      { name: '/rosout', types: ['rcl_interfaces/msg/Log'] },
    ],
    edges: [
      { node: '/talker', topic: '/chatter', dir: 'pub', qos: QOS },
      { node: '/listener', topic: '/chatter', dir: 'sub', qos: QOS },
      { node: '/talker', topic: '/rosout', dir: 'pub', qos: QOS },
      { node: '/listener', topic: '/rosout', dir: 'pub', qos: QOS },
    ],
    diagnostics: [],
  };
}

/** A heavy topic roshanavi does not subscribe to (the default for images). */
export function heavyOffEntry(topic = '/turtle_viz/image', over: Partial<TrafficEntry> = {}): TrafficEntry {
  return entry(topic, {
    type: 'sensor_msgs/msg/Image', status: 'not_monitored', monitored: false, heavy: true, hz: 0, bytes_per_sec: 0,
    avg_size: 0, jitter_ms: 0, jitter_recv_ms: 0, dropped: null, drop_ratio: null, latency_ms: null, last_seen: null,
    total_count: 0, recent_count: 0, history: [],
    publishers: [{ node: '/viz_a', hz: null, bps: null, basis: 'not_monitored' }, { node: '/viz_b', hz: null, bps: null, basis: 'not_monitored' }],
    subscribers: [{ node: '/consumer', hz: null, bps: null, basis: 'not_monitored', delivered: true, sources: ['/viz_a', '/viz_b'] }],
    ...over,
  });
}
