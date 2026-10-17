import { useState } from 'react';
import { api, describeError } from '../api/client';
import type { Job } from '../api/types';
import { t } from '../i18n';
import { suggestDummyName } from './dummyName';

/** Inline "turn this running job into a persistent dummy node" form. */
export function PersistForm({ job, onDone }: { job: Job; onDone: (message: string) => void }) {
  const [name, setName] = useState(() => suggestDummyName(job.topic));
  const [autostart, setAutostart] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const target = await api.persistJob(job.id, name.trim(), autostart);
      onDone(t('dummy.persistDone', { id: target.id }));
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <form
      className="persist-form"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      <span className="muted small">{t('dummy.persistHelp')}</span>
      <label className="small">
        {t('dummy.nodeName')}
        <input value={name} onChange={(e) => setName(e.target.value)} data-testid="persist-name" />
      </label>
      <label className="check small">
        <input type="checkbox" checked={autostart} onChange={(e) => setAutostart(e.target.checked)} />
        {t('dummy.autostart')}
      </label>
      <button type="submit" className="primary" disabled={busy || !name.trim()} data-testid="persist-submit">
        {t('dummy.persist')}
      </button>
      {error && <p className="error-box" role="alert">{error}</p>}
    </form>
  );
}
