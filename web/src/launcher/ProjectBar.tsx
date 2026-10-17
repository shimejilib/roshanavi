// Project file path + autosave status; reload lives in the ⚙ settings menu.

import { useEffect, useState } from 'react';
import { api, describeError } from '../api/client';
import type { ProjectState } from '../api/types';
import { t } from '../i18n';
import { useAppState } from '../state/AppState';

/** `version` changes (launch list edits) trigger a re-check of the autosave state. */
export function ProjectBar({ version }: { version: string }) {
  const [state, setState] = useState<ProjectState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { openDialog } = useAppState();

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

  const reload = async () => {
    if (!window.confirm(t('launcher.reloadConfirm'))) return;
    setBusy(true);
    setError(null);
    try {
      setState(await api.reloadProject());
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  const autosaveOff = state?.autosave === false;
  return (
    <div className="toolbar project-bar">
      <strong>{t('launcher.project')}</strong>
      {state && (
        <span className="muted small mono" title={state.path}>
          {t('launcher.projectPath', { path: state.path })}
        </span>
      )}
      {state && (
        <span className={autosaveOff ? 'badge unsaved' : 'badge'} data-testid="project-autosave" title={t('launcher.autosaveHelp')}>
          {autosaveOff ? t('launcher.autosaveOff') : t('launcher.autosaveOn')}
        </span>
      )}
      {state?.error && <span className="error-text small">{t('launcher.projectError', { message: state.error })}</span>}
      {state?.save_error && <span className="error-text small" role="alert">{t('launcher.saveError', { message: state.save_error })}</span>}
      {error && <span className="error-text small" role="alert">{error}</span>}
      <span className="spacer" />
      <details className="settings-menu">
        <summary data-testid="launcher-settings">⚙ {t('launcher.settings')}</summary>
        <div className="settings-items">
          <button type="button" disabled={busy} onClick={() => void reload()} data-testid="project-reload">
            {t('launcher.reload')}
          </button>
          <span className="muted small">{t('launcher.reloadHelp')}</span>
          <button type="button" onClick={() => openDialog({ kind: 'projects' })} data-testid="project-switch">
            {t('project.switch')}
          </button>
        </div>
      </details>
    </div>
  );
}
