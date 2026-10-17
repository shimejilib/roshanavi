// While 詳細計測モード is on: events/s, discarded events, disk, roshanavi's own CPU,
// nodes that are behind, and nodes that cannot be measured (with the reason).

import type { TracingStatus } from '../api/tracingTypes';
import { t } from '../i18n';
import { behindHelp, behindText, cpuHelp, tracingStatusText, unsupportedReasonText } from './tracing';

export function TracingStatusBar({ status }: { status: TracingStatus | null }) {
  if (!status?.active) return null;
  return (
    <div className="tracing-bar" data-testid="tracing-status" role="status">
      <div>
        <span title={`${cpuHelp(status)}\n${t('tracing.status.discardedHelp')}`}>{tracingStatusText(status)}</span>
        {status.skipped_chunks > 0 && <span className="warn-text small"> · {t('tracing.status.skipped', { n: status.skipped_chunks })}</span>}
        {status.error && <span className="warn-text small"> · {t('tracing.status.error', { message: status.error.message })}</span>}
      </div>
      {status.diagnostics.length > 0 && (
        <ul className="diag-list compact">
          {status.diagnostics.map((d) => (
            <li key={`${d.node}-${d.topic}`} className="sev-warning" title={behindHelp(d)}>
              <span className="mono">{d.node}</span> ← <span className="mono">{d.topic}</span>: {behindText(d)}
            </li>
          ))}
        </ul>
      )}
      {status.unsupported.length > 0 && (
        <details className="small" data-testid="tracing-unsupported">
          <summary>{t('tracing.unsupportedTitle')} ({status.unsupported.length})</summary>
          <ul>
            {status.unsupported.map((u) => (
              <li key={u.node}><span className="mono">{u.node}</span>: {unsupportedReasonText(u.reason)}</li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
