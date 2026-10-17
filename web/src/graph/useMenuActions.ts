// Runs a map context-menu action (everything except start / stop / restart,
// which go through useNodeControl for their confirmation dialogs).

import { api } from '../api/client';
import type { GraphNode, Target, TargetSpec } from '../api/types';
import { topicPath } from '../lib/topics';
import { useAppState } from '../state/AppState';
import { useLive } from '../state/LiveProvider';
import type { MenuAction, MenuTarget } from './menuModel';
import { nodeElementId, topicElementId } from './model';

export interface MapCommands {
  relayout: () => void;
  fit: () => void;
}

const BUILD_LOG_ID = '_build';

function targetOf(node: GraphNode | undefined, targets: readonly Target[]): Target | undefined {
  return node?.target_id ? targets.find((tg) => tg.id === node.target_id) : undefined;
}

/** Returns `run(action)`; it resolves when the action is done (rejects with an ApiError). */
export function useMenuActions(target: MenuTarget, commands: MapCommands): (action: MenuAction) => Promise<void> {
  const app = useAppState();
  const { live } = useLive();
  const node = target.kind === 'node' ? live.graph?.nodes.find((n) => n.id === target.nodeId) : undefined;
  const owner = targetOf(node, live.targets);
  const topic = target.kind === 'topic' || target.kind === 'edge' ? target.topic : '';
  const types = live.graph?.topics.find((tp) => tp.name === topic)?.types ?? [];

  const setPaused = async (paused: boolean) => {
    if (node?.job_id) await api.pauseInject(node.job_id, paused);
    else if (node) await api.setParameter(node.id, { name: 'paused', type: 'bool', value: paused });
  };

  const handlers: Partial<Record<MenuAction, () => unknown>> = {
    logs: () => owner && app.openLogs(owner.id),
    editTarget: () => owner && app.openLauncher({ kind: 'edit', targetId: owner.id }),
    buildRestart: async () => {
      if (!owner || owner.kind === 'dummy') return;
      await api.build((owner.spec as TargetSpec).package, true);
      app.openLogs(BUILD_LOG_ID);
    },
    params: () => node && app.openDialog({ kind: 'params', nodeId: node.id }),
    lifecycle: () => node && app.openDialog({ kind: 'lifecycle', nodeId: node.id }),
    isolate: () => node && app.setIsolation({ mode: 'io', elementId: nodeElementId(node.id) }),
    details: () => node && app.select({ kind: 'node', id: node.id }),
    pause: () => setPaused(true),
    resume: () => setPaused(false),
    editDummy: () => owner && app.openDialog({ kind: 'createInput', dummyId: owner.id }),
    exportLaunch: () => owner && app.openDialog({ kind: 'exportLaunch', dummyId: owner.id }),
    view: () => app.select({ kind: 'topic', id: topic }),
    tryInject: () => app.openInject(topic),
    createInput: () => app.openDialog({ kind: 'createInput', topic, type: types.length === 1 ? types[0] : undefined }),
    record: () => app.openRecord(topic),
    monitorOn: () => api.setMonitor(`${topicPath('/api/traffic', topic)}/monitor`, true),
    monitorOff: () => api.setMonitor(`${topicPath('/api/traffic', topic)}/monitor`, false),
    typeDef: () => types[0] && app.openDialog({ kind: 'interface', type: types[0] }),
    flowOnly: () => app.setIsolation({ mode: 'flow', elementId: topicElementId(topic) }),
    qosDetails: () => target.kind === 'edge' && app.openDialog({ kind: 'edge', topic, node: target.node, dir: target.dir }),
    whyNotDelivered: () => target.kind === 'edge' && app.openDialog({ kind: 'edge', topic, node: target.node, dir: target.dir }),
    addTopic: () => app.openDialog({ kind: 'createInput' }),
    launchNode: () => app.openLauncher({ kind: 'add' }),
    relayout: commands.relayout,
    fit: commands.fit,
  };

  return async (action: MenuAction) => {
    await handlers[action]?.();
  };
}
