// A small "ⓘ チュートリアルを見る" link for empty states: starts the tour that fits there.

import { t } from '../i18n';
import { ErrorBoundary } from '../lib/ErrorBoundary';
import { useTour } from './TourProvider';
import type { TourId } from './types';

function HelpButton({ id }: { id: TourId }) {
  const { run, start } = useTour();
  if (run) return null;
  return (
    <button type="button" className="link small tour-help" onClick={() => start(id)} data-testid={`tour-help-${id}`}>
      {t('tour.ui.help')}
    </button>
  );
}

export function TourHelp({ id }: { id: TourId }) {
  return (
    <ErrorBoundary scope="tour">
      <HelpButton id={id} />
    </ErrorBoundary>
  );
}
