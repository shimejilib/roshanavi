// "型の定義を見る": the message definition (`ros2 interface show` equivalent).

import { useEffect, useState } from 'react';
import { api, describeError } from '../api/client';
import type { InterfaceInfo } from '../api/nodeTypes';
import { t } from '../i18n';
import { Modal } from '../lib/Modal';
import { useAppState } from '../state/AppState';

export function InterfaceDialog({ type }: { type: string }) {
  const { closeDialog } = useAppState();
  const [info, setInfo] = useState<InterfaceInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    api
      .interfaceDef(type)
      .then((v) => !cancelled && setInfo(v))
      .catch((err: unknown) => !cancelled && setError(describeError(err)));
    return () => {
      cancelled = true;
    };
  }, [type]);
  return (
    <Modal title={t('iface.title', { type })} onClose={closeDialog} wide testId="interface-dialog">
      <p className="muted small">{t('iface.intro')}</p>
      {error && <p className="error-box" role="alert">{error}</p>}
      {!info && !error && <p className="muted">{t('common.loading')}</p>}
      {info && <pre className="echo-body" data-testid="interface-body">{info.expanded}</pre>}
      {info?.truncated && <p className="muted small">{t('iface.truncated')}</p>}
    </Modal>
  );
}
