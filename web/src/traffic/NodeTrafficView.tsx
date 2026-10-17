// ノード別: what each node sends and receives, with rates (same values as the topic rows).

import type { TrafficEntry } from '../api/types';
import { t } from '../i18n';
import { useAppState } from '../state/AppState';
import { groupByNode } from './endpoints';
import { DirectionLabel, RateCells, RowBasisBadge, TraceInfo } from './EndpointCells';

export function NodeTrafficView({ entries }: { entries: TrafficEntry[] }) {
  const { select } = useAppState();
  const groups = groupByNode(entries);
  return (
    <table className="traffic-table node-traffic" data-testid="node-traffic">
      <thead>
        <tr>
          <th>{t('traffic.byNode.node')}</th>
          <th>{t('traffic.byNode.dir')}</th>
          <th>{t('traffic.topic')}</th>
          <th className="num">{t('traffic.hz')}</th>
          <th className="num">{t('traffic.bandwidth')}</th>
          <th>{t('traffic.byNode.basis')}</th>
        </tr>
      </thead>
      <tbody>
        {groups.length === 0 && (
          <tr><td colSpan={6} className="muted">{t('traffic.empty')}</td></tr>
        )}
        {groups.flatMap((group) =>
          group.rows.map((row, i) => (
            <tr key={`${group.node}-${row.dir}-${row.topic}`} className={i === 0 ? 'node-first' : undefined} onClick={() => select({ kind: 'topic', id: row.topic })}
              data-testid={`node-traffic-${group.node}-${row.dir}-${row.topic}`}>
              <td className="mono">{i === 0 ? group.node : ''}</td>
              <td><DirectionLabel dir={row.dir} /></td>
              <td className="mono">{row.topic}</td>
              <RateCells row={row} />
              <td><RowBasisBadge row={row} /> <TraceInfo row={row} /></td>
            </tr>
          )),
        )}
      </tbody>
    </table>
  );
}
