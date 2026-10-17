// Which start / stop / restart actions a map node offers, and the confirm text (pure).
//
// Only what roshanavi started can be controlled: launcher targets (mine /
// dependency / persistent dummies) via the process manager, and inject jobs
// (virtual `dummy:<job>` nodes). Foreign nodes are never signalled.

import type { GraphNode, Target, TargetSpec } from '../api/types';
import { t, type MessageKey } from '../i18n';
import { isAlive } from '../launcher/status';

export type ControlAction = 'start' | 'stop' | 'restart';

export type NodeControl =
  | { kind: 'job'; jobId: string; actions: ControlAction[] }
  | { kind: 'target'; target: Target; actions: ControlAction[] }
  | { kind: 'none'; reason: string };

export function nodeControl(node: GraphNode | undefined, targets: readonly Target[]): NodeControl {
  if (!node) return { kind: 'none', reason: t('control.notOwned') };
  if (node.job_id) return { kind: 'job', jobId: node.job_id, actions: ['stop'] };
  const target = node.target_id ? targets.find((tg) => tg.id === node.target_id) : undefined;
  if (!target) return { kind: 'none', reason: t('control.notOwned') };
  if (target.status === 'invalid') return { kind: 'target', target, actions: [] };
  const actions: ControlAction[] = isAlive(target) ? ['stop', 'restart'] : ['start'];
  return { kind: 'target', target, actions };
}

/** Every graph node that runs in the target's process tree (they stop together). */
export function affectedNodes(target: Target, fallbackNode: string): string[] {
  const nodes = (target.nodes ?? []).map((n) => n.node).sort();
  return nodes.length > 0 ? nodes : [fallbackNode];
}

function launchFile(target: Target): string | null {
  return target.kind === 'launch' ? ((target.spec as TargetSpec).launch_file ?? null) : null;
}

/** Plain-language confirmation for stop / restart; null when no confirm is needed. */
export function confirmText(action: ControlAction, control: NodeControl, nodeId: string): string | null {
  if (action === 'start' || control.kind === 'none') return null;
  if (control.kind === 'job') return null; // a job stops only itself
  const nodes = affectedNodes(control.target, nodeId);
  const list = nodes.join(', ');
  if (action === 'restart') {
    return nodes.length > 1 ? t('control.confirmRestart', { n: nodes.length, nodes: list }) : null;
  }
  const file = launchFile(control.target);
  if (file) return t('control.confirmLaunch', { file, n: nodes.length, nodes: list });
  if (nodes.length > 1) return t('control.confirmGroup', { target: control.target.id, n: nodes.length, nodes: list });
  return t('control.confirmSingle', { node: nodeId });
}

export function actionLabel(action: ControlAction, control: NodeControl): string {
  if (action === 'stop' && control.kind === 'job') return t('control.stopJob');
  return t(`control.${action}` as MessageKey);
}
