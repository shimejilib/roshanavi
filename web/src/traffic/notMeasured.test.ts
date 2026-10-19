import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { LiveProvider } from '../state/LiveProvider';
import { entry, heavyOffEntry, NOW_MS } from '../test/fixtures';
import { endpointBandwidth, endpointHz, topicEndpoints, basisLabel, displayBasis } from './endpoints';
import { EndpointRows } from './EndpointRows';
import { isNotMeasured, notMeasuredBandwidth, notMeasuredHz, notMeasuredText, showTraceHint } from './notMeasured';
import { TrafficRow } from './TrafficRow';

// LiveProvider builds its socket URL from the page location (the socket itself opens in an effect, not in a static render).
vi.stubGlobal('window', { location: { protocol: 'http:', host: 'localhost:6871' } });

const NEVER_RECEIVED = ['受信なし', '未受信', '分けられない', '0 Hz', '届いていません'];

function renderRow(e = heavyOffEntry()): string {
  const noop = () => undefined;
  const row = createElement(TrafficRow, { entry: e, nowMs: NOW_MS, color: '#000', onSelect: noop, expanded: false, onToggle: noop });
  return renderToStaticMarkup(createElement(LiveProvider, null, createElement('table', null, createElement('tbody', null, row))));
}

function renderEndpoints(e = heavyOffEntry()): string {
  const rows = createElement(EndpointRows, { entry: e, span: 9 });
  return renderToStaticMarkup(createElement(LiveProvider, null, createElement('table', null, createElement('tbody', null, rows))));
}

describe('topics that are not measured (#61)', () => {
  it('only the not_monitored status counts', () => {
    expect(isNotMeasured(heavyOffEntry())).toBe(true);
    expect(isNotMeasured(entry('/chatter'))).toBe(false);
    expect(isNotMeasured(entry('/x', { status: 'error', monitored: true }))).toBe(false);
  });

  it('says 計測していません with the reason only for heavy data', () => {
    expect(notMeasuredText({ heavy: true })).toBe('計測していません (画像などの重いデータは既定でオフ)');
    expect(notMeasuredText({ heavy: false })).toBe('計測していません');
    expect(notMeasuredText({})).toBe('計測していません');
  });

  it('guides to 詳細計測モード for heavy data while it is off', () => {
    expect(showTraceHint({ heavy: true }, false)).toBe(true);
    expect(showTraceHint({ heavy: true }, true)).toBe(false);
    expect(showTraceHint({ heavy: false }, false)).toBe(false);
  });

  it('shows the traced Hz without bandwidth, and — when nothing is traced', () => {
    expect(notMeasuredHz(heavyOffEntry())).toBe('—');
    expect(notMeasuredBandwidth(heavyOffEntry())).toBe('—');
    const traced = heavyOffEntry('/cam', { hz_traced: 29.8 });
    expect(notMeasuredHz(traced)).toBe('29.8 Hz');
    expect(notMeasuredBandwidth(traced)).toBe('— (詳細計測では帯域は測れません)');
  });

  it('the topic row shows 計測していません + 計測する, never 0 Hz / 未受信', () => {
    const html = renderRow();
    expect(html).toContain('計測していません (画像などの重いデータは既定でオフ)');
    expect(html).toContain('計測する');
    expect(html).toContain('Hz は詳細計測モードで確認できます');
    for (const word of NEVER_RECEIVED) expect(html, word).not.toContain(word);
  });

  it('the topic row shows the traced Hz and the bandwidth note in 詳細計測モード', () => {
    const html = renderRow(heavyOffEntry('/turtle_viz/image', { hz_traced: 30 }));
    expect(html).toContain('30.0 Hz');
    expect(html).toContain('— (詳細計測では帯域は測れません)');
    expect(html).toContain('計測する');
  });

  it('a light topic switched off says 計測していません without the heavy-data reason', () => {
    const html = renderRow(heavyOffEntry('/chatter', { heavy: false, type: 'std_msgs/msg/String' }));
    expect(html).toContain('計測していません');
    expect(html).not.toContain('画像などの重いデータ');
    expect(html).not.toContain('Hz は詳細計測モードで確認できます');
  });

  it('a measured topic keeps its numbers and has no 計測する', () => {
    const html = renderRow(entry('/chatter'));
    expect(html).toContain('10.0 Hz');
    expect(html).not.toContain('計測する');
  });

  it('a measured topic that never received says 未受信 (that is a real state)', () => {
    expect(renderRow(entry('/quiet', { last_seen: null }))).toContain('未受信');
  });

  it('the endpoint rows of a not measured topic say not measured, not 分けられない', () => {
    const rows = topicEndpoints(heavyOffEntry());
    expect(rows.map((r) => basisLabel(displayBasis(r)))).toEqual(['計測していません', '計測していません', '計測していません']);
    expect(rows.map((r) => endpointHz(r))).toEqual(['—', '—', '—']);
    const html = renderEndpoints();
    expect(html).toContain('計測していません');
    for (const word of ['受信なし', '分けられない', '未受信']) expect(html, word).not.toContain(word);
  });

  it('in 詳細計測モード the endpoint rows show the traced Hz and why there is no bandwidth', () => {
    const traced = heavyOffEntry('/cam', {
      hz_traced: 30,
      publishers: [{ node: '/viz_a', hz: 30, bps: null, basis: 'traced', hz_traced: 30 }],
      subscribers: [{ node: '/consumer', hz: 29.5, bps: null, basis: 'measured', delivered: true, sources: ['/viz_a'] }],
    });
    const rows = topicEndpoints(traced);
    expect(rows.map((r) => endpointHz(r))).toEqual(['30.0 Hz', '29.5 Hz']);
    expect(rows.map((r) => endpointBandwidth(r))).toEqual(['— (詳細計測では帯域は測れません)', '— (詳細計測では帯域は測れません)']);
    expect(basisLabel(displayBasis(rows[0]!))).toBe('実測(トレース)');
  });

  it('a subscriber QoS-blocked on a not measured topic is still 届いていません (a real verdict)', () => {
    const blocked = heavyOffEntry('/cam', {
      subscribers: [{ node: '/fussy', hz: 0, bps: 0, basis: 'not_delivered', delivered: false, sources: [] }],
    });
    expect(endpointHz(topicEndpoints(blocked).at(-1)!)).toBe('届いていません');
  });
});
