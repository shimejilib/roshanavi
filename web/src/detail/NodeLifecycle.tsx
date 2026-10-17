// Right pane: lifecycle state of a managed node and a button to change it.

import { useEffect, useState } from 'react';
import { api, describeError } from '../api/client';
import { t } from '../i18n';
import { lifecycleStateText } from '../nodelist/rowText';
import { useAppState } from '../state/AppState';

const REFRESH_MS = 3000;

export function NodeLifecycle({ nodeId }: { nodeId: string }) {
  const { openDialog, dialog } = useAppState();
  const [state, setState] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .lifecycle(nodeId)
        .then((info) => alive && (setState(info.state.label), setError(null)))
        .catch((err: unknown) => alive && setError(describeError(err)));
    void load();
    const timer = setInterval(load, REFRESH_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [nodeId, dialog]);
  return (
    <section data-testid="node-lifecycle">
      <h4>{t('lifecycle.section')}</h4>
      <p className="small">
        {t('lifecycle.current')} <span className={`badge lc-${state ?? 'unknown'}`}>{lifecycleStateText(state)}</span>
      </p>
      {error && <p className="error-box small">{error}</p>}
      <button type="button" onClick={() => openDialog({ kind: 'lifecycle', nodeId })} data-testid="detail-lifecycle">
        {t('lifecycle.open')}
      </button>
    </section>
  );
}
