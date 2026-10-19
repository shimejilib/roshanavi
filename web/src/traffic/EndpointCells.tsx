// Cells shared by the per-endpoint rows: direction, Hz / bandwidth, the basis badge and the
// 詳細計測モード values (受信 / 処理 / 処理時間, 処理が追いついていない).

import { t } from '../i18n';
import { formatHz } from '../lib/format';
import { basisHelp, basisLabel, displayBasis, endpointBandwidth, endpointHz, type EndpointRow } from './endpoints';
import { behindHelp, behindText, traceCells } from './tracing';

export function DirectionLabel({ dir }: { dir: EndpointRow['dir'] }) {
  return <span className={`dir-label dir-${dir}`}>{dir === 'pub' ? `↑ ${t('traffic.dir.pub')}` : `↓ ${t('traffic.dir.sub')}`}</span>;
}

export function BasisBadge({ basis }: { basis: string }) {
  const help = basisHelp(basis);
  return (
    <span className={`badge basis-${basis}`} title={help} tabIndex={0} aria-label={`${basisLabel(basis)}: ${help}`}>
      {basisLabel(basis)} ⓘ
    </span>
  );
}

export function RowBasisBadge({ row }: { row: EndpointRow }) {
  return <BasisBadge basis={displayBasis(row)} />;
}

export function RateCells({ row }: { row: EndpointRow }) {
  return (
    <>
      <td className={row.delivered ? 'num' : 'num error-text'}>{endpointHz(row)}</td>
      <td className="num wrap-note">{endpointBandwidth(row)}</td>
    </>
  );
}

/** 受信 / 処理 / 処理時間 (+ warning) of a traced subscriber; the trace's send count for publishers. */
export function TraceInfo({ row }: { row: EndpointRow }) {
  if (row.dir === 'pub') {
    return row.hzTraced == null || row.basis === 'traced' ? null : <span className="muted small">{t('tracing.tracedPub', { hz: formatHz(row.hzTraced) })}</span>;
  }
  const cells = traceCells(row.trace, row.basis);
  if (!cells) return null;
  const behind = row.trace?.behind;
  return (
    <span className="trace-info small" data-testid={`trace-${row.topic}-${row.node}`}>
      <span>{t('tracing.recv')} <b>{cells.recv}</b></span>
      <span title={cells.note ?? undefined}>{t('tracing.processed')} <b>{cells.processed}</b></span>
      <span title={cells.note ?? undefined}>{t('tracing.cbTime')} {cells.cb}</span>
      {behind && (
        <span className="warn-text" role="status" title={behindHelp(behind)} data-testid={`trace-behind-${row.node}`}>
          ⚠ {behindText(behind)}
        </span>
      )}
    </span>
  );
}
