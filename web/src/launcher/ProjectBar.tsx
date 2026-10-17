import { useEffect, useState } from 'react';
import { api, describeError } from '../api/client';
import type { ProjectState } from '../api/types';
import { t } from '../i18n';

/** Project file path, unsaved indicator, explicit save / reload. `version` changes trigger a re-check. */
export function ProjectBar({ version }: { version: string }) {
  const [state, setState] = useState<ProjectState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .project()
      .then((s) => !cancelled && setState(s))
      .catch((err: unknown) => !cancelled && setError(describeError(err)));
    return () => {
      cancelled = true;
    };
  }, [version]);

  const run = async (fn: () => Promise<ProjectState>) => {
    setBusy(true);
    setError(null);
    try {
      setState(await fn());
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="toolbar project-bar">
      <strong>{t('launcher.project')}</strong>
      {state && (
        <span className="muted small mono" title={state.path}>
          {t('launcher.projectPath', { path: state.path })} {!state.exists && t('launcher.projectNew')}
        </span>
      )}
      {state && (
        <span className={state.dirty ? 'badge unsaved' : 'badge'} data-testid="project-dirty" data-dirty={state.dirty}>
          {state.dirty ? t('launcher.unsaved') : t('launcher.saved')}
        </span>
      )}
      <button type="button" className={state?.dirty ? 'primary' : ''} disabled={busy} onClick={() => void run(api.saveProject)} data-testid="project-save">
        {t('launcher.save')}
      </button>
      <button
        type="button"
        disabled={busy}
        onClick={() => {
          if (!state?.dirty || window.confirm(t('launcher.reloadConfirm'))) void run(api.reloadProject);
        }}
      >
        {t('launcher.reload')}
      </button>
      {state?.error && <span className="error-text small">{t('launcher.projectError', { message: state.error })}</span>}
      {error && <span className="error-text small" role="alert">{error}</span>}
    </div>
  );
}
