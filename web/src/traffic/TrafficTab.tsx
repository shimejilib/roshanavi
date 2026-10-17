import { useMemo, useState } from 'react';
import type { TrafficEntry } from '../api/types';
import { STALE_AFTER_SEC } from '../graph/model';
import { usePalette } from '../graph/usePalette';
import { t, type MessageKey } from '../i18n';
import { ageSec, formatBytes, formatHz, formatMs, formatPercent, formatRate } from '../lib/format';
import { useAppState } from '../state/AppState';
import { useLive } from '../state/LiveProvider';
import { Sparkline } from './Sparkline';
import { sortTraffic, toggleSort, type SortKey, type SortState } from './sort';

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

export function isStale(entry: TrafficEntry, nowMs: number): boolean {
  if (entry.status !== 'ok' || !entry.monitored) return false;
  const age = ageSec(entry.last_seen, nowMs);
  return age == null || age > STALE_AFTER_SEC;
}

function lastSeenText(entry: TrafficEntry, nowMs: number): string {
  const age = ageSec(entry.last_seen, nowMs);
  return age == null ? t('traffic.never') : t('traffic.agoSec', { n: age.toFixed(age < 10 ? 1 : 0) });
}

function StatusBadge({ entry, stale }: { entry: TrafficEntry; stale: boolean }) {
  if (entry.status !== 'ok') {
    const key = `traffic.status.${entry.status}` as MessageKey;
    return <span className="badge muted-badge" title={entry.error ?? undefined}>{t(key)}</span>;
  }
  return stale ? <span className="badge stale-badge">{t('traffic.stale')}</span> : null;
}

function HzCell({ entry }: { entry: TrafficEntry }) {
  const basis = entry.hz_basis;
  const help = basis === 'source' ? t('traffic.basis.sourceHelp') : t('traffic.basis.receiveHelp');
  return (
    <>
      {formatHz(entry.hz)}{' '}
      <span className={`badge basis-${basis}`} title={help} tabIndex={0}>
        {t(`traffic.basis.${basis}`)}
      </span>
    </>
  );
}

function DropCell({ entry }: { entry: TrafficEntry }) {
  if (entry.dropped == null) return <span title={t('traffic.approxHelp')}>—</span>;
  return (
    <span className={entry.dropped > 0 ? 'warn-text' : undefined} title={t('traffic.approxHelp')}>
      {entry.dropped} ({formatPercent(entry.drop_ratio)}) <span className="badge">≈</span>
    </span>
  );
}

function Row({ entry, nowMs, color, onSelect }: { entry: TrafficEntry; nowMs: number; color: string; onSelect: () => void }) {
  const stale = isStale(entry, nowMs);
  return (
    <tr className={stale ? 'row-stale' : undefined} onClick={onSelect} data-topic={entry.topic}>
      <td className="topic-cell">
        <div className="mono">{entry.topic}</div>
        <div className="muted small">{entry.type}</div>
        <StatusBadge entry={entry} stale={stale} />
      </td>
      <td className="num"><HzCell entry={entry} /></td>
      <td className="num">{formatRate(entry.bytes_per_sec)}</td>
      <td className="num">{formatBytes(entry.avg_size)}</td>
      <td className="num">{formatMs(entry.jitter_ms)}</td>
      <td className="num"><DropCell entry={entry} /></td>
      <td className="num" title={t('traffic.latencyHelp')}>{formatMs(entry.latency_ms)}</td>
      <td className="num">{lastSeenText(entry, nowMs)}</td>
      <td><Sparkline values={entry.history} color={color} /></td>
    </tr>
  );
}

export function TrafficTab() {
  const { live } = useLive();
  const { select } = useAppState();
  const palette = usePalette();
  const [sort, setSort] = useState<SortState>({ key: 'topic', desc: false });
  const [showCollapsed, setShowCollapsed] = useState(false);
  const nowMs = live.receivedAt || Date.now();

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
      </div>
      <div className="table-wrap">
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
              <Row key={entry.topic} entry={entry} nowMs={nowMs} color={palette.edge} onSelect={() => select({ kind: 'topic', id: entry.topic })} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
