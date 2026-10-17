import { useState } from 'react';
import { api, describeError } from '../api/client';
import type { DummySpec, Target } from '../api/types';
import { t } from '../i18n';
import { isAlive, statusClass, statusLabel } from '../launcher/status';
import { useAppState } from '../state/AppState';

const DEFAULT_EXPORT_DIR = 'launch/roshanavi_dummies';

function DummyRow({ target, onError }: { target: Target; onError: (msg: string | null) => void }) {
  const { openLogs } = useAppState();
  const spec = target.spec as DummySpec;
  const act = (fn: () => Promise<unknown>) => {
    onError(null);
    fn().catch((err: unknown) => onError(describeError(err)));
  };
  return (
    <li className={`job dummy ${statusClass(target.status)}`} data-testid={`dummy-${target.id}`}>
      <div>
        <span className="mono">{spec.namespace ? `${spec.namespace}/${spec.name}` : `/${spec.name}`}</span>{' '}
        <span className={`status-chip ${statusClass(target.status)}`}>{statusLabel(target)}</span>
      </div>
      <div className="muted small mono">
        → {spec.topic} · {t(`inject.mode.${spec.mode}`)}
        {spec.rate_hz ? ` · ${spec.rate_hz} Hz` : ''}
      </div>
      {target.problem && <div className="error-text small">{target.problem}</div>}
      <div className="row">
        {isAlive(target) ? (
          <button type="button" onClick={() => act(() => api.targetAction(target.id, 'stop'))}>{t('launcher.stop')}</button>
        ) : (
          <button type="button" onClick={() => act(() => api.targetAction(target.id, 'start'))}>{t('launcher.start')}</button>
        )}
        <label className="check small">
          <input type="checkbox" checked={spec.autostart ?? false} onChange={(e) => act(() => api.updateDummy({ ...spec, autostart: e.target.checked }))} />
          {t('dummy.autostart')}
        </label>
        <button type="button" onClick={() => openLogs(target.id)}>{t('launcher.logs')}</button>
        <button type="button" onClick={() => act(() => api.removeTarget(target.id))}>{t('common.remove')}</button>
      </div>
    </li>
  );
}

export function DummiesList({ targets }: { targets: Target[] }) {
  const dummies = targets.filter((tg) => tg.kind === 'dummy');
  const [error, setError] = useState<string | null>(null);
  const [dir, setDir] = useState(DEFAULT_EXPORT_DIR);
  const [exported, setExported] = useState<string | null>(null);
  const doExport = () => {
    setError(null);
    api
      .exportDummies(dir.trim())
      .then((result) => setExported(t('dummy.exportDone', { command: result.command })))
      .catch((err: unknown) => setError(describeError(err)));
  };
  return (
    <section className="dummies" aria-labelledby="dummies-title">
      <h3 id="dummies-title">{t('dummy.list')}</h3>
      {error && <p className="error-box" role="alert">{error}</p>}
      {dummies.length === 0 ? (
        <p className="muted small">{t('dummy.none')}</p>
      ) : (
        <>
          <ul className="job-list">
            {dummies.map((target) => (
              <DummyRow key={target.id} target={target} onError={setError} />
            ))}
          </ul>
          <div className="export-box">
            <label className="small">
              {t('dummy.exportDir')}
              <input value={dir} onChange={(e) => setDir(e.target.value)} />
            </label>
            <button type="button" onClick={doExport} disabled={!dir.trim()}>{t('dummy.export')}</button>
            <span className="muted small">{t('dummy.exportNote')}</span>
            {exported && <p className="ok-box small mono" role="status">{exported}</p>}
          </div>
        </>
      )}
    </section>
  );
}
