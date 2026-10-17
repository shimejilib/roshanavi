// Topic presets for recording (pure, unit-tested).

import type { GraphSnapshot, Job } from '../api/types';
import { isHiddenTopic } from '../lib/topics';

/** Topics fed by running injections / browser captures, with their CameraInfo / AudioInfo. */
export function inputTopics(jobs: readonly Job[]): string[] {
  const topics = new Set<string>();
  for (const job of jobs) {
    if (job.state !== 'running' || !job.topic) continue;
    topics.add(job.topic);
    for (const extra of job.companions ?? []) topics.add(extra);
  }
  return [...topics].sort();
}

/** Topics published by nodes marked "mine" in the Launcher (internal topics excluded). */
export function myNodeOutputs(graph: GraphSnapshot | null): string[] {
  if (!graph) return [];
  const mine = new Set(graph.nodes.filter((n) => n.role === 'mine').map((n) => n.id));
  const topics = graph.edges.filter((e) => e.dir === 'pub' && mine.has(e.node) && !isHiddenTopic(e.topic)).map((e) => e.topic);
  return [...new Set(topics)].sort();
}

export function toggle(selected: readonly string[], topic: string): string[] {
  return selected.includes(topic) ? selected.filter((x) => x !== topic) : [...selected, topic].sort();
}

export function addAll(selected: readonly string[], topics: readonly string[]): string[] {
  return [...new Set([...selected, ...topics])].sort();
}
