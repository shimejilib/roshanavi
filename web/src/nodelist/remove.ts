// Node-list delete (pure): which roshanavi registrations go, what stops with them, the
// confirm text. Rows roshanavi did not start (external nodes) are never deletable.

import type { NodeListResponse, NodeRow } from '../api/nodeListTypes';
import type { Target } from '../api/types';
import { affectedNodes } from '../graph/nodeControl';
import { t, tDynamic } from '../i18n';
import { isAlive } from '../launcher/status';

export interface RemoveStep {
  targetId: string;
  label: string;
  kind: string;
  running: boolean;
  /** Every node of this registration that stops (the same process / launch). */
  nodes: string[];
  takeover: boolean;
}

export interface RemovePlan {
  steps: RemoveStep[];
  /** Nodes that stop although their row was not selected. */
  alsoStopped: string[];
  skipped: { name: string; reason: string }[];
}

function label(target: Target): string {
  const spec = target.spec as { launch_file?: string };
  if (target.kind === 'launch' && spec.launch_file) return t('nodes.bulk.launchLabel', { file: spec.launch_file });
  return target.id;
}

export function planRemove(selected: readonly NodeRow[], targets: readonly Target[]): RemovePlan {
  const plan: RemovePlan = { steps: [], alsoStopped: [], skipped: [] };
  const seen = new Set<string>();
  for (const row of selected) {
    const target = row.target_id ? targets.find((tg) => tg.id === row.target_id) : undefined;
    if (!target) {
      plan.skipped.push({ name: row.name, reason: t('nodes.delete.external') });
      continue;
    }
    if (seen.has(target.id)) continue;
    seen.add(target.id);
    const running = isAlive(target);
    plan.steps.push({
      targetId: target.id,
      label: label(target),
      kind: target.kind,
      running,
      nodes: running ? affectedNodes(target, row.node ?? row.name) : [],
      takeover: Boolean((target.spec as { takeover?: boolean }).takeover),
    });
  }
  const chosen = new Set(selected.map((r) => r.node).filter(Boolean));
  plan.alsoStopped = [...new Set(plan.steps.flatMap((s) => s.nodes))].filter((n) => !chosen.has(n)).sort();
  return plan;
}

export function planRemoveFromSnapshot(snapshot: Pick<NodeListResponse, 'rows' | 'targets'>, selected: ReadonlySet<string>): RemovePlan {
  return planRemove(snapshot.rows.filter((r) => selected.has(r.key)), snapshot.targets ?? []);
}

function kindText(kind: string): string {
  return tDynamic(`nodes.delete.kind.${kind}`, 'nodes.delete.kind.run');
}

/** Plain-language confirmation: what goes, what stops together, and what is never deleted. */
export function removeConfirmText(plan: RemovePlan): string {
  const lines = [t('nodes.delete.intro', { n: plan.steps.length })];
  for (const step of plan.steps) {
    const nodes = step.nodes.length > 0 ? `: ${step.nodes.join(', ')}` : '';
    const running = step.running ? ` — ${t('nodes.delete.running')}` : '';
    lines.push(`・${step.label} (${kindText(step.kind)})${nodes}${running}`);
  }
  if (plan.alsoStopped.length > 0) {
    lines.push(t('nodes.delete.stopsTogether', { n: plan.alsoStopped.length, nodes: plan.alsoStopped.join(', ') }));
  }
  if (plan.skipped.length > 0) {
    lines.push(t('nodes.delete.skipped', { items: plan.skipped.map((s) => `${s.name} (${s.reason})`).join(', ') }));
  }
  lines.push('', t('nodes.delete.safety'));
  if (plan.steps.some((s) => s.takeover)) lines.push(t('nodes.delete.takeover'));
  lines.push(t('nodes.delete.undoHint'));
  return lines.join('\n');
}
