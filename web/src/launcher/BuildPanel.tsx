import type { BuildStatus } from '../api/types';
import { t } from '../i18n';

interface Props {
  build: BuildStatus | null;
  restartRunning: boolean;
  onRestartRunning: (value: boolean) => void;
  onCancel: () => void;
  onShowLog: () => void;
}

function Result({ build }: { build: BuildStatus }) {
  const pkg = build.package ?? '';
  if (build.state === 'running') return <p className="build-state running" role="status">{t('launcher.build.running', { pkg })}</p>;
  if (build.state === 'succeeded') {
    return (
      <div className="ok-box" role="status" data-testid="build-result" data-state="succeeded">
        {t('launcher.build.succeeded', { pkg })}
        {build.restarted && build.restarted.length > 0 && <div>{t('launcher.build.restarted', { ids: build.restarted.join(', ') })}</div>}
        {build.needs_resource && <div className="small">{t('launcher.build.needsResource')}</div>}
      </div>
    );
  }
  return (
    <div className="error-box" role="alert" data-testid="build-result" data-state="failed">
      {t('launcher.build.failed', { pkg })}
      {build.error_lines && build.error_lines.length > 0 && (
        <>
          <div className="small">{t('launcher.build.firstErrors')}</div>
          <pre className="build-errors">{build.error_lines.join('\n')}</pre>
        </>
      )}
    </div>
  );
}

export function BuildPanel({ build, restartRunning, onRestartRunning, onCancel, onShowLog }: Props) {
  return (
    <section className="build-panel" aria-label={t('launcher.build.title')}>
      <label className="check small">
        <input type="checkbox" checked={restartRunning} onChange={(e) => onRestartRunning(e.target.checked)} />
        {t('launcher.build.restartRunning')}
      </label>
      {build && build.state !== 'idle' && (
        <>
          <Result build={build} />
          <div className="row">
            {build.state === 'running' && <button type="button" onClick={onCancel}>{t('launcher.build.cancel')}</button>}
            <button type="button" onClick={onShowLog}>{t('launcher.build.showLog')}</button>
          </div>
        </>
      )}
    </section>
  );
}
