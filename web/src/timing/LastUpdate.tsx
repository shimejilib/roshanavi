// "最終更新 HH:MM:SS (N 秒前)" for the live connection; turns to a warning colour
// when frames stop arriving (disconnect or a stalled server); shows 「一時停止中」
// instead while the map is paused (the frozen view is expected to be old). Ticks on its own
// so the age keeps growing even while no frame arrives.

import { useEffect, useState } from 'react';
import { t } from '../i18n';
import { useLive } from '../state/LiveProvider';
import { lastUpdate } from './timing';

const TICK_MS = 1000;

export function LastUpdateBadge() {
  const { live, paused } = useLive();
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), TICK_MS);
    return () => clearInterval(timer);
  }, []);
  const info = lastUpdate(live.receivedAt, now, paused);
  const className = ['last-update', info.late ? 'late' : '', info.paused ? 'paused' : ''].filter(Boolean).join(' ');
  return (
    <span
      className={className}
      title={t(info.paused ? 'timing.pausedHelp' : 'timing.lastUpdateHelp')}
      data-testid="last-update" data-tour="last-update"
      data-late={info.late}
      data-paused={info.paused}
      role="status"
    >
      {info.text}
    </span>
  );
}
