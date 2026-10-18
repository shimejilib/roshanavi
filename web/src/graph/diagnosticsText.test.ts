import { describe, expect, it } from 'vitest';
import type { Diagnostic } from '../api/types';
import { diagnosticTargets, diagnosticText, quietTopicNotes, reasonText, warningDiagnostics } from './diagnosticsText';

const base = { severity: 'warning' as const, nodes: ['/a'], detail: {} };

describe('diagnosticText', () => {
  it('renders every code in plain Japanese', () => {
    const diags: Diagnostic[] = [
      { ...base, severity: 'info', code: 'no_subscriber', topic: '/x' },
      { ...base, severity: 'info', code: 'no_publisher', topic: '/y' },
      { ...base, code: 'similar_names', topic: '/cmd_vel', detail: { published: '/cmd_vel', subscribed: '/cmdvel' } },
      { ...base, code: 'type_mismatch', topic: '/z', detail: { types: ['A', 'B'] } },
      { ...base, code: 'subscriber_lost', topic: '/chatter', detail: { lost: ['/listener'] } },
      { ...base, code: 'publisher_lost', topic: '/chatter', detail: { lost: ['/talker', '/talker2'] } },
      { ...base, code: 'mine_no_input', topic: '/camera', detail: { node: '/detector' } },
      {
        ...base,
        severity: 'error',
        code: 'qos_incompatible',
        topic: '/scan',
        detail: { publisher: '/lidar', subscriber: '/slam', reasons: [{ policy: 'reliability', pub: 'best_effort', sub: 'reliable' }] },
      },
    ];
    const texts = diags.map(diagnosticText);
    expect(texts[0]).toBe('/x を受信しているノードはまだありません (今は送信だけです)');
    expect(texts[1]).toContain('/y に送信しているノードはまだありません');
    expect(texts[2]).toContain('/cmd_vel (送信) と /cmdvel (受信) は名前が似ていて');
    expect(texts[3]).toContain('A, B');
    expect(texts[4]).toBe('さっきまで /listener が /chatter を受信していましたが、いなくなりました');
    expect(texts[5]).toBe('さっきまで /talker, /talker2 が /chatter に送信していましたが、いなくなりました');
    expect(texts[6]).toBe('開発中のノード /detector の入力 /camera に送信元がいません');
    expect(texts[7]).toBe('/slam は /scan を受け取れません: 送信側は BEST_EFFORT、受信側は RELIABLE のため届きません');
    expect(texts.every((s) => !s.includes('{'))).toBe(true);
  });

  it('counts only warnings and errors; info is a quiet marker per topic', () => {
    const diags: Diagnostic[] = [
      { ...base, severity: 'info', code: 'no_subscriber', topic: '/x' },
      { ...base, severity: 'info', code: 'no_publisher', topic: '/y' },
      { ...base, code: 'subscriber_lost', topic: '/z', detail: {} },
    ];
    expect(warningDiagnostics(diags).map((d) => d.code)).toEqual(['subscriber_lost']);
    expect([...quietTopicNotes(diags)]).toEqual([
      ['/x', '受信なし'],
      ['/y', '送信なし'],
    ]);
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
