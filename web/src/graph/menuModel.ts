// Which right-click menu items the map offers, per target and node role (pure, docs/design/ui.md).
//
// Only what roshanavi started can be stopped or rebuilt; nodes it did not start
// ("external") get read-only items. Disabled items carry a plain-language reason.

import type { GraphNode, Job, Target, TargetSpec, TrafficEntry } from '../api/types';
import { t, type MessageKey } from '../i18n';
import { nodeControl, type ControlAction } from './nodeControl';

export type MenuTarget =
  | { kind: 'node'; nodeId: string }
  | { kind: 'topic'; topic: string }
  | { kind: 'edge'; topic: string; node: string; dir: 'pub' | 'sub' }
  | { kind: 'blank' };

export type MenuAction =
  | ControlAction
  | 'logs' | 'editTarget' | 'buildRestart' | 'params' | 'isolate'
  | 'pause' | 'resume' | 'editDummy' | 'editTransform' | 'editFunction' | 'exportLaunch' | 'details' | 'lifecycle'
  | 'view' | 'tryInject' | 'createInput' | 'createTransform' | 'record' | 'monitorOn' | 'monitorOff' | 'typeDef' | 'flowOnly'
  | 'qosDetails' | 'whyNotDelivered'
  | 'addTopic' | 'launchNode' | 'relayout' | 'fit';

export interface MenuItem {
  action: MenuAction;
  label: string;
  enabled: boolean;
  reason?: string;
  danger?: boolean;
}

export interface MenuContext {
  node?: GraphNode;
  targets: readonly Target[];
  jobs: readonly Job[];
  /** Workspace packages with sources (can be built). */
  buildable: ReadonlySet<string>;
  traffic?: TrafficEntry;
  topicTypes?: readonly string[];
  /** Current `paused` parameter of a persistent dummy; undefined while unknown (both items are then offered). */
  dummyPaused?: boolean;
}

/** owned = launcher target (mine / dependency), dummy = persistent dummy, transform = 変換ノード, job = inject job. */
export type MenuRole = 'owned' | 'dummy' | 'transform' | 'function' | 'job' | 'external';

export function menuRole(node: GraphNode | undefined, targets: readonly Target[]): MenuRole {
  if (!node) return 'external';
  if (node.job_id) return 'job';
  const target = node.target_id ? targets.find((tg) => tg.id === node.target_id) : undefined;
  if (!target) return 'external';
  if (target.kind === 'dummy' || target.kind === 'transform' || target.kind === 'function') return target.kind;
  return 'owned';
}

const item = (action: MenuAction, enabled = true, reason?: string): MenuItem => ({
  action,
  label: t(`menu.${action}` as MessageKey),
  enabled,
  reason: enabled ? undefined : reason,
  danger: action === 'stop',
});

function controlItems(node: GraphNode | undefined, targets: readonly Target[]): MenuItem[] {
  const control = nodeControl(node, targets);
  if (control.kind === 'none') return [item('stop', false, control.reason)];
  if (control.actions.length === 0) return [item('start', false, t('menu.reason.invalid'))];
  return control.actions.map((action) => item(action));
}

function buildItem(target: Target | undefined, buildable: ReadonlySet<string>): MenuItem {
  const pkg = target && (target.kind === 'run' || target.kind === 'launch') ? (target.spec as TargetSpec).package : null;
  return item('buildRestart', pkg !== null && buildable.has(pkg), t('menu.reason.notWorkspace'));
}

function dummyPauseItems(paused: boolean | undefined): MenuItem[] {
  if (paused === undefined) return [item('pause'), item('resume')];
  return [paused ? item('resume') : item('pause')];
}

function nodeItems(ctx: MenuContext): MenuItem[] {
  const items = baseNodeItems(ctx);
  return ctx.node?.lifecycle ? [...items, item('lifecycle')] : items;
}

function baseNodeItems(ctx: MenuContext): MenuItem[] {
  const { node, targets } = ctx;
  const role = menuRole(node, targets);
  const target = node?.target_id ? targets.find((tg) => tg.id === node.target_id) : undefined;
  const controls = controlItems(node, targets);
  if (role === 'owned') {
    return [...controls, item('logs'), item('editTarget'), buildItem(target, ctx.buildable), item('params'), item('isolate')];
  }
  if (role === 'dummy') {
    return [...controls, ...dummyPauseItems(ctx.dummyPaused), item('editDummy'), item('exportLaunch'), item('logs'), item('params'), item('isolate')];
  }
  if (role === 'transform') {
    return [...controls, item('editTransform'), item('exportLaunch'), item('logs'), item('params'), item('isolate')];
  }
  if (role === 'function') {
    return [...controls, item('editFunction'), item('exportLaunch'), item('logs'), item('params'), item('isolate')];
  }
  if (role === 'job') {
    const job = ctx.jobs.find((j) => j.id === node?.job_id);
    const pausable = Boolean(job?.pausable) && job?.state === 'running';
    const pauseItem = job?.paused ? item('resume', pausable) : item('pause', pausable, t('menu.reason.notPausable'));
    return [
      ...controls,
      pauseItem,
      item('editDummy', false, t('menu.reason.jobFixed')),
      item('exportLaunch', false, t('menu.reason.jobFixed')),
      item('isolate'),
    ];
  }
  return [...controls, item('params'), item('isolate'), item('details')];
}

function topicItems(ctx: MenuContext): MenuItem[] {
  const monitored = ctx.traffic?.monitored ?? true;
  const singleType = (ctx.topicTypes?.length ?? 0) === 1;
  return [
    item('view'),
    item('tryInject'),
    item('createInput'),
    item('createTransform'),
    item('record'),
    monitored ? item('monitorOff', ctx.traffic !== undefined) : item('monitorOn'),
    item('typeDef', singleType, t('menu.reason.typeUnknown')),
    item('flowOnly'),
  ];
}

export function menuItems(target: MenuTarget, ctx: MenuContext): MenuItem[] {
  switch (target.kind) {
    case 'node':
      return nodeItems(ctx);
    case 'topic':
      return topicItems(ctx);
    case 'edge':
      return [item('qosDetails'), item('whyNotDelivered')];
    case 'blank':
      return [item('addTopic'), item('launchNode'), item('relayout'), item('fit')];
    default:
      return [];
  }
}

export function menuTitle(target: MenuTarget): string {
  switch (target.kind) {
    case 'node':
      return target.nodeId;
    case 'topic':
      return target.topic;
    case 'edge':
      return target.dir === 'pub' ? `${target.node} → ${target.topic}` : `${target.topic} → ${target.node}`;
    default:
      return t('menu.blankTitle');
  }
}
