// Right pane: 詳細計測モード values of the selected node (receive / process rate and
// callback time per subscribed topic), or why it cannot be measured.

import type { TrafficEntry } from '../api/types';
import type { TracingStatus } from '../api/tracingTypes';
import { t } from '../i18n';
import { behindHelp, behindText, nodeTraceRows, unsupportedFor, unsupportedReasonText } from '../traffic/tracing';

interface Props {
  nodeId: string;
  traffic: Map<string, TrafficEntry>;
  tracing: TracingStatus | null;
}

export function NodeTracing({ nodeId, traffic, tracing }: Props) {
  if (!tracing?.active) return null;
  const rows = nodeTraceRows(traffic.values(), nodeId);
  const unsupported = unsupportedFor(tracing, nodeId);
  return (
    <section className="node-tracing" data-testid="node-tracing">
      <h4>{t('tracing.node.title')}</h4>
      {unsupported && <p className="warn-text small">{unsupportedReasonText(unsupported.reason)}</p>}
      {rows.length === 0 && !unsupported && <p className="muted small">{t('tracing.node.none')}</p>}
      {rows.length > 0 && (
        <table className="node-trace">
          <thead>
            <tr>
              <th>{t('traffic.topic')}</th>
              <th className="num">{t('tracing.recv')}</th>
              <th className="num">{t('tracing.processed')}</th>
              <th>{t('tracing.cbTime')}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.topic} title={row.symbol ? `${t('tracing.node.callback')}: ${row.symbol}` : undefined}>
                <td className="mono">
                  {row.topic}
                  {row.behind && <div className="warn-text" title={behindHelp(row.behind)}>⚠ {behindText(row.behind)}</div>}
                </td>
                <td className="num">{row.cells.recv}</td>
                <td className="num" title={row.cells.note ?? undefined}>{row.cells.processed}</td>
                <td title={row.cells.note ?? undefined}>{row.cells.cb}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
