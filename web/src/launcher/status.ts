// Target status -> label / css class (pure).

import type { Target } from '../api/types';
import { t, type MessageKey } from '../i18n';
import { formatDuration } from '../lib/format';

export function statusLabel(target: Pick<Target, 'status' | 'exit_code'>): string {
  return t(`launcher.status.${target.status}` as MessageKey, { code: target.exit_code ?? '?' });
}

export function statusClass(status: Target['status']): string {
  if (status === 'running') return 'st-running';
  if (status === 'starting') return 'st-starting';
  if (status === 'crashed' || status === 'invalid') return 'st-bad';
  return 'st-idle';
}

export function isAlive(target: Pick<Target, 'status'>): boolean {
  return target.status === 'running' || target.status === 'starting';
}

export function uptimeText(target: Pick<Target, 'uptime_sec'>): string | null {
  return target.uptime_sec == null ? null : t('launcher.uptime', { time: formatDuration(target.uptime_sec) });
}
