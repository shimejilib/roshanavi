// Diagnostic -> plain-language sentence (localized via the i18n dictionary).

import type { Diagnostic, QosReason } from '../api/types';
import { t } from '../i18n';

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
    default:
      return d.topic;
  }
}

/** Element ids a diagnostic should focus on the map. */
export function diagnosticTargets(d: Diagnostic): { topics: string[]; nodes: string[] } {
  const topics = [d.topic, d.detail.subscribed].filter((x): x is string => Boolean(x));
  return { topics: [...new Set(topics)], nodes: d.nodes };
}
