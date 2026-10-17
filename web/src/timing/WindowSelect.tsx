// Averaging window selector (1 / 5 / 10 s) shared by the map and the traffic table.

import { t } from '../i18n';
import { useLive } from '../state/LiveProvider';
import { isWindowSec, WINDOW_CHOICES, windowLabel } from './timing';

export function WindowSelect() {
  const { windowSec, setWindowSec } = useLive();
  return (
    <label className="window-select" title={t('timing.windowHelp')}>
      <span className="visually-hidden">{t('timing.windowLabel')}</span>
      <select
        value={windowSec}
        onChange={(e) => {
          const next = Number(e.target.value);
          if (isWindowSec(next)) setWindowSec(next);
        }}
        data-testid="window-select"
      >
        {WINDOW_CHOICES.map((sec) => (
          <option key={sec} value={sec}>{windowLabel(sec)}</option>
        ))}
      </select>
    </label>
  );
}
