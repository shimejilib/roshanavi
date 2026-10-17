import { describe, expect, it } from 'vitest';
import type { Diagnostic } from '../api/types';
import { diagnosticTargets, diagnosticText, reasonText } from './diagnosticsText';

const base = { severity: 'warning' as const, nodes: ['/a'], detail: {} };

describe('diagnosticText', () => {
  it('renders every code in plain Japanese', () => {
    const diags: Diagnostic[] = [
      { ...base, code: 'no_subscriber', topic: '/x' },
      { ...base, code: 'no_publisher', topic: '/y' },
      { ...base, code: 'similar_names', topic: '/cmd_vel', detail: { published: '/cmd_vel', subscribed: '/cmdvel' } },
      { ...base, code: 'type_mismatch', topic: '/z', detail: { types: ['A', 'B'] } },
      {
        ...base,
        severity: 'error',
        code: 'qos_incompatible',
        topic: '/scan',
        detail: { publisher: '/lidar', subscriber: '/slam', reasons: [{ policy: 'reliability', pub: 'best_effort', sub: 'reliable' }] },
      },
    ];
    const texts = diags.map(diagnosticText);
    expect(texts[0]).toBe('/x は送信されていますが、受信しているノードがありません');
    expect(texts[1]).toContain('/y を受信待ち');
    expect(texts[2]).toContain('/cmd_vel (送信のみ) と /cmdvel (受信のみ)');
    expect(texts[3]).toContain('A, B');
    expect(texts[4]).toBe('/slam は /scan を受け取れません: 送信側は BEST_EFFORT、受信側は RELIABLE のため届きません');
    expect(texts.every((s) => !s.includes('{'))).toBe(true);
  });

  it('formats durations and infinity in QoS reasons', () => {
    expect(reasonText({ policy: 'deadline', pub: null, sub: 100 })).toContain('無制限');
    expect(reasonText({ policy: 'deadline', pub: null, sub: 100 })).toContain('100 ms');
  });

  it('targets both topics of a similar-name warning', () => {
    const d: Diagnostic = { ...base, code: 'similar_names', topic: '/a', detail: { published: '/a', subscribed: '/b' } };
    expect(diagnosticTargets(d)).toEqual({ topics: ['/a', '/b'], nodes: ['/a'] });
  });
});
