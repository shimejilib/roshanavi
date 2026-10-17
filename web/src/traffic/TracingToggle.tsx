// Toolbar switch for 詳細計測モード: explains the cost in a dialog before turning it on;
// disabled with install guidance when LTTng is missing.

import { useState } from 'react';
import { api, describeError } from '../api/client';
import type { TracingStatus } from '../api/tracingTypes';
import { t } from '../i18n';
import { Modal } from '../lib/Modal';
import { BENCH_SUMMARY, tracingUnavailableText } from './tracing';

function ExplainDialog({ onEnable, onClose, busy, error }: { onEnable: () => void; onClose: () => void; busy: boolean; error: string | null }) {
  return (
    <Modal title={t('tracing.dialog.title')} onClose={onClose} wide testId="tracing-dialog">
      <p>{t('tracing.dialog.what')}</p>
      <h4>{t('tracing.dialog.target')}</h4>
      <ul className="small">
        <li>{t('tracing.dialog.target1')}</li>
        <li>{t('tracing.dialog.target2')}</li>
      </ul>
      <h4>{t('tracing.dialog.self')}</h4>
      <ul className="small">
        <li>{t('tracing.dialog.self1')}</li>
        <li>{t('tracing.dialog.self2')}</li>
        <li>{t('tracing.dialog.self3')}</li>
        <li>{t('tracing.dialog.self4')}</li>
      </ul>
      {BENCH_SUMMARY && <p className="muted small">{t('tracing.dialog.bench', { bench: BENCH_SUMMARY })}</p>}
      <p className="muted small">{t('tracing.dialog.limits')}</p>
      {error && <p className="error-text small" role="alert" style={{ whiteSpace: 'pre-line' }}>{error}</p>}
      <div className="modal-actions">
        <button type="button" onClick={onClose}>{t('tracing.dialog.cancel')}</button>
        <button type="button" className="primary" onClick={onEnable} disabled={busy} data-testid="tracing-enable">
          {busy ? t('tracing.enabling') : t('tracing.dialog.enable')}
        </button>
      </div>
    </Modal>
  );
}

export function TracingToggle({ status }: { status: TracingStatus | null }) {
  const [dialog, setDialog] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!status) return null;
  const unavailable = tracingUnavailableText(status);

  const change = async (enabled: boolean) => {
    setBusy(true);
    setError(null);
    try {
      await api.setTracing(enabled);
      setDialog(false);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <label className={unavailable ? 'check disabled' : 'check'} title={unavailable ?? t('tracing.toggleHelp')} data-testid="tracing-toggle">
        <input
          type="checkbox"
          checked={status.active}
          disabled={!!unavailable || busy}
          onChange={(e) => (e.target.checked ? setDialog(true) : void change(false))}
        />
        {t('tracing.toggle')}
      </label>
      {unavailable && <span className="muted small" data-testid="tracing-unavailable">{unavailable}</span>}
      {error && !dialog && <span className="error-text small" role="alert">{error}</span>}
      {dialog && <ExplainDialog onEnable={() => void change(true)} onClose={() => setDialog(false)} busy={busy} error={error} />}
    </>
  );
}
