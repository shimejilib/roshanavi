import { describe, expect, it } from 'vitest';
import { isHiddenTopic } from './topics';

describe('isHiddenTopic', () => {
  it('hides infrastructure topics, including the one rosbag2 publishes while recording', () => {
    expect(isHiddenTopic('/rosout')).toBe(true);
    expect(isHiddenTopic('/parameter_events')).toBe(true);
    expect(isHiddenTopic('/events/write_split')).toBe(true);
  });
  it('hides topics with a segment starting with an underscore', () => {
    expect(isHiddenTopic('/nav/_action/status')).toBe(true);
  });
  it('keeps ordinary topics', () => {
    expect(isHiddenTopic('/chatter')).toBe(false);
    expect(isHiddenTopic('/my/events/write_split')).toBe(false);
  });
});
