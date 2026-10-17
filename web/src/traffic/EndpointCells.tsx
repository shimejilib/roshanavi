// Cells shared by the per-endpoint rows: direction, Hz / bandwidth and the basis badge.

import { t } from '../i18n';
import { basisHelp, basisLabel, endpointBandwidth, endpointHz, type EndpointRow } from './endpoints';

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

export function RateCells({ row }: { row: EndpointRow }) {
  return (
    <>
      <td className={row.delivered ? 'num' : 'num error-text'}>{endpointHz(row)}</td>
      <td className="num">{endpointBandwidth(row)}</td>
    </>
  );
}
