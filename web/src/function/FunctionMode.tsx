// Function mode of "＋ 関数・クラスノードを作る": run a plain Python function of a workspace package
// as a node (docs/design/nodes.md). Modules and signatures come from the server's static parse
// (user code is never imported to list them). Editing shows the node's live status and the code export.

import { useMemo, useState } from 'react';
import { api, describeError } from '../api/client';
import type { CallMode, FunctionSpec } from '../api/functionTypes';
import type { Target } from '../api/types';
import { t, type MessageKey } from '../i18n';
import { Term } from '../lib/Term';
import { useAppState } from '../state/AppState';
import { useLive } from '../state/LiveProvider';
import { applyFunction, buildFunctionSpec, defaultFunctionForm, formFromFunction, rowsFor, type FunctionForm } from './functionForm';
import { FunctionPortsFields } from './FunctionPortsFields';
import { FUNCTION_NAME_RE } from './codeLocations';
import { FunctionStatusPanel } from './FunctionStatusPanel';
import { ModuleNotes, ModuleSelect } from './ModuleSelect';
import { useFunctionModules, useModuleInfo } from './useFunctionModules';

interface Props {
  topic?: string;
  /** The function node being edited (undefined: create). */
  editing?: Target;
  /** Choose this module (and function) when the dialog opens (after 「ひな形を作る」). */
  preselect?: { module: string; fn?: string };
  /** Changes when the code locations changed: the module list is read again. */
  refreshKey?: number;
}

const CALLS: CallMode[] = ['on_message', 'periodic', 'multi_input'];

function ExportCode({ id }: { id: string }) {
  const [directory, setDirectory] = useState('generated');
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const run = async () => {
    try {
      const result = await api.exportFunctionCode(id, directory);
      setMessage({ ok: true, text: t('function.exported', result) });
    } catch (err) {
      setMessage({ ok: false, text: describeError(err) });
    }
  };
  return (
    <fieldset className="function-export">
      <legend>{t('function.exportCode')}</legend>
      <p className="muted small">{t('function.exportHelp')}</p>
      <div className="row">
        <label>
          {t('function.exportDir')}
          <input value={directory} onChange={(e) => setDirectory(e.target.value)} data-testid="function-export-dir" />
        </label>
        <button type="button" onClick={() => void run()} data-testid="function-export">{t('function.exportCode')}</button>
      </div>
      {message && <p className={message.ok ? 'ok-box small' : 'error-box small'} role="status" data-testid="function-export-result">{message.text}</p>}
    </fieldset>
  );
}

export function FunctionMode({ topic, editing, preselect, refreshKey = 0 }: Props) {
  const { closeDialog, select } = useAppState();
  const { live } = useLive();
  const [form, setForm] = useState<FunctionForm>(() => {
    if (editing) return formFromFunction(editing.spec as FunctionSpec);
    const initial = defaultFunctionForm(topic);
    return preselect ? { ...initial, module: preselect.module } : initial;
  });
  const [nameTouched, setNameTouched] = useState(Boolean(editing));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pendingFn, setPendingFn] = useState(editing ? '' : (preselect?.fn ?? ''));
  const modules = useFunctionModules(refreshKey);
  const moduleInfo = useModuleInfo(form.module, refreshKey);
  const listable = moduleInfo.info?.listable !== false;
  const manualError = !listable && form.fn && !FUNCTION_NAME_RE.test(form.fn) ? t('code.manualInvalid') : null;
  const fnInfo = moduleInfo.info?.functions.find((f) => f.name === form.fn);
  const topicTypes = useMemo(() => new Map((live.graph?.topics ?? []).map((tp) => [tp.name, tp.types])), [live.graph]);
  const update = (patch: Partial<FunctionForm>) => setForm((prev) => ({ ...prev, ...patch }));

  const pickFunction = (name: string) => {
    const info = moduleInfo.info?.functions.find((f) => f.name === name);
    setForm((prev) => (info ? applyFunction(prev, info, nameTouched) : { ...prev, fn: name }));
  };
  // After 「ひな形を作る」: the module's listing arrives after the dialog switched; pick the function once.
  if (pendingFn && moduleInfo.info?.module === form.module) {
    setPendingFn('');
    if (moduleInfo.info.functions.some((f) => f.name === pendingFn)) pickFunction(pendingFn);
  }
  const setCall = (call: CallMode) => setForm((prev) => ({ ...prev, call, inputs: rowsFor(call, prev.inputs, fnInfo?.params.length) }));

  const submit = async () => {
    if (manualError) {
      setError(manualError);
      return;
    }
    const built = buildFunctionSpec(form, live.targets.map((tg) => tg.id), editing?.id);
    if (!built.ok) {
      setError(built.error);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (editing) {
        await api.updateFunction(built.value);
        await api.targetAction(built.value.id, 'restart');
      } else {
        await api.addFunction(built.value, true);
      }
      select({ kind: 'topic', id: built.value.output.topic });
      closeDialog();
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
      <form className="input-form function-form" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
        <p className="muted small">{t('function.intro')}</p>
        {editing && <FunctionStatusPanel target={editing} />}
        <div className="row wrap">
          <label>
            {t('function.module')}
            <ModuleSelect value={form.module} modules={modules.modules} onChange={(module) => update({ module, fn: '' })} disabled={Boolean(editing)} testId="function-module" data-tour="function-module" />
            {modules.modules.length === 0 && !modules.error && <span className="muted small">{t('function.noModules')}</span>}
            {modules.error && <span className="error-text small">{modules.error}</span>}
          </label>
          {listable ? (
            <label>
              {t('function.function')}
              <select value={form.fn} onChange={(e) => pickFunction(e.target.value)} disabled={!moduleInfo.info} data-testid="function-name" data-tour="function-name">
                <option value="">{t('function.functionChoose')}</option>
                {(moduleInfo.info?.functions ?? []).map((f) => <option key={f.name} value={f.name}>{f.signature}</option>)}
              </select>
              {moduleInfo.info && moduleInfo.info.functions.length === 0 && <span className="muted small">{t('function.noFunctions')}</span>}
              {moduleInfo.error && <span className="error-text small" role="alert">{moduleInfo.error}</span>}
            </label>
          ) : (
            <label>
              {t('code.manualFunction')}
              <input value={form.fn} onChange={(e) => update({ fn: e.target.value.trim() })} disabled={Boolean(editing)} data-testid="function-name-manual" />
              <span className="muted small">{t('code.notListable')}</span>
              {manualError && <span className="error-text small" role="alert">{manualError}</span>}
            </label>
          )}
        </div>
        {fnInfo && (
          <p className="function-signature small" data-testid="function-signature">
            <code className="mono">{fnInfo.signature}</code>
            {moduleInfo.info && <span className="muted"> — {moduleInfo.info.file}:{fnInfo.line}</span>}
            {fnInfo.doc && <span className="muted"> — {fnInfo.doc}</span>}
          </p>
        )}
        <ModuleNotes info={moduleInfo.info} />
        <label>
          <span>{t('function.name')} <Term term="node" /></span>
          <input value={form.name} onChange={(e) => { update({ name: e.target.value }); setNameTouched(true); }} disabled={Boolean(editing)} data-testid="function-node-name" />
        </label>
        <fieldset>
          <legend>{t('function.call')}</legend>
          <div className="row wrap">
            {CALLS.map((call) => (
              <label key={call} className="check">
                <input type="radio" name="function-call" checked={form.call === call} onChange={() => setCall(call)} data-testid={`function-call-${call}`} />
                {t(`function.call.${call}` as MessageKey)}
              </label>
            ))}
          </div>
          <span className="muted small">{t(`function.callHelp.${form.call}` as MessageKey)}</span>
          {form.call === 'periodic' && (
            <label>
              {t('function.rate')}
              <input value={form.rateHz} inputMode="decimal" onChange={(e) => update({ rateHz: e.target.value })} data-testid="function-rate" />
            </label>
          )}
        </fieldset>
        <FunctionPortsFields form={form} info={fnInfo} topicTypes={topicTypes} onChange={setForm} />
        <label className="check">
          <input type="checkbox" checked={form.autostart} onChange={(e) => update({ autostart: e.target.checked })} />
          {t('function.autostart')}
        </label>
        {editing && <ExportCode id={editing.id} />}
        {error && <p className="error-box" role="alert">{error}</p>}
        <div className="row end">
          <button type="button" onClick={closeDialog}>{t('common.cancel')}</button>
          <button type="submit" className="primary" disabled={busy} data-testid="function-submit" data-tour="function-submit">
            {editing ? t('function.saveRestart') : t('function.submit')}
          </button>
        </div>
      </form>
  );
}
