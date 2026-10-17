import { describe, expect, it } from 'vitest';
import type { TracingStatus } from '../api/tracingTypes';
import type { SubscriberRate, TrafficEntry } from '../api/types';
import { applyLive, EMPTY_LIVE } from '../state/live';
import { basisLabel, displayBasis, topicEndpoints } from './endpoints';
import {
  behindText, cbText, nodeTraceRows, traceCells, tracingStatusText, tracingUnavailableText,
  unsupportedFor, unsupportedReasonText,
} from './tracing';

const STATUS: TracingStatus = {
  available: true, reason: null, active: true, active_sec: 12.4, receiving: true, error: null,
  events_per_sec: 1234.5, discarded: 0, disk_bytes: 1_200_000, parse_ms: 40, buffer_per_cpu: 4194304,
  skipped_chunks: 0, cpu_percent: { server: 1, worker: 10.5, lttng: 0.8, total: 12.3 }, restarts: 0,
  unsupported: [{ node: '/py', reason: 'rclpy', pid: null }], diagnostics: [],
};

const CB = { avg: 200.1, p95: 201, max: 205 };

function sub(over: Partial<SubscriberRate>): SubscriberRate {
  return { node: '/slow', hz: 5, bps: 50, basis: 'measured', delivered: true, sources: ['/talker'],
    hz_expected: 10, hz_recv: 5, hz_processed: 5, cb_ms: CB, lang: 'cpp', ...over };
}

function entry(subs: SubscriberRate[], topic = '/fast'): TrafficEntry {
  return { topic, type: 'std_msgs/msg/String', subscribers: subs, publishers: [] } as unknown as TrafficEntry;
}

describe('tracing availability and status', () => {
  it('explains how to install lttng when it is missing', () => {
    expect(tracingUnavailableText({ ...STATUS, available: false, reason: 'not_installed' })).toContain('sudo apt install lttng-tools python3-bt2');
    expect(tracingUnavailableText({ ...STATUS, available: false, reason: 'disabled' })).toContain('--tracing off');
    expect(tracingUnavailableText({ ...STATUS, available: false, reason: 'failed', error: { code: 'x', message: 'boom' } })).toContain('boom');
    expect(tracingUnavailableText(STATUS)).toBeNull();
    expect(tracingUnavailableText(null)).toBeNull();
  });

  it('shows events, discarded events, disk and roshanavi CPU', () => {
    expect(tracingStatusText({ ...STATUS, discarded: 1500 })).toBe('詳細計測中 (12 秒) · 1,235 件/秒 · 取りこぼし 1,500 件 · ディスク 1.2 MB · roshanavi の CPU 12.3%');
    expect(tracingStatusText({ ...STATUS, receiving: false })).toBe('詳細計測中 · 最初の結果を待っています…');
  });

  it('names the reason a node cannot be measured', () => {
    expect(unsupportedReasonText('restart_needed')).toContain('再起動');
    expect(unsupportedFor(STATUS, '/py')?.reason).toBe('rclpy');
    expect(unsupportedFor({ ...STATUS, active: false }, '/py')).toBeUndefined();
  });
});

describe('trace values of subscriber rows', () => {
  it('formats receive / process / callback time for C++ nodes', () => {
    expect(traceCells(sub({}), 'measured')).toEqual({ recv: '5.00 Hz', processed: '5.00 Hz', cb: '平均 200 ms / p95 201 ms / 最大 205 ms', note: null });
    expect(cbText(null)).toBe('—');
  });

  it('marks processed / time as unsupported for rclpy', () => {
    const cells = traceCells(sub({ lang: 'py', hz_processed: null, cb_ms: null }), 'measured');
    expect(cells?.processed).toBe('未対応');
    expect(cells?.note).toContain('rclpy');
  });

  it('shows 計測中… while the window has too few events', () => {
    const cells = traceCells(sub({ basis: 'theoretical', hz_recv: null, hz_processed: null }), 'theoretical');
    expect(cells).toEqual({ recv: '計測中…', processed: '計測中…', cb: '—', note: null });
  });

  it('is null for theoretical rows', () => {
    expect(traceCells(sub({ lang: undefined, basis: 'theoretical' }), 'theoretical')).toBeNull();
  });

  it('reads 実測(トレース) only on traced subscriber rows', () => {
    const [row] = topicEndpoints(entry([sub({})]));
    if (!row) throw new Error('no row');
    expect(displayBasis(row)).toBe('traced');
    expect(basisLabel(displayBasis(row))).toBe('実測(トレース)');
    expect(displayBasis({ dir: 'pub', basis: 'measured' })).toBe('measured');
    expect(row.trace?.hz_processed).toBe(5);
  });

  it('says plainly when processing falls behind', () => {
    expect(behindText({ incoming_hz: 10, processed_hz: 5, basis: 'sent', cb_avg_ms: 200 }))
      .toBe('受け取っていますが処理が追いついていません: 届く量 10.0 Hz に対して処理 5.00 Hz (1 回の処理に平均 200 ms)');
  });

  it('collects the traced subscriptions of one node for the right pane', () => {
    const behind = { incoming_hz: 10, processed_hz: 5, basis: 'sent' as const };
    const rows = nodeTraceRows([entry([sub({ behind })], '/b'), entry([sub({}), sub({ node: '/other' })], '/a'),
      entry([sub({ basis: 'theoretical', lang: undefined })], '/c')], '/slow');
    expect(rows.map((r) => r.topic)).toEqual(['/a', '/b']);
    expect(rows[1]?.behind).toEqual(behind);
  });
});

describe('live frames', () => {
  it('keep the latest tracing status', () => {
    const first = applyLive(EMPTY_LIVE, { traffic: [], jobs: [], tracing: STATUS }, 1);
    expect(first.tracing?.active).toBe(true);
    expect(applyLive(first, { traffic: [], jobs: [] }, 2).tracing).toBe(STATUS);
  });
});
