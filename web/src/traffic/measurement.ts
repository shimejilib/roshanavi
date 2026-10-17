// How traffic is measured (C++ probe or Python fallback) as a short note for the toolbar.

import type { Measurement } from '../api/types';
import { t, type MessageKey } from '../i18n';

export interface MeasurementNote {
  text: string;
  /** info = normal operation, warn = less precise per-publisher values. */
  level: 'info' | 'warn';
  help?: string;
}

export function measurementNote(m: Measurement | null | undefined): MeasurementNote | null {
  if (!m) return null;
  if (m.mode === 'python') {
    const key = `traffic.measurement.python.${m.reason ?? 'disabled'}` as MessageKey;
    return { text: t(key), level: m.reason === 'disabled' ? 'info' : 'warn' };
  }
  if (!m.receiving || m.state === 'restarting') return { text: t('traffic.measurement.restarting'), level: 'warn' };
  if (m.gid_resolution === 'unmatched') {
    return { text: t('traffic.measurement.unmatched', { rmw: m.rmw ?? '?' }), level: 'warn' };
  }
  const text = m.cpu_percent == null
    ? t('traffic.measurement.probe')
    : t('traffic.measurement.probeCpu', { cpu: m.cpu_percent.toFixed(1) });
  return { text, level: 'info', help: t('traffic.measurement.probeHelp') };
}

/** Tooltip of an error badge; known backend codes get a plain sentence. */
export function trafficErrorText(error: string | null | undefined): string | undefined {
  if (!error) return undefined;
  return error === 'probe_unavailable' ? t('traffic.error.probe_unavailable') : error;
}
