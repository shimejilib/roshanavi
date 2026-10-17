// Right pane. Sections are chosen by selection kind; later phases (logs,
// launcher controls, media viewers) add their own sections here.

import { t } from '../i18n';
import { useAppState } from '../state/AppState';
import { useLive } from '../state/LiveProvider';
import { NodeDetail } from './NodeDetail';
import { TopicDetail } from './TopicDetail';

export function DetailPane() {
  const { selection, select } = useAppState();
  const { live } = useLive();
  return (
    <aside className="detail-pane" aria-label="detail">
      {selection && (
        <button type="button" className="close" onClick={() => select(null)} aria-label={t('common.close')}>
          ×
        </button>
      )}
      {!selection && <p className="muted">{t('detail.empty')}</p>}
      {selection?.kind === 'topic' && (
        <TopicDetail topic={selection.id} graph={live.graph} entry={live.traffic.get(selection.id)} />
      )}
      {selection?.kind === 'node' && <NodeDetail nodeId={selection.id} graph={live.graph} />}
    </aside>
  );
}
