// Diagnostic -> plain-language sentence (localized via the i18n dictionary).

import type { Diagnostic, QosReason } from '../api/types';
import { t } from '../i18n';
import { formatBytes } from '../lib/format';

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
        slope: (d.detail.slope_mb_per_min ?? 0).toFixed(1),
        min: Math.max(1, Math.round((d.detail.span_sec ?? 0) / 60)),
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

/** Node names of a resource diagnostic, else its process name. */
function resourceWho(d: Diagnostic): string {
  if (d.nodes.length > 0) return d.nodes.join(', ');
  return d.detail.name ?? `pid ${d.detail.pid ?? '?'}`;
}

/** Element ids a diagnostic should focus on the map. */
export function diagnosticTargets(d: Diagnostic): { topics: string[]; nodes: string[] } {
  const topics = [d.topic, d.detail.subscribed].filter((x): x is string => Boolean(x));
  // resource diagnostics carry no topic (except udp_rcvbuf, which names the lossy topic)
  return { topics: [...new Set(topics)], nodes: d.nodes };
}
