// Child rows under an expanded topic: one per publisher and per subscriber.

import { topicEndpoints } from './endpoints';
import { BasisBadge, DirectionLabel, RateCells } from './EndpointCells';
import type { TrafficEntry } from '../api/types';
import { t } from '../i18n';

export function EndpointRows({ entry, span }: { entry: TrafficEntry; span: number }) {
  const rows = topicEndpoints(entry);
  if (rows.length === 0) {
    return (
      <tr className="endpoint-row">
        <td colSpan={span} className="muted small">{t('traffic.noEndpoints')}</td>
      </tr>
    );
  }
  return (
    <>
      {rows.map((row) => (
        <tr key={`${row.dir}-${row.node}`} className="endpoint-row" data-testid={`endpoint-${entry.topic}-${row.dir}-${row.node}`}>
          <td className="endpoint-cell">
            <DirectionLabel dir={row.dir} /> <span className="mono">{row.node}</span> <BasisBadge basis={row.basis} />
          </td>
          <RateCells row={row} />
          <td colSpan={span - 3} />
        </tr>
      ))}
    </>
  );
}
