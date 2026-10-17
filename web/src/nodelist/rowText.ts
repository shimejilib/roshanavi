// Display text for node-list rows: origin, status, role, why a row cannot be selected (pure).

import type { NodeGroup, NodeRow } from '../api/nodeListTypes';
import { t, tDynamic, type MessageKey } from '../i18n';

export function originText(row: Pick<NodeRow, 'origin'>): string {
  const o = row.origin;
  if (o.kind === 'external') return t('nodes.origin.external');
  if (o.kind === 'dummy') return o.topic ? t('nodes.origin.dummy', { topic: o.topic }) : t('nodes.origin.dummyNoTopic');
  if (o.kind === 'transform') return o.topic ? t('nodes.origin.transform', { topic: o.topic }) : t('nodes.origin.transformNoTopic');
  if (o.kind === 'class') return o.topic ? t('nodes.origin.class', { topic: o.topic }) : t('nodes.origin.classNoTopic');
  if (o.kind === 'function') return o.topic ? t('nodes.origin.function', { topic: o.topic }) : t('nodes.origin.functionNoTopic');
  const base = o.kind === 'launch' ? `${o.package ?? '?'} / ${o.launch_file ?? '?'}` : `${o.package ?? '?'} / ${o.executable ?? '?'}`;
  return o.imported_from ? `${base} ${t('nodes.origin.imported', { file: o.imported_from })}` : base;
}

export function roleText(row: Pick<NodeRow, 'role'>): string {
  return t(`nodes.role.${row.role}` as MessageKey);
}

/** Target status for owned rows; 「実行中 (外部)」 for nodes roshanavi did not start. */
export function statusText(row: Pick<NodeRow, 'status' | 'target_id' | 'exit_code'>): string {
  if (!row.target_id) return t('nodes.status.externalRunning');
  return tDynamic(`launcher.status.${row.status}`, 'nodes.status.unknown', { code: row.exit_code ?? '?' });
}

export function lifecycleStateText(state: string | null | undefined): string {
  if (!state) return t('lifecycle.state.unknown');
  return tDynamic(`lifecycle.state.${state}`, 'lifecycle.state.other', { state });
}

/** Tooltip of a disabled checkbox (and the reason line under the name). */
export function disabledReason(row: Pick<NodeRow, 'control' | 'reason' | 'problem'>): string | null {
  if (row.control !== 'none') return null;
  if (row.reason === 'invalid') return t('nodes.reason.invalid', { problem: row.problem ?? '' });
  return t('nodes.reason.external');
}

export function confidenceText(row: Pick<NodeRow, 'confidence' | 'target_id' | 'node'>): string {
  if (!row.target_id) return '—';
  if (!row.node) return t('nodes.mapping.none');
  return row.confidence === 'heuristic' ? t('launcher.confidence.heuristic') : t('launcher.confidence.exact');
}

export function groupTitle(group: NodeGroup): string {
  return group.kind === 'launch'
    ? t('nodes.group.launch', { file: group.label, n: group.nodes.length })
    : t('nodes.group.process', { target: group.label, n: group.nodes.length });
}
