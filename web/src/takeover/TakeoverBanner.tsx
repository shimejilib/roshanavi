// Banners under the top bar: leftovers of a force-killed run, the launch takeover's
// error / 「launch ファイルが変更されました」 / what per-node running loses
// (docs/design/integration.md, docs/design/ui.md).

import { useState } from 'react';
import { describeError } from '../api/client';
import { takeoverApi, type TakeoverPending, type TakeoverStatus } from '../api/takeoverTypes';
import { t } from '../i18n';
import { banners, launchLabel, lostCount, NO_DISMISS, type Dismissed } from './model';
import { TakeoverDiffDialog } from './TakeoverDiffDialog';
import { TakeoverReportDialog } from './TakeoverReportDialog';
import { useTakeover } from './useTakeover';

function LeftoverBanner({ count, onDone, onClose }: { count: number; onDone: () => void; onClose: () => void }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const stop = () => {
    setBusy(true);
    takeoverApi
      .stopLeftovers()
      .then((r) => setMessage(r.survivors.length > 0
        ? t('leftovers.failed', { n: r.survivors.length })
        : t('leftovers.done', { n: r.stopped.length })))
      .catch((err: unknown) => setMessage(describeError(err)))
      .finally(() => {
        setBusy(false);
        onDone();
      });
  };
  return (
    <div className="notice-box app-banner" role="alert" data-testid="leftovers-banner">
      <span>{t('leftovers.banner', { n: count })}</span>
      <span className="muted small">{t('leftovers.why')}</span>
      {message && <span role="status">{message}</span>}
      <span className="banner-actions">
        <button type="button" className="danger" disabled={busy} onClick={stop} data-testid="leftovers-stop">
          {busy ? t('leftovers.stopping') : t('leftovers.stop')}
        </button>
        <button type="button" onClick={onClose}>{t('takeover.dismiss')}</button>
      </span>
    </div>
  );
}

function PendingBanner({ pending, onShow, onLater }: { pending: TakeoverPending; onShow: () => void; onLater: () => void }) {
  return (
    <div className="notice-box app-banner" role="alert" data-testid="takeover-changed-banner">
      <span>{pending.reason === 'changed_since_last' ? t('takeover.changedSinceLast') : t('takeover.changed')}</span>
      <span className="banner-actions">
        <button type="button" className="primary" onClick={onShow} data-testid="takeover-show-diff">{t('takeover.show')}</button>
        <button type="button" onClick={onLater} data-testid="takeover-later">{t('takeover.later')}</button>
      </span>
    </div>
  );
}

function LostBanner({ status, onShow, onClose }: { status: TakeoverStatus; onShow: () => void; onClose: () => void }) {
  return (
    <div className="notice-box app-banner" role="status" data-testid="takeover-lost-banner">
      <span>{t('takeover.lostBanner', { n: lostCount(status.report) })}</span>
      <span className="banner-actions">
        <button type="button" onClick={onShow} data-testid="takeover-report-open">{t('takeover.details')}</button>
        <button type="button" onClick={onClose}>{t('takeover.dismiss')}</button>
      </span>
    </div>
  );
}

export function TakeoverBanner() {
  const { status, leftovers, reload, reloadLeftovers } = useTakeover();
  const [dismissed, setDismissed] = useState<Dismissed>(NO_DISMISS);
  const [dialog, setDialog] = useState<'diff' | 'report' | null>(null);
  const [applied, setApplied] = useState<string | null>(null);
  const shown = banners(status, leftovers, dismissed);
  const pending = status?.pending ?? null;
  return (
    <>
      {shown.includes('leftovers') && leftovers && (
        <LeftoverBanner count={leftovers.count} onDone={reloadLeftovers}
          onClose={() => setDismissed((d) => ({ ...d, leftovers: true }))} />
      )}
      {shown.includes('error') && status?.error && (
        <div className="error-box app-banner" role="alert" data-testid="takeover-error-banner">
          {t('takeover.error', { file: launchLabel(status), message: status.error.message })}
        </div>
      )}
      {shown.includes('pending') && pending && (
        <PendingBanner pending={pending} onShow={() => setDialog('diff')}
          onLater={() => setDismissed((d) => ({ ...d, pending: pending.preview_id }))} />
      )}
      {shown.includes('lost') && status && (
        <LostBanner status={status} onShow={() => setDialog('report')}
          onClose={() => setDismissed((d) => ({ ...d, lost: true }))} />
      )}
      {applied && (
        <p className="ok-box app-banner" role="status" data-testid="takeover-applied">
          {applied}{' '}
          <button type="button" className="link" onClick={() => setApplied(null)}>{t('takeover.dismiss')}</button>
        </p>
      )}
      {dialog === 'diff' && pending && status && (
        <TakeoverDiffDialog status={status} pending={pending} onClose={() => setDialog(null)}
          onApplied={(text) => {
            setDialog(null);
            setApplied(text);
            reload();
          }} />
      )}
      {dialog === 'report' && status?.report && (
        <TakeoverReportDialog status={status} report={status.report} onClose={() => setDialog(null)} />
      )}
    </>
  );
}
