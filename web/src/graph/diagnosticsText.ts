// Diagnostic -> plain-language sentence (localized via the i18n dictionary).

import type { Diagnostic, QosReason } from '../api/types';
import { t } from '../i18n';
import { formatBytes } from '../lib/format';
import { formatGrowthDuration, formatGrowthRate, selfLabel } from '../resources/model';

function durationText(value: string | number | null): string {
  return typeof value === 'number' ? `${value} ms` : t('qos.infinite');
}

export function reasonText(reason: QosReason): string {
  const isDuration = reason.policy === 'deadline' || reason.policy === 'liveliness_lease';
  const pub = isDuration ? durationText(reason.pub) : String(reason.pub ?? '').toUpperCase();
  const sub = isDuration ? durationText(reason.sub) : String(reason.sub ?? '').toUpperCase();
  return t(`qos.${reason.policy}`, { pub, sub });
}

/** Reasons of one qos_incompatible diagnostic, prefixed by the publisher. */
export function qosReasonText(d: Diagnostic): string {
  const reasons = (d.detail.reasons ?? []).map(reasonText).join(' / ');
  return `${d.detail.publisher ?? '?'} → ${d.detail.subscriber ?? '?'}: ${reasons}`;
}

export function diagnosticText(d: Diagnostic): string {
  switch (d.code) {
    case 'qos_incompatible':
      return t('diag.qos_incompatible', {
        subscriber: d.detail.subscriber ?? '?',
        topic: d.topic,
        reasons: (d.detail.reasons ?? []).map(reasonText).join(' / '),
      });
    case 'no_subscriber':
      return t('diag.no_subscriber', { topic: d.topic });
    case 'no_publisher':
      return t('diag.no_publisher', { topic: d.topic });
    case 'subscriber_lost':
      return t('diag.subscriber_lost', { who: (d.detail.lost ?? []).join(', ') || '?', topic: d.topic });
    case 'publisher_lost':
      return t('diag.publisher_lost', { who: (d.detail.lost ?? []).join(', ') || '?', topic: d.topic });
    case 'mine_no_input':
      return t('diag.mine_no_input', { node: d.detail.node ?? d.nodes[0] ?? '?', topic: d.topic });
    case 'similar_names':
      return t('diag.similar_names', {
        published: d.detail.published ?? d.topic,
        subscribed: d.detail.subscribed ?? '?',
      });
    case 'type_mismatch':
      return t('diag.type_mismatch', { topic: d.topic, types: (d.detail.types ?? []).join(', ') });
    case 'mem_leak':
    case 'gpu_mem_leak':
      return t(`diag.${d.code}`, {
        who: resourceWho(d),
        rate: formatGrowthRate(d.detail.rate_mb_per_min ?? 0),
        duration: formatGrowthDuration(d.detail.duration_sec ?? 0),
      });
    case 'disk_low': {
      const params = { path: d.detail.path ?? '', free: formatBytes(d.detail.free ?? 0), pct: d.detail.free_pct ?? '?' };
      if (d.detail.level === 'stop') return t('diag.disk_low.stop', params);
      return t('diag.disk_low', params) + (d.detail.recording ? t('diag.disk_low.recording') : '');
    }
    case 'udp_rcvbuf':
      return t('diag.udp_rcvbuf', { topic: d.topic, n: d.detail.rcvbuf_recent ?? 0 });
    default:
      return d.topic;
  }
}

/** What the badge counts and the panel lists: warnings and errors. `info` (no_subscriber /
 *  no_publisher) is shown quietly on the map and in the topic / node details only. */
export function warningDiagnostics<T extends Pick<Diagnostic, 'severity'>>(diagnostics: readonly T[]): T[] {
  return diagnostics.filter((d) => d.severity !== 'info');
}

/** `受信なし` / `送信なし` marker per topic for the map. */
export function quietTopicNotes(diagnostics: readonly Diagnostic[]): Map<string, string> {
  const notes = new Map<string, string>();
  for (const d of diagnostics) {
    if (d.code === 'no_subscriber') notes.set(d.topic, t('diag.quiet.no_subscriber'));
    else if (d.code === 'no_publisher') notes.set(d.topic, t('diag.quiet.no_publisher'));
  }
  return notes;
}

/** Node names of a resource diagnostic, else roshanavi's own process role, else its process name. */
function resourceWho(d: Diagnostic): string {
  if (d.nodes.length > 0) return d.nodes.join(', ');
  if (d.detail.group === 'self' && d.detail.label) return t('diag.who.self', { label: selfLabel(d.detail.label) });
  return d.detail.name ?? `pid ${d.detail.pid ?? '?'}`;
}

/** Element ids a diagnostic should focus on the map. */
export function diagnosticTargets(d: Diagnostic): { topics: string[]; nodes: string[] } {
  const topics = [d.topic, d.detail.subscribed].filter((x): x is string => Boolean(x));
  // resource diagnostics carry no topic (except udp_rcvbuf, which names the lossy topic)
  return { topics: [...new Set(topics)], nodes: d.nodes };
}
