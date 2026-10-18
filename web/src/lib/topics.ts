// Topic-name helpers shared by graph, traffic and diagnostics.

// `/events/write_split` is published by `ros2 bag record` itself while roshanavi records.
const INFRA_TOPICS = new Set(['/rosout', '/parameter_events', '/events/write_split']);

// Every lifecycle node publishes `<node>/transition_event`.
const LIFECYCLE_EVENT_SEGMENT = 'transition_event';

/** Same rule as the backend (diagnostics.is_hidden_topic): `/rosout` and friends, any `_` segment
 *  (`/x/_action/status`), lifecycle `<node>/transition_event`. */
export function isHiddenTopic(topic: string): boolean {
  const segments = topic.split('/').filter(Boolean);
  return (
    INFRA_TOPICS.has(topic) ||
    segments.some((seg) => seg.startsWith('_')) ||
    (segments.length > 1 && segments[segments.length - 1] === LIFECYCLE_EVENT_SEGMENT)
  );
}

/** Same rule as the backend (diagnostics.is_hidden_node): ROS hides nodes named `_...`
 *  (`_ros2cli_daemon_0_...`, the transient `_ros2cli_<pid>`). */
export function isHiddenNode(nodeId: string): boolean {
  return (nodeId.split('/').pop() ?? '').startsWith('_');
}

/** `/a/b` -> `/ws/echo/a/b` with each segment URL-encoded. */
export function topicPath(prefix: string, topic: string): string {
  const segments = topic.split('/').filter(Boolean).map(encodeURIComponent);
  return `${prefix}/${segments.join('/')}`;
}

/** `std_msgs/msg/String` -> template URL, or null if not a msg type. */
export function templatePath(type: string): string | null {
  const match = /^([A-Za-z0-9_]+)\/msg\/([A-Za-z0-9_]+)$/.exec(type.trim());
  if (!match) return null;
  return `/api/types/${match[1]}/msg/${match[2]}/template`;
}
