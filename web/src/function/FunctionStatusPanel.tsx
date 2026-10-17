// Live status of a function node: state, counters and the last error with file:line.

import type { Target } from '../api/types';
import { t, type MessageKey } from '../i18n';

export function FunctionStatusPanel({ target }: { target: Target }) {
  const status = target.function_status;
  if (!status) {
    return (
      <section className="function-status" data-testid="function-status" data-state="none">
        <h4>{t('function.status')}</h4>
        <p className="muted small">{t('function.status.none')}</p>
      </section>
    );
  }
  const error = status.state === 'running' ? status.last_error : (status.problem ?? status.last_error);
  return (
    <section className="function-status" data-testid="function-status" data-state={status.state}>
      <h4>{t('function.status')}</h4>
      <p>
        <span className={`status-chip ${status.state === 'running' ? 'st-running' : 'st-bad'}`}>
          {t(`function.status.${status.state}` as MessageKey)}
        </span>{' '}
        {status.signature && <code className="mono">{status.signature}</code>}
      </p>
      {status.location && <p className="muted small">{t('function.defined', { location: status.location })}</p>}
      <p className="small" data-testid="function-stats">{t('function.stats', { ...status.stats })}</p>
      {error && (
        <div className="error-box" role="alert" data-testid="function-error">
          <strong>{t('function.lastError')}</strong>
          {error.location && <div className="mono small">{t('function.where', { location: error.location })}</div>}
          <div className="mono small">{error.message}</div>
        </div>
      )}
    </section>
  );
}
