// "パラメータを見る・変更する": list / change a node's parameters (parameter services).
// Nodes roshanavi did not start are read-only until the user confirms.

import { useCallback, useEffect, useState } from 'react';
import { api, describeError } from '../api/client';
import type { ParamInfo, ParamsResponse } from '../api/nodeTypes';
import { t } from '../i18n';
import { ConfirmDialog } from '../lib/ConfirmDialog';
import { Modal } from '../lib/Modal';
import { Term } from '../lib/Term';
import { useAppState } from '../state/AppState';
import { ParamRow } from './ParamRow';

export function ParamsDialog({ nodeId }: { nodeId: string }) {
  const { closeDialog } = useAppState();
  const [data, setData] = useState<ParamsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [unlocked, setUnlocked] = useState(false);
  const [asking, setAsking] = useState(false);

  const load = useCallback(() => {
    setError(null);
    api
      .parameters(nodeId)
      .then(setData)
      .catch((err: unknown) => setError(describeError(err)));
  }, [nodeId]);
  useEffect(load, [load]);

  const save = async (param: ParamInfo, value: ParamInfo['value']) => {
    if (param.type === 'not_set') return;
    await api.setParameter(nodeId, { name: param.name, type: param.type, value, allow_external: unlocked });
    load();
  };

  return (
    <Modal title={t('params.title', { node: nodeId })} onClose={closeDialog} wide testId="params-dialog">
      <p className="muted small">
        {t('params.intro')} <Term term="parameter" />
      </p>
      {error && <p className="error-box" role="alert">{error}</p>}
      {!data && !error && <p className="muted">{t('common.loading')}</p>}
      {data?.external && (
        <div className="notice-box" data-testid="params-external">
          {t(unlocked ? 'params.externalUnlocked' : 'params.external')}{' '}
          {!unlocked && <button type="button" onClick={() => setAsking(true)} data-testid="params-unlock">{t('params.unlock')}</button>}
        </div>
      )}
      {data && data.parameters.length === 0 && <p className="muted">{t('params.none')}</p>}
      {data && data.parameters.length > 0 && (
        <table className="params-table" data-testid="params-table">
          <thead>
            <tr><th>{t('params.name')}</th><th>{t('params.type')}</th><th>{t('params.value')}</th></tr>
          </thead>
          <tbody>
            {data.parameters.map((p) => (
              <ParamRow key={p.name} param={p} external={data.external} unlocked={unlocked} onSave={save} />
            ))}
          </tbody>
        </table>
      )}
      <div className="row end">
        <button type="button" onClick={load}>{t('params.reload')}</button>
        <button type="button" onClick={closeDialog}>{t('common.close')}</button>
      </div>
      {asking && (
        <ConfirmDialog
          title={t('params.unlockTitle')}
          text={t('params.unlockText', { node: nodeId })}
          okLabel={t('params.unlockOk')}
          onOk={() => { setUnlocked(true); setAsking(false); }}
          onCancel={() => setAsking(false)}
        />
      )}
    </Modal>
  );
}
