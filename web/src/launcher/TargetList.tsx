import { useState } from 'react';
import { api, describeError } from '../api/client';
import type { Target, TargetSpec } from '../api/types';
import { t, type MessageKey } from '../i18n';
import { isAlive, statusClass, statusLabel, uptimeText } from './status';

interface Props {
  targets: Target[];
  selectedLog: string | null;
  onLogs: (id: string) => void;
  onEdit: (spec: TargetSpec) => void;
}

function NodesLine({ target }: { target: Target }) {
  const nodes = target.nodes ?? [];
  if (!isAlive(target)) return null;
  if (!nodes.length) return <div className="muted small">{t('launcher.nodes')}: {t('launcher.noNodes')}</div>;
  return (
    <div className="small target-nodes">
      {t('launcher.nodes')}:{' '}
      {nodes.map((n) => (
        <span key={n.node} className="node-chip mono" title={t(`launcher.confidenceHelp.${n.confidence}` as MessageKey)}>
          {n.node} <span className={`badge conf-${n.confidence}`}>{t(`launcher.confidence.${n.confidence}` as MessageKey)}</span>
        </span>
      ))}
    </div>
  );
}

function TargetCard({ target, active, onLogs, onEdit, onError }: { target: Target; active: boolean; onLogs: Props['onLogs']; onEdit: Props['onEdit']; onError: (msg: string | null) => void }) {
  const [busy, setBusy] = useState(false);
  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    onError(null);
    try {
      await fn();
    } catch (err) {
      onError(describeError(err));
    } finally {
      setBusy(false);
    }
  };
  const alive = isAlive(target);
  const uptime = uptimeText(target);
  return (
    <li className={`target-card ${statusClass(target.status)}${active ? ' active' : ''}`} data-testid={`target-${target.id}`}>
      <div className="target-head">
        <span className="mono target-id">{target.id}</span>
        <span className={`badge role-${target.role}`}>{t(`launcher.role.${target.role}` as MessageKey)}</span>
        <span className={`status-chip ${statusClass(target.status)}`} data-testid={`target-status-${target.id}`} data-status={target.status}>
          {statusLabel(target)}
        </span>
      </div>
      {target.command && <code className="mono small command-line" title={target.command.join(' ')}>{target.command.slice(1).join(' ')}</code>}
      <div className="muted small">
        {[uptime, target.restart_count ? t('launcher.restarts', { n: target.restart_count }) : null].filter(Boolean).join(' · ')}
      </div>
      <NodesLine target={target} />
      {target.problem && <div className="error-text small">{target.problem}</div>}
      {target.pending_restart && <div className="warn-text small">{t('launcher.pendingRestart')}</div>}
      <div className="row">
        {alive ? (
          <button type="button" disabled={busy} onClick={() => void act(() => api.targetAction(target.id, 'stop'))} data-testid={`target-stop-${target.id}`}>{t('launcher.stop')}</button>
        ) : (
          <button type="button" className="primary" disabled={busy || target.status === 'invalid'} onClick={() => void act(() => api.targetAction(target.id, 'start'))} data-testid={`target-start-${target.id}`}>{t('launcher.start')}</button>
        )}
        <button type="button" disabled={busy || !alive} onClick={() => void act(() => api.targetAction(target.id, 'restart'))}>{t('launcher.restart')}</button>
        <button type="button" onClick={() => onLogs(target.id)} aria-pressed={active}>{t('launcher.logs')}</button>
        {target.kind !== 'dummy' && <button type="button" onClick={() => onEdit(target.spec as TargetSpec)}>{t('common.edit')}</button>}
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            if (window.confirm(t('launcher.removeConfirm', { id: target.id }))) void act(() => api.removeTarget(target.id));
          }}
        >
          {t('common.remove')}
        </button>
      </div>
    </li>
  );
}

export function TargetList({ targets, selectedLog, onLogs, onEdit }: Props) {
  const [error, setError] = useState<string | null>(null);
  return (
    <section className="target-list" aria-labelledby="targets-title">
      <h3 id="targets-title">{t('launcher.targets')}</h3>
      {error && <p className="error-box" role="alert">{error}</p>}
      {targets.length === 0 ? (
        <p className="muted">{t('launcher.noTargets')}</p>
      ) : (
        <ul className="target-cards">
          {targets.map((target) => (
            <TargetCard key={target.id} target={target} active={selectedLog === target.id} onLogs={onLogs} onEdit={onEdit} onError={setError} />
          ))}
        </ul>
      )}
    </section>
  );
}
