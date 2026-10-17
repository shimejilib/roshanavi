// "lifecycle の状態を変える": current state + allowed transitions (ROS lifecycle services, no signals).

import { useCallback, useEffect, useState } from 'react';
import { api, describeError } from '../api/client';
import type { LifecycleInfo, LifecycleTransition } from '../api/nodeListTypes';
import { t } from '../i18n';
import { ConfirmDialog } from '../lib/ConfirmDialog';
import { Modal } from '../lib/Modal';
import { lifecycleStateText } from '../nodelist/rowText';
import { useAppState } from '../state/AppState';
import { confirmTransitionText, offeredTransitions, transitionHelp, transitionLabel } from './lifecycleText';

export function LifecycleDialog({ nodeId }: { nodeId: string }) {
  const { closeDialog } = useAppState();
  const [info, setInfo] = useState<LifecycleInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState<LifecycleTransition | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api
      .lifecycle(nodeId)
      .then((body) => {
        setInfo(body);
        setError(null);
      })
      .catch((err: unknown) => setError(describeError(err)));
  }, [nodeId]);
  useEffect(load, [load]);

  const external = info?.role === 'other';
  const run = (label: LifecycleTransition) => {
    setAsking(null);
    setBusy(true);
    api
      .changeLifecycle(nodeId, { transition: label, allow_external: external })
      .then((body) => {
        setInfo(body);
        setError(null);
      })
      .catch((err: unknown) => setError(describeError(err)))
      .finally(() => setBusy(false));
  };

  return (
    <Modal title={t('lifecycle.title', { node: nodeId })} onClose={closeDialog} testId="lifecycle-dialog">
      <p className="muted small">{t('lifecycle.intro')}</p>
      {error && <p className="error-box" role="alert">{error}</p>}
      {!info && !error && <p className="muted">{t('common.loading')}</p>}
      {info && (
        <>
          <p>
            {t('lifecycle.current')}{' '}
            <span className={`badge lc-${info.state.label}`} data-testid="lifecycle-state">{lifecycleStateText(info.state.label)}</span>
          </p>
          {external && <p className="notice-box small">{t('lifecycle.externalNote')}</p>}
          <div className="lifecycle-actions">
            {offeredTransitions(info).map((label) => (
              <button
                key={label}
                type="button"
                disabled={busy}
                title={transitionHelp(label)}
                className={label === 'deactivate' || label === 'cleanup' ? 'danger' : undefined}
                onClick={() => setAsking(label)}
                data-testid={`lifecycle-${label}`}
              >
                {transitionLabel(label)}
              </button>
            ))}
            {offeredTransitions(info).length === 0 && <span className="muted small">{t('lifecycle.noTransitions')}</span>}
          </div>
        </>
      )}
      <div className="row end">
        <button type="button" onClick={load}>{t('params.reload')}</button>
        <button type="button" onClick={closeDialog}>{t('common.close')}</button>
      </div>
      {asking && (
        <ConfirmDialog
          title={t('lifecycle.confirmTitle')}
          text={confirmTransitionText(nodeId, asking, external)}
          okLabel={transitionLabel(asking)}
          onOk={() => run(asking)}
          onCancel={() => setAsking(null)}
        />
      )}
    </Modal>
  );
}
