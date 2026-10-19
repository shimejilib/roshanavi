// One topic row of the traffic table (+ its expander) and the shared cells.

import type { TrafficEntry } from '../api/types';
import { STALE_AFTER_SEC } from '../graph/model';
import { t, type MessageKey } from '../i18n';
import { ageSec, formatBytes, formatHz, formatMs, formatPercent, formatRate } from '../lib/format';
import { hzBasisHelp, hzBasisNote, rateText } from '../timing/timing';
import { trafficErrorText } from './measurement';
import { NotMeasured } from './NotMeasured';
import { isNotMeasured, NO_VALUE, notMeasuredBandwidth, notMeasuredHz, tracedTopicHz } from './notMeasured';
import { Sparkline } from './Sparkline';

export function isStale(entry: TrafficEntry, nowMs: number): boolean {
  if (entry.status !== 'ok' || !entry.monitored) return false;
  if (entry.stale) return true;
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
    return <span className="badge muted-badge" title={trafficErrorText(entry.error)}>{t(key)}</span>;
  }
  return stale ? <span className="badge stale-badge">{t('traffic.stale')}</span> : null;
}

export function HzValue({ entry }: { entry: TrafficEntry }) {
  const note = entry.rate_note ? null : hzBasisNote(entry.hz_basis, entry.hz, entry.stale);
  return (
    <>
      {entry.rate_note ? <span data-testid={`rate-note-${entry.rate_note}`}>{rateText(entry)}</span> : formatHz(entry.hz)}
      {note && <span className="muted small basis-note"> {note}</span>}{' '}
      <span className="info-tip" title={hzBasisHelp(entry.hz_basis)} tabIndex={0} aria-label={hzBasisHelp(entry.hz_basis)}>ⓘ</span>
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

/** Numbers of a topic nobody measures: no `0 Hz`, no `未受信`; with 詳細計測モード the traced Hz (#61). */
function NotMeasuredCells({ entry }: { entry: TrafficEntry }) {
  return (
    <>
      <td className="num" data-testid={`off-hz-${entry.topic}`}>
        {notMeasuredHz(entry)}
        {tracedTopicHz(entry) != null && <span className="muted small"> {t('monitor.traced')}</span>}
      </td>
      <td className="num wrap-note">{notMeasuredBandwidth(entry)}</td>
      {[0, 1, 2, 3, 4].map((i) => <td key={i} className="num">{NO_VALUE}</td>)}
      <td />
    </>
  );
}

interface RowProps {
  entry: TrafficEntry;
  nowMs: number;
  color: string;
  onSelect: () => void;
  expanded: boolean;
  onToggle: () => void;
}

export function TrafficRow({ entry, nowMs, color, onSelect, expanded, onToggle }: RowProps) {
  const stale = isStale(entry, nowMs);
  const off = isNotMeasured(entry);
  const count = (entry.publishers?.length ?? 0) + (entry.subscribers?.length ?? 0);
  return (
    <tr className={stale ? 'row-stale' : undefined} onClick={onSelect} data-topic={entry.topic}>
      <td className="topic-cell">
        <div className="topic-head">
          <button
            type="button"
            className="expander"
            aria-expanded={expanded}
            aria-label={t(expanded ? 'traffic.collapseTopic' : 'traffic.expandTopic', { topic: entry.topic })}
            onClick={(e) => {
              e.stopPropagation();
              onToggle();
            }}
            data-testid={`expand-${entry.topic}`}
          >
            {expanded ? '▾' : '▸'}
          </button>
          <span className="mono">{entry.topic}</span>
          <span className="muted small">{t('traffic.endpointCount', { n: count })}</span>
        </div>
        <div className="muted small">{entry.type}</div>
        {off ? <NotMeasured entry={entry} /> : <StatusBadge entry={entry} stale={stale} />}
      </td>
      {off ? <NotMeasuredCells entry={entry} /> : (
        <>
          <td className="num"><HzValue entry={entry} /></td>
          <td className="num">{formatRate(entry.bytes_per_sec)}</td>
          <td className="num">{formatBytes(entry.avg_size)}</td>
          <td className="num">{formatMs(entry.jitter_ms)}</td>
          <td className="num"><DropCell entry={entry} /></td>
          <td className="num" title={t('traffic.latencyHelp')}>{formatMs(entry.latency_ms)}</td>
          <td className="num">{lastSeenText(entry, nowMs)}</td>
          <td><Sparkline values={entry.history} color={color} /></td>
        </>
      )}
    </tr>
  );
}
