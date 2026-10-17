// What the tours create through the API (and remove again). Every id starts with `tour_`.

import { api } from '../api/client';
import type { FunctionSpec } from '../api/functionTypes';
import type { DummySpec, GraphSnapshot, TargetSpec } from '../api/types';
import type { Baseline, Fixture } from './types';

export const QOS_TOPIC = '/tour_qos';
export const QOS_PUB = 'tour_qos_pub';
export const QOS_SUB = 'tour_qos_sub';
export const SHOUT_IN = '/tour_in';
export const SHOUT_OUT = '/tour_out';
export const SHOUT_NODE = 'tour_shout';
export const CHATTER_SOURCE = 'tour_chatter_src';

const target = (id: string): Fixture => ({ kind: 'target', id });

/** Removes a leftover of an earlier, interrupted tour; "not found" is the normal case. */
async function removeQuietly(id: string): Promise<void> {
  try {
    await api.removeTarget(id);
  } catch {
    // nothing to remove
  }
}

export async function removeFixtures(fixtures: readonly Fixture[]): Promise<string[]> {
  const failed: string[] = [];
  for (const f of fixtures) {
    try {
      if (f.kind === 'target') await api.removeTarget(f.id);
      else await api.deleteScenario(f.id);
    } catch (err) {
      // Already gone (the learner removed it) is fine; anything else is reported.
      const status = (err as { status?: number }).status;
      if (status !== 404) failed.push(f.id);
    }
  }
  return failed;
}

/** Ids that exist now: the tour never touches them. */
export async function takeBaseline(): Promise<Baseline> {
  const [targets, scenarios, runs] = await Promise.all([api.targets(), api.scenarios(), api.scenarioRuns()]);
  return {
    targets: targets.map((tg) => tg.id),
    scenarios: scenarios.items.filter((i) => i.source === 'project').map((i) => i.id),
    runId: runs.current?.run_id ?? runs.runs[0]?.run_id ?? null,
  };
}

/** Something that publishes `topic`, when nobody does (the demo project has its own talker). */
export async function ensurePublisher(graph: GraphSnapshot | null, topic: string, id: string, text: string): Promise<Fixture[]> {
  if (graph?.edges.some((e) => e.topic === topic && e.dir === 'pub')) return [];
  await removeQuietly(id);
  const spec: DummySpec = {
    id, name: id, topic, type: 'std_msgs/msg/String', kind: 'string', mode: 'periodic',
    payload: { data: text }, rate_hz: 1, qos: { reliability: 'reliable', durability: 'volatile', depth: 10 }, autostart: true,
  };
  await api.addDummy(spec, true);
  return [target(id)];
}

/** A sender that gives up when the receiver wants delivery guarantees (BEST_EFFORT vs RELIABLE). */
export async function prepareQosPair(): Promise<Fixture[]> {
  const created: Fixture[] = [];
  try {
    await Promise.all([removeQuietly(QOS_PUB), removeQuietly(QOS_SUB)]);
    const pub: DummySpec = {
      id: QOS_PUB, name: QOS_PUB, topic: QOS_TOPIC, type: 'std_msgs/msg/String', kind: 'string', mode: 'periodic',
      payload: { data: 'hello' }, rate_hz: 2, qos: { reliability: 'best_effort', durability: 'volatile', depth: 10 }, autostart: true,
    };
    await api.addDummy(pub, true);
    created.push(target(QOS_PUB));
    // demo_nodes_cpp's listener subscribes with the ROS default (RELIABLE) to `chatter`.
    const sub: TargetSpec = {
      id: QOS_SUB, kind: 'run', package: 'demo_nodes_cpp', executable: 'listener', name: QOS_SUB,
      remaps: { chatter: QOS_TOPIC }, role: 'dependency', args: [], params: {}, autostart: false, auto_restart: false,
    };
    await api.addTarget(sub, true);
    created.push(target(QOS_SUB));
    return created;
  } catch (err) {
    await removeFixtures(created);
    throw err;
  }
}

/** The function node the scenario tour records against: /tour_in -> shout -> /tour_out. */
export async function prepareShoutNode(): Promise<Fixture[]> {
  await removeQuietly(SHOUT_NODE);
  const spec: FunctionSpec = {
    id: SHOUT_NODE, name: SHOUT_NODE, module: 'roshanavi_examples.logic', function: 'shout', call: 'on_message',
    inputs: [{ topic: SHOUT_IN, kind: 'string' }], output: { topic: SHOUT_OUT, kind: 'string' }, autostart: true,
  };
  await api.addFunction(spec, true);
  return [target(SHOUT_NODE)];
}
