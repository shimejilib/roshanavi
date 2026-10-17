// 詳細計測モード: texts and per-node rows from the tracing status and traffic entries (pure).

import type { TrafficEntry } from '../api/types';
import type { Behind, CallbackMs, SubscriberTrace, TracingStatus, UnsupportedNode, UnsupportedReason } from '../api/tracingTypes';
import { t, tDynamic, type MessageKey } from '../i18n';
import { formatBytes, formatHz, formatMs } from '../lib/format';

/** Benchmark summary shown in the explanation dialog (docs/design/measurement.md, measured). */
export const BENCH_SUMMARY =
  '100 Hz × 10 トピック (毎秒 1,000 メッセージ・約 6,000 件の記録) で、計測されるノードの CPU の増加は測定のばらつき (±2%) の範囲内、遅延は +5 µs 程度。roshanavi 側は CPU 約 16% (解析 13% + LTTng のデーモン 3%)、ディスク 1 MB 未満、取りこぼし 0。720p 画像 30 Hz では対象ノードへの影響は見えず、roshanavi 側は約 6%。';

/** Why the toggle is disabled (install guidance etc.), or null when it can be used. */
export function tracingUnavailableText(s: TracingStatus | null | undefined): string | null {
  if (!s) return null;
  if (s.available) return null;
  if (s.reason === 'failed') return t('tracing.unavailable.failed', { message: s.error?.message ?? '' });
  return tDynamic(`tracing.unavailable.${s.reason ?? 'unknown'}`, 'tracing.unavailable.unknown');
}

function percent(value: number | null | undefined): string {
  return value == null ? '—' : `${value.toFixed(1)}%`;
}

/** One-line status while the mode is on. */
export function tracingStatusText(s: TracingStatus): string {
  if (!s.receiving) return t('tracing.status.waiting');
  return t('tracing.status', {
    sec: Math.round(s.active_sec ?? 0),
    events: s.events_per_sec == null ? '—' : Math.round(s.events_per_sec).toLocaleString('ja-JP'),
    discarded: s.discarded.toLocaleString('ja-JP'),
    disk: formatBytes(s.disk_bytes),
    cpu: percent(s.cpu_percent.total),
  });
}

export function cpuHelp(s: TracingStatus): string {
  const c = s.cpu_percent;
  return t('tracing.status.cpuHelp', { server: percent(c.server), worker: percent(c.worker), lttng: percent(c.lttng) });
}

export function unsupportedReasonText(reason: UnsupportedReason): string {
  return t(`tracing.reason.${reason}` as MessageKey);
}

export function behindText(b: Behind): string {
  const main = t('tracing.behind', { incoming: formatHz(b.incoming_hz), processed: formatHz(b.processed_hz) });
  return b.cb_avg_ms == null ? main : `${main} ${t('tracing.behindCb', { ms: formatMs(b.cb_avg_ms) })}`;
}

export function behindHelp(b: Behind): string {
  return t(b.basis === 'sent' ? 'tracing.behind.sent' : 'tracing.behind.received');
}

export function cbText(cb: CallbackMs | null | undefined): string {
  if (!cb) return '—';
  return t('tracing.cbStats', { avg: formatMs(cb.avg), p95: formatMs(cb.p95), max: formatMs(cb.max) });
}

export interface TraceCells {
  recv: string;
  processed: string;
  cb: string;
  /** Explains a missing processed / time value (rclpy). */
  note: string | null;
}

/** Traced endpoint whose window does not hold enough events yet (< 2, same rule as the probe). */
function isMeasuring(trace: SubscriberTrace): boolean {
  return trace.hz_recv == null && trace.hz_processed == null;
}

function measuringCells(): TraceCells {
  const text = t('tracing.measuring');
  return { recv: text, processed: text, cb: '—', note: null };
}

/** 受信 / 処理 / 処理時間 of a traced subscriber row, or null when it is not traced. */
export function traceCells(trace: SubscriberTrace | undefined, basis: string): TraceCells | null {
  if (!trace || trace.lang === undefined) return null;
  if (basis !== 'measured') return basis === 'theoretical' && isMeasuring(trace) ? measuringCells() : null;
  const py = trace.lang === 'py';
  return {
    recv: trace.hz_recv == null ? '—' : formatHz(trace.hz_recv),
    processed: py ? t('tracing.notMeasured') : trace.hz_processed == null ? '—' : formatHz(trace.hz_processed),
    cb: py ? t('tracing.notMeasured') : cbText(trace.cb_ms),
    note: py ? t('tracing.pyNoCallback') : null,
  };
}

export interface NodeTraceRow {
  topic: string;
  cells: TraceCells;
  symbol: string | null;
  behind: Behind | null;
}

/** Traced subscriptions of one node, by topic (right pane). */
export function nodeTraceRows(entries: Iterable<TrafficEntry>, node: string): NodeTraceRow[] {
  const rows: NodeTraceRow[] = [];
  for (const entry of entries) {
    for (const sub of entry.subscribers ?? []) {
      if (sub.node !== node) continue;
      const cells = traceCells(sub, sub.basis);
      if (cells) rows.push({ topic: entry.topic, cells, symbol: sub.symbol ?? null, behind: sub.behind ?? null });
    }
  }
  return rows.sort((a, b) => a.topic.localeCompare(b.topic));
}

export function unsupportedFor(s: TracingStatus | null | undefined, node: string): UnsupportedNode | undefined {
  return s?.active ? s.unsupported.find((u) => u.node === node) : undefined;
}
