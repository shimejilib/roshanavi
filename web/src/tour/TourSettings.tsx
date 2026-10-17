// ⚙ 設定 → チュートリアル: every tour with a check mark when it was completed.

import { t, type MessageKey } from '../i18n';
import { ErrorBoundary } from '../lib/ErrorBoundary';
import { TOURS } from './tours';
import { useTour } from './TourProvider';
import type { TourId } from './types';

function TourList() {
  const { progress, run, start, quit } = useTour();
  const closeMenu = (el: HTMLElement) => el.closest('details')?.removeAttribute('open');
  const label = (id: TourId): string => {
    if (run?.tourId === id && run.status === 'paused') return t('tour.ui.continue');
    return progress.completed.includes(id) ? t('tour.ui.again') : t('tour.ui.start');
  };
  return (
    <section className="tour-settings" aria-labelledby="tour-settings-title">
      <h4 id="tour-settings-title">{t('tour.ui.settingsTitle')}</h4>
      <ul>
        {TOURS.map((tour) => {
          const done = progress.completed.includes(tour.id);
          return (
            <li key={tour.id} data-testid={`tour-item-${tour.id}`} data-done={done}>
              <span className="tour-check" aria-label={done ? t('tour.ui.done') : undefined} title={done ? t('tour.ui.done') : undefined}>
                {done ? '✓' : ''}
              </span>
              <span className="tour-item-text">
                <strong>{t(`tour.name.${tour.id}` as MessageKey)}</strong>
                <span className="muted small">{t(`tour.summary.${tour.id}` as MessageKey)}</span>
              </span>
              <button type="button" data-testid={`tour-start-${tour.id}`} data-tour={`tour-start-${tour.id}`}
                onClick={(e) => { closeMenu(e.currentTarget); start(tour.id); }}>
                {label(tour.id)}
              </button>
            </li>
          );
        })}
      </ul>
      {run && <button type="button" className="small" onClick={quit} data-testid="tour-settings-quit">{t('tour.ui.quit')}</button>}
    </section>
  );
}

export function TourSettings() {
  return (
    <ErrorBoundary scope="tour">
      <TourList />
    </ErrorBoundary>
  );
}
