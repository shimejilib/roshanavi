// 「計測していません (…)」 + 「計測する」 inline, for a topic that is not subscribed.

import { useState } from 'react';
import { api, describeError } from '../api/client';
import type { TrafficEntry } from '../api/types';
import { t } from '../i18n';
import { topicPath } from '../lib/topics';
import { useLive } from '../state/LiveProvider';
import { notMeasuredText, showTraceHint } from './notMeasured';

/** Turn the measurement of one topic on or off (the server keeps the choice in the project file). */
export function setTopicMonitor(topic: string, enabled: boolean): Promise<unknown> {
  return api.setMonitor(`${topicPath('/api/traffic', topic)}/monitor`, enabled);
}

export function NotMeasured({ entry, compact = false }: { entry: Pick<TrafficEntry, 'topic' | 'heavy'>; compact?: boolean }) {
  const { live } = useLive();
  const [error, setError] = useState<string | null>(null);
  const start = async () => {
    setError(null);
    try {
      await setTopicMonitor(entry.topic, true);
    } catch (err) {
      setError(`${t('monitor.failed')}: ${describeError(err)}`);
    }
  };
  const hint = !compact && showTraceHint(entry, live.tracing?.active === true);
  return (
    <span className={compact ? 'not-measured' : 'not-measured block'} data-testid={`not-measured-${entry.topic}`}>
      <span className="not-measured-line">
        <span className="badge muted-badge">{compact ? t('monitor.off') : notMeasuredText(entry)}</span>{' '}
        <button type="button" className="small" title={t('monitor.onHelp')} data-testid={`measure-on-${entry.topic}`}
          onClick={(e) => { e.stopPropagation(); void start(); }}>
          {t('monitor.on')}
        </button>
      </span>
      {hint && <span className="muted small not-measured-hint">{t('monitor.traceHint')}</span>}
      {error && <span className="error-text small not-measured-hint" role="alert">{error}</span>}
    </span>
  );
}
