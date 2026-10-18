// 「launch ファイルを取り込み直す」: added / removed / changed nodes, then apply (only the changed
// nodes restart).

import { useState } from 'react';
import { describeError } from '../api/client';
import { takeoverApi, type DiffEntry, type TakeoverPending, type TakeoverStatus } from '../api/takeoverTypes';
import { t } from '../i18n';
import { Modal } from '../lib/Modal';
import { changedText, entryText, launchLabel } from './model';
import { ReportBody } from './TakeoverReportDialog';

function Section({ title, items, render, testId }: { title: string; items: DiffEntry[]; render: (e: DiffEntry) => string; testId: string }) {
  if (items.length === 0) return null;
  return (
    <>
      <h4>{title}</h4>
      <ul data-testid={testId}>{items.map((e) => <li key={e.id} className="mono">{render(e)}</li>)}</ul>
    </>
  );
}

interface Props {
  status: TakeoverStatus;
  pending: TakeoverPending;
  onClose: () => void;
  onApplied: (text: string) => void;
}

export function TakeoverDiffDialog({ status, pending, onClose, onApplied }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const empty = pending.added.length + pending.removed.length + pending.changed.length === 0;
  const apply = () => {
    setBusy(true);
    setError(null);
    takeoverApi
      .apply(pending.preview_id)
      .then((r) => {
        if (r.errors.length > 0) {
          setError(t('takeover.applyFailed', { items: r.errors.map((e) => `${e.id}: ${e.message}`).join('\n') }));
          return;
        }
        onApplied(t('takeover.applied', { added: r.added.length, removed: r.removed.length, changed: r.changed.length }));
      })
      .catch((err: unknown) => setError(describeError(err)))
      .finally(() => setBusy(false));
  };
  return (
    <Modal title={t('takeover.diffTitle')} onClose={onClose} wide testId="takeover-diff-dialog">
      <p>{t('takeover.diffIntro', { file: launchLabel(status) })}</p>
      {pending.files.length > 0 && <p className="muted small mono">{t('takeover.files', { files: pending.files.join(', ') })}</p>}
      {empty && <p>{t('takeover.noChange')}</p>}
      <Section title={t('takeover.added', { n: pending.added.length })} items={pending.added} render={entryText} testId="takeover-added" />
      <Section title={t('takeover.removed', { n: pending.removed.length })} items={pending.removed} render={entryText} testId="takeover-removed" />
      <Section title={t('takeover.changedNodes', { n: pending.changed.length })} items={pending.changed} render={changedText} testId="takeover-changed" />
      {pending.report.lost.length > 0 && <ReportBody status={status} report={pending.report} />}
      {error && <p className="error-box" role="alert">{error}</p>}
      <div className="row end">
        <button type="button" onClick={onClose}>{t('common.cancel')}</button>
        <button type="button" className="primary" disabled={busy || empty} onClick={apply} data-testid="takeover-apply">
          {t('takeover.apply')}
        </button>
      </div>
    </Modal>
  );
}
