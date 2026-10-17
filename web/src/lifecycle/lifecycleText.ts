// Plain-language labels and confirmations for lifecycle transitions (pure, docs/design/launcher.md).

import type { LifecycleInfo, LifecycleTransition } from '../api/nodeListTypes';
import { t, type MessageKey } from '../i18n';

/** Order in which transition buttons are shown. */
export const TRANSITION_ORDER: readonly LifecycleTransition[] = ['configure', 'activate', 'deactivate', 'cleanup'];

export function transitionLabel(label: LifecycleTransition): string {
  return t(`lifecycle.tr.${label}` as MessageKey);
}

export function transitionHelp(label: LifecycleTransition): string {
  return t(`lifecycle.trHelp.${label}` as MessageKey);
}

/** Transitions the node offers now, in display order. */
export function offeredTransitions(info: Pick<LifecycleInfo, 'transitions'>): LifecycleTransition[] {
  const offered = new Set(info.transitions.map((tr) => tr.label));
  return TRANSITION_ORDER.filter((label) => offered.has(label));
}

export function confirmTransitionText(node: string, label: LifecycleTransition, external: boolean): string {
  const lines = [t('lifecycle.confirmText', { node, action: transitionLabel(label) }), transitionHelp(label)];
  if (external) lines.push(t('lifecycle.confirmExternal'));
  return lines.join('\n');
}
