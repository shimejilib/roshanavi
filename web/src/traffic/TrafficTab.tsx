import { Fragment, useMemo, useState } from 'react';
import { usePalette } from '../graph/usePalette';
import { t, type MessageKey } from '../i18n';
import { useAppState } from '../state/AppState';
import { useLive } from '../state/LiveProvider';
import { LastUpdateBadge } from '../timing/LastUpdate';
import { WindowSelect } from '../timing/WindowSelect';
import { toggleAllTopics, toggleTopic } from './endpoints';
import { measurementNote } from './measurement';
import { EndpointRows } from './EndpointRows';
import { NodeTrafficView } from './NodeTrafficView';
import { sortTraffic, toggleSort, type SortKey, type SortState } from './sort';
import { TrafficRow } from './TrafficRow';
import { TracingStatusBar } from './TracingStatusBar';
import { TracingToggle } from './TracingToggle';

type View = 'topic' | 'node';

const COLUMNS: { key: SortKey; label: MessageKey; numeric: boolean }[] = [
  { key: 'topic', label: 'traffic.topic', numeric: false },
  { key: 'hz', label: 'traffic.hz', numeric: true },
  { key: 'bytes_per_sec', label: 'traffic.bandwidth', numeric: true },
  { key: 'avg_size', label: 'traffic.avgSize', numeric: true },
  { key: 'jitter_ms', label: 'traffic.jitter', numeric: true },
  { key: 'drop_ratio', label: 'traffic.dropped', numeric: true },
  { key: 'latency_ms', label: 'traffic.latency', numeric: true },
  { key: 'last_seen', label: 'traffic.lastSeen', numeric: true },
];

export function TrafficTab() {
  const { live } = useLive();
  const { select } = useAppState();
  const palette = usePalette();
  const [sort, setSort] = useState<SortState>({ key: 'topic', desc: false });
  const [showCollapsed, setShowCollapsed] = useState(false);
  const [view, setView] = useState<View>('topic');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const nowMs = live.receivedAt || Date.now();
  const note = measurementNote(live.measurement);

  const rows = useMemo(() => {
    const all = [...live.traffic.values()].filter((e) => showCollapsed || !e.collapsed);
    return sortTraffic(all, sort);
  }, [live.traffic, sort, showCollapsed]);

  return (
    <div className="traffic-tab">
      <div className="toolbar">
        <label className="check">
          <input type="checkbox" checked={showCollapsed} onChange={(e) => setShowCollapsed(e.target.checked)} />
          {t('traffic.showCollapsed')}
        </label>
        <div role="radiogroup" aria-label={t('traffic.view')} className="segmented" data-tour="traffic-view">
          {(['topic', 'node'] as const).map((v) => (
            <label key={v} className={view === v ? 'seg active' : 'seg'} data-testid={`traffic-view-${v}`}>
              <input type="radio" name="traffic-view" checked={view === v} onChange={() => setView(v)} />
              {t(`traffic.view.${v}`)}
            </label>
          ))}
        </div>
        {view === 'topic' && (
          <button type="button" onClick={() => setExpanded((prev) => toggleAllTopics(prev, rows.map((r) => r.topic)))} data-testid="traffic-expand-all">
            {rows.length > 0 && rows.every((r) => expanded.has(r.topic)) ? t('traffic.collapseAll') : t('traffic.expandAll')}
          </button>
        )}
        <WindowSelect />
        <TracingToggle status={live.tracing} />
        {note && (
          <span className={note.level === 'warn' ? 'measurement-note warn-text small' : 'measurement-note muted small'}
            title={note.help} data-testid="traffic-measurement">{note.text}</span>
        )}
        <span className="spacer" />
        <LastUpdateBadge />
      </div>
      <TracingStatusBar status={live.tracing} />
      <div className="table-wrap">
        {view === 'node' ? <NodeTrafficView entries={rows} /> : (
        <table className="traffic-table">
          <thead>
            <tr>
              {COLUMNS.map((col) => (
                <th key={col.key} className={col.numeric ? 'num' : undefined} aria-sort={sort.key === col.key ? (sort.desc ? 'descending' : 'ascending') : 'none'}>
                  <button type="button" className="th-button" onClick={() => setSort(toggleSort(sort, col.key))}>
                    {t(col.label)} {sort.key === col.key ? (sort.desc ? '▼' : '▲') : ''}
                  </button>
                </th>
              ))}
              <th>{t('traffic.history')}</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr>
                <td colSpan={COLUMNS.length + 1} className="muted">{t('traffic.empty')}</td>
              </tr>
            )}
            {rows.map((entry) => (
              <Fragment key={entry.topic}>
                <TrafficRow entry={entry} nowMs={nowMs} color={palette.edge} onSelect={() => select({ kind: 'topic', id: entry.topic })}
                  expanded={expanded.has(entry.topic)} onToggle={() => setExpanded((prev) => toggleTopic(prev, entry.topic))} />
                {expanded.has(entry.topic) && <EndpointRows entry={entry} span={COLUMNS.length + 1} />}
              </Fragment>
            ))}
          </tbody>
        </table>
        )}
      </div>
    </div>
  );
}
