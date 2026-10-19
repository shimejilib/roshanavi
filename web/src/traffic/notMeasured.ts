// Topics roshanavi does not measure (images and point clouds by default, or switched off) are
// never shown as 受信なし / 未受信 / 分けられない: they say 計測していません (pure).
// With 詳細計測モード the Hz of such a topic comes from the trace (send count at the publishers);
// the bandwidth cannot be measured that way.

import type { TrafficEntry } from '../api/types';
import { t } from '../i18n';
import { formatHz } from '../lib/format';

export const NO_VALUE = '—';

type MeasureFields = Pick<TrafficEntry, 'status'>;

export function isNotMeasured(entry: MeasureFields | undefined): boolean {
  return entry?.status === 'not_monitored';
}

/** 「計測していません (画像などの重いデータは既定でオフ)」; the plain form for a light topic someone switched off. */
export function notMeasuredText(entry: Pick<TrafficEntry, 'heavy'>): string {
  return entry.heavy ? t('monitor.off.heavy') : t('monitor.off');
}

/** Heavy data without 詳細計測モード: tell where its Hz can be seen. */
export function showTraceHint(entry: Pick<TrafficEntry, 'heavy'>, tracingActive: boolean): boolean {
  return entry.heavy === true && !tracingActive;
}

/** Send rate of the whole topic counted by the trace, or null (not all publishers covered / mode off). */
export function tracedTopicHz(entry: Pick<TrafficEntry, 'hz_traced'>): number | null {
  return entry.hz_traced ?? null;
}

/** Hz cell of a topic row: the trace's rate, never `0 Hz` for something nobody measured. */
export function notMeasuredHz(entry: Pick<TrafficEntry, 'hz_traced'>): string {
  const hz = tracedTopicHz(entry);
  return hz == null ? NO_VALUE : formatHz(hz);
}

/** Bandwidth cell of a not measured topic: with a traced Hz it says why there is no number. */
export function notMeasuredBandwidth(entry: Pick<TrafficEntry, 'hz_traced'>): string {
  return tracedTopicHz(entry) == null ? NO_VALUE : t('monitor.noBandwidth');
}
