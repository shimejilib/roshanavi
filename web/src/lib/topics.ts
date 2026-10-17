// Topic-name helpers shared by graph, traffic and diagnostics.

const INFRA_TOPICS = new Set(['/rosout', '/parameter_events']);

/** Same rule as the backend (diagnostics.is_hidden_topic). */
export function isHiddenTopic(topic: string): boolean {
  return INFRA_TOPICS.has(topic) || topic.split('/').some((seg) => seg.startsWith('_'));
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
