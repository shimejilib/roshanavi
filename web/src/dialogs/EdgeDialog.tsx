// Edge menu: "QoS の詳細" and "届かない理由" (both sides' QoS + plain-language reasons).

import { edgeDetails, qosCells } from '../graph/edgeInfo';
import { t } from '../i18n';
import { Modal } from '../lib/Modal';
import { Term } from '../lib/Term';
import { useAppState } from '../state/AppState';
import { useLive } from '../state/LiveProvider';

interface Props {
  topic: string;
  node: string;
  dir: 'pub' | 'sub';
}

const HEADERS = ['edge.reliability', 'edge.durability', 'edge.depth', 'edge.deadline', 'edge.liveliness'] as const;

export function EdgeDialog({ topic, node, dir }: Props) {
  const { closeDialog } = useAppState();
  const { live } = useLive();
  const info = edgeDetails(live.graph, topic, node, dir, live.traffic.get(topic));
  return (
    <Modal title={t('edge.title', { topic })} onClose={closeDialog} wide testId="edge-dialog">
      <h4>{t('edge.reasons')}</h4>
      {info.reasons.length === 0 ? (
        <p className="ok-text">{t('edge.noProblem')}</p>
      ) : (
        <ul className="diag-list compact">
          {info.reasons.map((r) => <li key={r} className="sev-error">{r}</li>)}
        </ul>
      )}
      <h4>{t('edge.qos')} <Term term="qos" /></h4>
      <table className="params-table">
        <thead>
          <tr>
            <th>{t('edge.endpoint')}</th>
            {HEADERS.map((h) => <th key={h}>{t(h)}</th>)}
          </tr>
        </thead>
        <tbody>
          {info.endpoints.map((e) => (
            <tr key={`${e.dir}:${e.node}`} className={e.node === node && e.dir === dir ? 'row-highlight' : undefined}>
              <td className="mono">{e.dir === 'pub' ? t('edge.sends') : t('edge.receives')} {e.node}</td>
              {qosCells(e).map((cell, i) => <td key={HEADERS[i]}>{cell}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </Modal>
  );
}
