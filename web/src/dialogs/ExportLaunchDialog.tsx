// "launch に書き出し" for one persistent input node.

import { useState } from 'react';
import { api, describeError } from '../api/client';
import type { ExportResult } from '../api/types';
import { t } from '../i18n';
import { Modal } from '../lib/Modal';
import { Term } from '../lib/Term';
import { useAppState } from '../state/AppState';

const DEFAULT_DIR = 'roshanavi_launch';

export function ExportLaunchDialog({ dummyId }: { dummyId: string }) {
  const { closeDialog } = useAppState();
  const [directory, setDirectory] = useState(DEFAULT_DIR);
  const [result, setResult] = useState<ExportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const run = async () => {
    setError(null);
    try {
      setResult(await api.exportDummies(directory.trim(), [dummyId]));
    } catch (err) {
      setError(describeError(err));
    }
  };
  return (
    <Modal title={t('export.title', { id: dummyId })} onClose={closeDialog} testId="export-dialog">
      <form onSubmit={(e) => { e.preventDefault(); void run(); }}>
        <label>
          <span>{t('export.directory')} <Term term="launch" /></span>
          <input value={directory} onChange={(e) => setDirectory(e.target.value)} />
          <span className="muted small">{t('export.directoryHelp')}</span>
        </label>
        {error && <p className="error-box" role="alert">{error}</p>}
        {result && (
          <p className="ok-box" role="status">
            {t('export.done', { file: result.launch_file })}
            <br />
            <code className="mono small">{result.command}</code>
          </p>
        )}
        <div className="row end">
          <button type="button" onClick={closeDialog}>{t('common.close')}</button>
          <button type="submit" className="primary">{t('export.run')}</button>
        </div>
      </form>
    </Modal>
  );
}
