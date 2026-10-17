// One collapsible topic in the node I/O pane; subscribes (echo / viewer) only while open.

import type { IoItem } from './nodeIO';
import { t } from '../i18n';
import { useAppState } from '../state/AppState';
import { rateText } from '../timing/timing';
import { AudioViewer } from './AudioViewer';
import { EchoView } from './EchoView';
import { ImageViewer } from './ImageViewer';

interface Props {
  item: IoItem;
  open: boolean;
  viewKind: 'image' | 'audio' | undefined;
  onToggle: () => void;
}

function Body({ item, viewKind }: Pick<Props, 'item' | 'viewKind'>) {
  if (item.blocked) return <p className="error-box small">{t('io.blockedHelp')}</p>;
  if (viewKind === 'image') return <ImageViewer topic={item.topic} />;
  if (viewKind === 'audio') return <AudioViewer topic={item.topic} needsRate={!item.types[0]?.startsWith('audio_common_msgs/')} />;
  return <EchoView topic={item.topic} autoStart compact />;
}

export function TopicIOItem({ item, open, viewKind, onToggle }: Props) {
  const { select } = useAppState();
  const hz = item.entry && item.entry.monitored ? rateText(item.entry) : t('io.notMonitored');
  return (
    <li className={`io-item${item.blocked ? ' blocked' : ''}`} data-testid={`io-${item.key}`}>
      <div className="io-head">
        <button type="button" className="link mono" aria-expanded={open} onClick={onToggle} data-testid={`io-toggle-${item.key}`}>
          {open ? '▾' : '▸'} {item.topic}
        </button>
        <span className="muted small">{hz}</span>
        <button type="button" className="small" onClick={() => select({ kind: 'topic', id: item.topic })} title={t('io.selectTopic')}>↗</button>
      </div>
      <div className="muted small mono">{item.types.join(', ') || t('common.unknown')}</div>
      {item.blocked && <span className="badge warn-badge">{t('io.blocked')}</span>}
      {item.heavy && !open && <span className="muted small">{t('io.heavyHint')}</span>}
      {open && <Body item={item} viewKind={viewKind} />}
    </li>
  );
}
