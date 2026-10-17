// 「launch ファイルから取り込む」: pick a launch file, analyse it (no process is started),
// preview the per-node targets, then import them into the launch list (autosaved).

import { useMemo, useState } from 'react';
import { api, describeError } from '../api/client';
import type { ImportPlan } from '../api/nodeListTypes';
import { t } from '../i18n';
import { useWorkspace } from '../launcher/useWorkspace';
import { Modal } from '../lib/Modal';
import { useAppState } from '../state/AppState';
import {
  changedArgs, commitRequest, defaultSelection, EMPTY_SOURCE, importBlocker, initialArgValues, launchPackages,
  sourceFromForm, type ImportMode, type SourceForm,
} from './importModel';
import { ImportPreview } from './ImportPreview';
import { ImportSourceForm } from './ImportSourceForm';

export function ImportLaunchDialog() {
  const { closeDialog } = useAppState();
  const { info } = useWorkspace();
  const packages = useMemo(() => launchPackages(info?.packages ?? []), [info]);
  const [form, setForm] = useState<SourceForm>(EMPTY_SOURCE);
  const [values, setValues] = useState<Record<string, string>>({});
  const [plan, setPlan] = useState<ImportPlan | null>(null);
  const [mode, setMode] = useState<ImportMode>('nodes');
  const [role, setRole] = useState<'mine' | 'dependency'>('dependency');
  const [selection, setSelection] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  const changeSource = (next: SourceForm) => {
    setForm(next);
    setPlan(null);
    setValues({});
    setDone(null);
  };

  const analyse = () => {
    const source = sourceFromForm(form);
    if (!source) return;
    setBusy(true);
    setError(null);
    setDone(null);
    api
      .importPreview(source, plan ? changedArgs(plan.arguments, values) : values)
      .then((next) => {
        setPlan(next);
        setValues(initialArgValues(next.arguments, values));
        setSelection(defaultSelection(next));
        setMode('nodes');
      })
      .catch((err: unknown) => setError(describeError(err)))
      .finally(() => setBusy(false));
  };

  const commit = () => {
    if (!plan) return;
    setBusy(true);
    setError(null);
    api
      .importCommit(commitRequest(plan, mode, selection, role))
      .then((result) => {
        const failed = result.errors.map((e) => `${e.code}: ${e.message}`);
        setDone([t('import.done', { n: result.created.length, ids: result.created.map((c) => c.id).join(', ') }), ...failed].join('\n'));
        setPlan(null);
      })
      .catch((err: unknown) => setError(describeError(err)))
      .finally(() => setBusy(false));
  };

  const blocker = plan ? importBlocker(plan, mode, selection) : null;
  const toggle = (index: number) =>
    setSelection((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });

  return (
    <Modal title={t('import.title')} onClose={closeDialog} wide testId="import-dialog">
      <p className="muted small">{t('import.intro')}</p>
      <ImportSourceForm form={form} onForm={changeSource} packages={packages} args={plan?.arguments ?? []} values={values}
        missing={plan?.missing_args ?? []} onValue={(name, value) => setValues((prev) => ({ ...prev, [name]: value }))} />
      <div className="row end">
        <button type="button" onClick={analyse} disabled={busy || !sourceFromForm(form)} data-testid="import-analyse">
          {busy && !plan ? t('import.analysing') : plan ? t('import.reanalyse') : t('import.analyse')}
        </button>
      </div>
      {error && <p className="error-box" role="alert" data-testid="import-error">{error}</p>}
      {done && <p className="ok-box" role="status" data-testid="import-done">{done}</p>}
      {plan && (
        <>
          <ImportPreview plan={plan} mode={mode} onMode={setMode} selection={selection} onToggle={toggle} role={role} onRole={setRole} />
          {blocker && <p className="muted small" data-testid="import-blocker">{blocker}</p>}
        </>
      )}
      <div className="row end">
        <button type="button" onClick={closeDialog}>{t('common.close')}</button>
        {plan && (
          <button type="button" className="primary" disabled={busy || blocker !== null} onClick={commit} data-testid="import-commit">
            {t('import.commit')}
          </button>
        )}
      </div>
    </Modal>
  );
}
