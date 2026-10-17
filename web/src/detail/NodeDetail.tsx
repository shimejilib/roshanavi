import type { GraphSnapshot } from '../api/types';
import { diagnosticText } from '../graph/diagnosticsText';
import { t, type MessageKey } from '../i18n';
import { useAppState } from '../state/AppState';
import { useLive } from '../state/LiveProvider';
import { NodeControls } from './NodeControls';
import { NodeIO } from './NodeIO';
import { NodeLifecycle } from './NodeLifecycle';
import { NodeLauncher } from './NodeLauncher';
import { NodeLinks } from './NodeLinks';
import { NodeTracing } from './NodeTracing';

export function NodeDetail({ nodeId, graph }: { nodeId: string; graph: GraphSnapshot | null }) {
  const { openDialog } = useAppState();
  const { live } = useLive();
  const node = graph?.nodes.find((n) => n.id === nodeId);
  const edges = graph?.edges.filter((e) => e.node === nodeId) ?? [];
  const diags = graph?.diagnostics.filter((d) => d.nodes.includes(nodeId)) ?? [];
  const role = node?.role ?? 'other';
  return (
    <div className="detail-body">
      <div className="eyebrow">{t('detail.node')}</div>
      <h3 className="mono" data-testid="detail-title">{nodeId}</h3>
      <div className="muted small">
        {t('detail.role')}: <span className={`badge role-${role}`}>{t(`detail.role.${role}` as MessageKey)}</span>
      </div>
      {diags.length > 0 && (
        <ul className="diag-list compact">
          {diags.map((d, i) => (
            <li key={i} className={`sev-${d.severity}`}>{diagnosticText(d)}</li>
          ))}
        </ul>
      )}
      <NodeControls node={node} />
      {node?.lifecycle && <NodeLifecycle nodeId={nodeId} />}
      {node && !node.job_id && (
        <button type="button" onClick={() => openDialog({ kind: 'params', nodeId })} data-testid="detail-params">
          {t('menu.params')}
        </button>
      )}
      <NodeIO nodeId={nodeId} graph={graph} traffic={live.traffic} />
      <NodeTracing nodeId={nodeId} traffic={live.traffic} tracing={live.tracing} />
      <NodeLauncher node={node} />
      <details className="qos-details">
        <summary>{t('io.qosDetails')}</summary>
        <NodeLinks title={t('detail.publishesTo')} edges={edges.filter((e) => e.dir === 'pub')} showTopic />
        <NodeLinks title={t('detail.subscribesTo')} edges={edges.filter((e) => e.dir === 'sub')} showTopic />
      </details>
    </div>
  );
}
