// Bulk start / stop / restart of the selected node-list rows, and the confirm text (pure).
//
// Launcher targets are acted on once each, whatever number of their nodes is
// selected; every node of a stopped target stops with it, which the confirm
// dialog lists (same rule as the map: graph/nodeControl.affectedNodes).
// Lifecycle nodes roshanavi did not start are switched with lifecycle
// transitions instead (activate / deactivate); they are never signalled.

import type { LifecycleGoal, NodeListResponse, NodeRow } from '../api/nodeListTypes';
import type { Target } from '../api/types';
import { affectedNodes, type ControlAction } from '../graph/nodeControl';
import { t } from '../i18n';
import { isAlive } from '../launcher/status';

export interface TargetStep {
  targetId: string;
  label: string;
  /** Every node of this target that the action stops (stop / restart). */
  nodes: string[];
}

export interface LifecycleStep {
  node: string;
  goal: LifecycleGoal;
  external: boolean;
}

export interface BulkPlan {
  action: ControlAction;
  targets: TargetStep[];
  lifecycle: LifecycleStep[];
  /** Nodes that stop although they were not selected (same process / launch). */
  alsoStopped: string[];
  skipped: { name: string; reason: string }[];
}

function targetLabel(target: Target): string {
  const spec = target.spec as { launch_file?: string; name?: string; executable?: string };
  if (target.kind === 'launch' && spec.launch_file) return t('nodes.bulk.launchLabel', { file: spec.launch_file });
  return target.id;
}

function targetApplies(action: ControlAction, target: Target): string | null {
  if (target.status === 'invalid') return t('nodes.skip.invalid');
  if (action === 'start') return isAlive(target) ? t('nodes.skip.running') : null;
  return isAlive(target) ? null : t('nodes.skip.stopped');
}

function lifecycleGoal(action: ControlAction, row: NodeRow): LifecycleGoal | string {
  const state = row.lifecycle?.state ?? null;
  if (action === 'restart') return t('nodes.skip.lifecycleRestart');
  if (action === 'start') return state === 'active' ? t('nodes.skip.running') : 'active';
  return state === 'active' ? 'inactive' : t('nodes.skip.notActive');
}

export function planBulk(action: ControlAction, selected: readonly NodeRow[], targets: readonly Target[]): BulkPlan {
  const plan: BulkPlan = { action, targets: [], lifecycle: [], alsoStopped: [], skipped: [] };
  const seen = new Set<string>();
  for (const row of selected) {
    if (row.control === 'lifecycle' && row.node) {
      const goal = lifecycleGoal(action, row);
      if (goal === 'active' || goal === 'inactive') plan.lifecycle.push({ node: row.node, goal, external: row.role === 'other' });
      else plan.skipped.push({ name: row.name, reason: goal });
      continue;
    }
    const target = row.target_id ? targets.find((tg) => tg.id === row.target_id) : undefined;
    if (!target || row.control !== 'target') {
      plan.skipped.push({ name: row.name, reason: t('nodes.skip.notControllable') });
      continue;
    }
    if (seen.has(target.id)) continue;
    seen.add(target.id);
    const reason = targetApplies(action, target);
    if (reason) {
      plan.skipped.push({ name: row.name, reason });
      continue;
    }
    const nodes = action === 'start' ? [] : affectedNodes(target, row.node ?? row.name);
    plan.targets.push({ targetId: target.id, label: targetLabel(target), nodes });
  }
  const chosen = new Set(selected.map((r) => r.node).filter(Boolean));
  plan.alsoStopped = plan.targets.flatMap((s) => s.nodes).filter((n) => !chosen.has(n)).sort();
  return plan;
}

/**
 * Plan from one node-list snapshot: the selected rows and the targets they refer to come from
 * the same response, so a row shown as stopped is never planned against a target state from
 * another source (issue The websocket could still say "running" right after a stop).
 */
export function planFromSnapshot(action: ControlAction, snapshot: Pick<NodeListResponse, 'rows' | 'targets'>, selected: ReadonlySet<string>): BulkPlan {
  const rows = snapshot.rows.filter((r) => selected.has(r.key));
  return planBulk(action, rows, snapshot.targets ?? []);
}

export function isEmptyPlan(plan: BulkPlan): boolean {
  return plan.targets.length === 0 && plan.lifecycle.length === 0;
}

const ACTION_KEYS = { start: 'nodes.bulk.start', stop: 'nodes.bulk.stop', restart: 'nodes.bulk.restart' } as const;

/** Plain-language confirmation listing everything that will start / stop. */
export function bulkConfirmText(plan: BulkPlan): string {
  const lines: string[] = [];
  if (plan.targets.length > 0) {
    lines.push(t(ACTION_KEYS[plan.action], { n: plan.targets.length }));
    for (const step of plan.targets) {
      lines.push(step.nodes.length > 0 ? `・${step.label}: ${step.nodes.join(', ')}` : `・${step.label}`);
    }
  }
  if (plan.alsoStopped.length > 0) {
    lines.push(t('nodes.bulk.alsoStopped', { n: plan.alsoStopped.length, nodes: plan.alsoStopped.join(', ') }));
  }
  if (plan.lifecycle.length > 0) {
    const key = plan.lifecycle[0]?.goal === 'active' ? 'nodes.bulk.lifecycleOn' : 'nodes.bulk.lifecycleOff';
    lines.push(t(key, { n: plan.lifecycle.length, nodes: plan.lifecycle.map((s) => s.node).join(', ') }));
    if (plan.lifecycle.some((s) => s.external)) lines.push(t('nodes.bulk.lifecycleExternal'));
  }
  if (plan.skipped.length > 0) {
    lines.push(t('nodes.bulk.skipped', { items: plan.skipped.map((s) => `${s.name} (${s.reason})`).join(', ') }));
  }
  return lines.join('\n');
}
