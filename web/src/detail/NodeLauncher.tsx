import type { GraphNode } from '../api/types';
import { FunctionStatusPanel } from '../function/FunctionStatusPanel';
import { t, type MessageKey } from '../i18n';
import { statusClass, statusLabel } from '../launcher/status';
import { formatDuration } from '../lib/format';
import { useAppState } from '../state/AppState';
import type { DialogRequest } from '../dialogs/dialogTypes';
import { useLive } from '../state/LiveProvider';

/** Right-pane section: which launcher target owns this node, its process, quick actions. */
/** The dialog that edits a node the tool itself made (input / transform / function). */
function editDialogFor(target: { id: string; kind: string }): { label: MessageKey; dialog: DialogRequest } | null {
  switch (target.kind) {
    case 'dummy':
      return { label: 'menu.editDummy', dialog: { kind: 'createInput', dummyId: target.id } };
    case 'transform':
      return { label: 'menu.editTransform', dialog: { kind: 'createTransform', transformId: target.id } };
    case 'function':
      return { label: 'menu.editFunction', dialog: { kind: 'createFunction', functionId: target.id } };
    default:
      return null;
  }
}

export function NodeLauncher({ node }: { node: GraphNode | undefined }) {
  const { live } = useLive();
  const { openLogs, openDialog } = useAppState();
  if (!node || node.id.startsWith('dummy:')) return null;
  const target = node.target_id ? live.targets.find((tg) => tg.id === node.target_id) : undefined;
  if (!target) {
    return (
      <section>
        <h4>{t('detail.launcher')}</h4>
        <p className="muted small">{t('detail.notLaunched')}</p>
      </section>
    );
  }
  const mapped = target.nodes?.find((n) => n.node === node.id);
  const edit = editDialogFor(target);
  const confidence = node.confidence ?? mapped?.confidence ?? 'heuristic';
  return (
    <section data-testid="node-launcher">
      <h4>{t('detail.launcher')}</h4>
      <dl className="stats">
        <dt>{t('detail.target')}</dt>
        <dd>{target.id}</dd>
        <dt>{t('detail.process')}</dt>
        <dd>
          <span className={`status-chip ${statusClass(target.status)}`}>{statusLabel(target)}</span>
          {mapped?.pid ? ` pid ${mapped.pid}` : target.pid ? ` pid ${target.pid}` : ''}
        </dd>
        <dt>{t('detail.mapping')}</dt>
        <dd title={t(`launcher.confidenceHelp.${confidence}` as MessageKey)}>
          <span className={`badge conf-${confidence}`}>{t(`launcher.confidence.${confidence}` as MessageKey)}</span>
        </dd>
        <dt>{t('detail.uptime')}</dt>
        <dd>{target.uptime_sec == null ? '—' : formatDuration(target.uptime_sec)}</dd>
      </dl>
      <p className="muted small">{t(`launcher.confidenceHelp.${confidence}` as MessageKey)}</p>
      <div className="row">
        <button type="button" onClick={() => openLogs(target.id)} data-testid="node-logs">{t('detail.openLogs')}</button>
        {edit && (
          <button type="button" onClick={() => openDialog(edit.dialog)} data-testid="node-edit" data-tour="node-edit">{t(edit.label)}</button>
        )}
      </div>
      {target.kind === 'function' && <FunctionStatusPanel target={target} />}
    </section>
  );
}
