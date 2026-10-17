// Shown while the launch list is empty: what the Launcher does, in three steps.

import { t } from '../i18n';

interface Props {
  canTry: boolean;
  busy: boolean;
  onTry: () => void;
  onAdd: () => void;
}

export function FirstRunGuide({ canTry, busy, onTry, onAdd }: Props) {
  return (
    <section className="first-run" data-testid="first-run-guide" aria-labelledby="first-run-title">
      <h3 id="first-run-title">{t('guide.title')}</h3>
      <ol>
        <li>{t('guide.step1')}</li>
        <li>{t('guide.step2')}</li>
        <li>{t('guide.step3')}</li>
      </ol>
      <div className="row">
        <button type="button" className="primary" disabled={!canTry || busy} onClick={onTry} data-testid="guide-try-talker" title={canTry ? undefined : t('guide.noDemo')}>
          {t('guide.tryTalker')}
        </button>
        <button type="button" onClick={onAdd}>{t('launcher.add')}</button>
      </div>
      {!canTry && <p className="muted small">{t('guide.noDemo')}</p>}
    </section>
  );
}
