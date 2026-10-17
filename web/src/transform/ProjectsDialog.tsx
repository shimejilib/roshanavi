// ⚙ settings menu → 「プロジェクトを切り替える」: the example and saved project files.

import { useEffect, useState } from 'react';
import { api, describeError } from '../api/client';
import type { ProjectEntry } from '../api/transformTypes';
import { t } from '../i18n';
import { Modal } from '../lib/Modal';
import { useAppState } from '../state/AppState';

export function ProjectsDialog() {
  const { closeDialog } = useAppState();
  const [projects, setProjects] = useState<ProjectEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => api.projects().then((list) => setProjects(list.projects)).catch((err: unknown) => setError(describeError(err)));
  useEffect(() => {
    void load();
  }, []);

  const open = async (entry: ProjectEntry) => {
    if (!window.confirm(t('project.switchIntro'))) return;
    setBusy(true);
    setError(null);
    try {
      const state = await api.openProject(entry.id);
      setNotice(t('project.opened', { path: state.path }));
      if (state.error) setError(t('launcher.projectError', { message: state.error }));
      await load();
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={t('project.switchTitle')} onClose={closeDialog} wide testId="projects-dialog">
      <p className="muted small">{t('project.switchIntro')}</p>
      {error && <p className="error-box" role="alert">{error}</p>}
      {notice && <p className="ok-box" role="status">{notice}</p>}
      {projects?.length === 0 && <p className="muted">{t('project.none')}</p>}
      <ul className="project-list">
        {(projects ?? []).map((entry) => (
          <li key={entry.id} data-testid={`project-${entry.id}`}>
            <div>
              <span className="badge">{t(entry.kind === 'example' ? 'project.example' : 'project.data')}</span>{' '}
              <strong className="mono">{entry.name}</strong>
              {entry.current && <span className="badge ok"> {t('project.current')}</span>}
              {entry.title && <div className="muted small">{entry.title}</div>}
              {entry.kind === 'example' && entry.copy_path && <div className="muted small">{t('project.exampleNote', { path: entry.copy_path })}</div>}
            </div>
            <button type="button" className="primary" disabled={busy || entry.current} onClick={() => void open(entry)} data-testid={`project-open-${entry.id}`}>
              {t('project.open')}
            </button>
          </li>
        ))}
      </ul>
      <div className="row end">
        <button type="button" onClick={closeDialog} data-testid="projects-close">{t('common.close')}</button>
      </div>
    </Modal>
  );
}
