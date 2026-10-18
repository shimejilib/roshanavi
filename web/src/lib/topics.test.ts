import { describe, expect, it } from 'vitest';
import { isHiddenNode, isHiddenTopic } from './topics';

describe('isHiddenTopic', () => {
  it('hides infrastructure topics, including the one rosbag2 publishes while recording', () => {
    expect(isHiddenTopic('/rosout')).toBe(true);
    expect(isHiddenTopic('/parameter_events')).toBe(true);
    expect(isHiddenTopic('/events/write_split')).toBe(true);
  });
  it('hides topics with a segment starting with an underscore (action internals)', () => {
    expect(isHiddenTopic('/nav/_action/status')).toBe(true);
    expect(isHiddenTopic('/fibonacci/_action/feedback')).toBe(true);
  });
  it('hides lifecycle transition events', () => {
    expect(isHiddenTopic('/lc_talker/transition_event')).toBe(true);
    expect(isHiddenTopic('/ns/lc/transition_event')).toBe(true);
  });
  it('keeps ordinary topics', () => {
    expect(isHiddenTopic('/chatter')).toBe(false);
    expect(isHiddenTopic('/my/events/write_split')).toBe(false);
    expect(isHiddenTopic('/transition_event_log')).toBe(false);
  });
});

describe('isHiddenNode', () => {
  it('hides the ros2 CLI daemon and its transient nodes', () => {
    expect(isHiddenNode('/_ros2cli_daemon_0_1a2b3c')).toBe(true);
    expect(isHiddenNode('/_ros2cli_12345')).toBe(true);
    expect(isHiddenNode('/ns/_ros2cli_9')).toBe(true);
  });
  it('keeps user nodes', () => {
    expect(isHiddenNode('/talker')).toBe(false);
    expect(isHiddenNode('/ns/my_ros2cli')).toBe(false);
    expect(isHiddenNode('dummy:abc')).toBe(false);
  });
});
