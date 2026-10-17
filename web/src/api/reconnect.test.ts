import { describe, expect, it } from 'vitest';
import { BACKOFF_MAX_MS, BACKOFF_MIN_MS, nextBackoff, wsUrl } from './reconnect';
import { templatePath, topicPath } from '../lib/topics';

describe('reconnect helpers', () => {
  it('backs off exponentially up to a cap', () => {
    expect(nextBackoff(0)).toBe(BACKOFF_MIN_MS);
    expect(nextBackoff(BACKOFF_MIN_MS)).toBe(BACKOFF_MIN_MS * 2);
    expect(nextBackoff(BACKOFF_MAX_MS)).toBe(BACKOFF_MAX_MS);
  });

  it('builds ws urls from the page location', () => {
    expect(wsUrl('/ws/live', { protocol: 'http:', host: 'localhost:5173' })).toBe('ws://localhost:5173/ws/live');
    expect(wsUrl('/ws/live', { protocol: 'https:', host: 'lab' })).toBe('wss://lab/ws/live');
  });

  it('encodes topic paths and template urls', () => {
    expect(topicPath('/ws/echo', '/robot 1/scan')).toBe('/ws/echo/robot%201/scan');
    expect(templatePath('std_msgs/msg/String')).toBe('/api/types/std_msgs/msg/String/template');
    expect(templatePath('bad type')).toBeNull();
  });
});
