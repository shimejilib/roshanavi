import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import type { GraphSnapshot } from '../api/types';
import { waitForTopicType } from './fixtures';

const graphWith = (topics: GraphSnapshot['topics']): GraphSnapshot =>
  ({ nodes: [], topics, edges: [], diagnostics: [], hash: '' });

describe('waitForTopicType (the qosFix sender takes the receiver type)', () => {
  afterEach(() => vi.restoreAllMocks());

  it('returns the type once the topic is on the graph (Lyrical: example_interfaces)', async () => {
    const graph = vi.spyOn(api, 'graph')
      .mockResolvedValueOnce(graphWith([]))
      .mockRejectedValueOnce(new Error('busy'))
      .mockResolvedValue(graphWith([{ name: '/tour_qos', types: ['example_interfaces/msg/String'] }]));
    await expect(waitForTopicType('/tour_qos', 1000, 1)).resolves.toBe('example_interfaces/msg/String');
    expect(graph).toHaveBeenCalledTimes(3);
  });

  it('falls back to std_msgs/msg/String when the receiver never shows up', async () => {
    vi.spyOn(api, 'graph').mockResolvedValue(graphWith([]));
    await expect(waitForTopicType('/tour_qos', 20, 1)).resolves.toBe('std_msgs/msg/String');
  });
});
