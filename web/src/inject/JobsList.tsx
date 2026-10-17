import { useState } from 'react';
import { api, describeError } from '../api/client';
import type { Job } from '../api/types';
import { t, type MessageKey } from '../i18n';

export function JobsList({ jobs }: { jobs: Job[] }) {
  const [error, setError] = useState<string | null>(null);
  const stop = async (id: string) => {
    setError(null);
    try {
      await api.stopInject(id);
    } catch (err) {
      setError(describeError(err));
    }
  };
  const sorted = [...jobs].sort((a, b) => b.created_at - a.created_at);
  return (
    <section className="jobs" aria-labelledby="jobs-title">
      <h3 id="jobs-title">{t('inject.jobs')}</h3>
      {error && <p className="error-box" role="alert">{error}</p>}
      {sorted.length === 0 ? (
        <p className="muted">{t('inject.noJobs')}</p>
      ) : (
        <ul className="job-list">
          {sorted.map((job) => (
            <li key={job.id} className={`job state-${job.state}`} data-testid="job">
              <div>
                <span className="mono">{job.topic ?? job.source}</span>{' '}
                <span className="badge">{t(`inject.mode.${job.mode}` as MessageKey)}</span>{' '}
                <span className={`badge state-badge-${job.state}`}>{t(`inject.state.${job.state}` as MessageKey)}</span>
              </div>
              <div className="muted small">
                {job.id} · {t('inject.sent', { n: job.sent })}
                {job.rate_hz ? ` · ${job.rate_hz} Hz` : ''}
              </div>
              {job.error && <div className="error-text small">{job.error}</div>}
              {job.state === 'running' && (
                <button type="button" onClick={() => void stop(job.id)}>
                  {t('common.stop')}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
