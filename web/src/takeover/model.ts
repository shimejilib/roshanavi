// Launch takeover banner / dialog text (pure): which banner to show, report and diff lines.

import type { DiffEntry, LeftoverState, ReportItem, TakeoverReport, TakeoverStatus } from '../api/takeoverTypes';
import { t, tDynamic, type MessageKey } from '../i18n';

export type BannerKind = 'leftovers' | 'error' | 'pending' | 'lost' | null;

export interface Dismissed {
  /** preview id of a pending re-import the user postponed (「あとで」). */
  pending: string | null;
  lost: boolean;
  leftovers: boolean;
}

export const NO_DISMISS: Dismissed = { pending: null, lost: false, leftovers: false };

/** The banners to show, most urgent first. */
export function banners(status: TakeoverStatus | null, leftovers: LeftoverState | null, dismissed: Dismissed): BannerKind[] {
  const out: BannerKind[] = [];
  if (leftovers && leftovers.count > 0 && !dismissed.leftovers) out.push('leftovers');
  if (!status || !status.active) return out;
  if (status.state === 'error' && status.error) out.push('error');
  if (status.pending && status.pending.preview_id !== dismissed.pending) out.push('pending');
  if (status.state === 'ready' && status.report?.suggest_whole && !dismissed.lost) out.push('lost');
  return out;
}

export function itemText(side: 'carried' | 'lost', item: ReportItem): string {
  const fallback: MessageKey = side === 'lost' ? 'takeover.lost.unknown' : 'takeover.carried.unknown';
  const text = tDynamic(`takeover.${side}.${item.code}`, fallback, { code: item.code, detail: item.detail ?? '' });
  const nodes = item.nodes && item.nodes.length > 0 ? ` (${t('takeover.nodes', { nodes: item.nodes.join(', ') })})` : '';
  return text + nodes;
}

export function restText(item: ReportItem): string {
  const reason = tDynamic(`import.reason.${item.code}`, 'import.reason.unknown', { code: item.code });
  return item.detail ? `${item.detail}: ${reason}` : reason;
}

export function noteText(code: string): string {
  return tDynamic(`takeover.note.${code}`, 'takeover.lost.unknown', { code });
}

export function entryText(entry: DiffEntry): string {
  if (entry.kind === 'rest') return t('takeover.kind.rest', { label: entry.label });
  if (entry.kind === 'whole') return t('takeover.kind.whole', { label: entry.label });
  return entry.label;
}

export function changedText(entry: DiffEntry): string {
  const fields = (entry.fields ?? []).map((f) => tDynamic(`takeover.field.${f}`, 'takeover.field.params'));
  return fields.length > 0 ? `${entryText(entry)}: ${fields.join('・')}` : entryText(entry);
}

export function launchLabel(status: Pick<TakeoverStatus, 'package' | 'launch_file'>): string {
  return `${status.package ?? '?'} / ${status.launch_file ?? '?'}`;
}

export function lostCount(report: TakeoverReport | null | undefined): number {
  return report?.lost.length ?? 0;
}
