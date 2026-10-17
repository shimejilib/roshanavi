// Class mode of "＋ 関数・クラスノードを作る": run a plain Python class of a workspace package as a
// node (docs/design/nodes.md). The class, its __init__ arguments and methods come from the server's
// static parse; the user sets the parameters' start values, binds methods to topics and marks the
// action methods (buttons). Editing shows the live status, the action buttons and the code export.

import { useMemo, useState } from 'react';
import { api, describeError } from '../api/client';
import type { ClassSpec } from '../api/classTypes';
import type { Target } from '../api/types';
import { t } from '../i18n';
import { Term } from '../lib/Term';
import { useAppState } from '../state/AppState';
import { useLive } from '../state/LiveProvider';
import { applyClass, buildClassSpec, defaultClassForm, formFromClass, renameNode, type ClassForm } from './classForm';
import { ClassNodeFields } from './ClassNodeFields';
import { ClassStatusPanel } from './ClassStatusPanel';
import { useFunctionModules, useModuleInfo } from './useFunctionModules';

function ExportClassCode({ id }: { id: string }) {
  const [directory, setDirectory] = useState('generated');
  const [lifecycle, setLifecycle] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const run = async () => {
    try {
      const result = await api.exportClassCode(id, directory, lifecycle);
      setMessage({ ok: true, text: t('function.exported', result) });
    } catch (err) {
      setMessage({ ok: false, text: describeError(err) });
    }
  };
  return (
    <fieldset className="function-export">
      <legend>{t('function.exportCode')}</legend>
      <p className="muted small">{t('class.exportHelp')}</p>
      <div className="row wrap">
        <label>
          {t('function.exportDir')}
          <input value={directory} onChange={(e) => setDirectory(e.target.value)} data-testid="class-export-dir" />
        </label>
        <label className="check">
          <input type="checkbox" checked={lifecycle} onChange={(e) => setLifecycle(e.target.checked)} data-testid="class-export-lifecycle" />
          {t('class.exportLifecycle')} <Term term="lifecycle" />
        </label>
        <button type="button" onClick={() => void run()} data-testid="class-export">{t('function.exportCode')}</button>
      </div>
      <p className="muted small">{t('class.exportLifecycleHelp')}</p>
      {message && <p className={message.ok ? 'ok-box small' : 'error-box small'} role="status" data-testid="class-export-result">{message.text}</p>}
    </fieldset>
  );
}

export function ClassMode({ editing }: { editing?: Target }) {
  const { closeDialog, select } = useAppState();
  const { live } = useLive();
  const spec = editing?.spec as ClassSpec | undefined;
  const modules = useFunctionModules();
  const [form, setForm] = useState<ClassForm>(() => (spec ? formFromClass(spec, undefined) : defaultClassForm()));
  const [nameTouched, setNameTouched] = useState(Boolean(editing));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const moduleInfo = useModuleInfo(form.module);
  const classInfo = moduleInfo.info?.classes?.find((c) => c.name === form.className);
  const topicTypes = useMemo(() => new Map((live.graph?.topics ?? []).map((tp) => [tp.name, tp.types])), [live.graph]);
  const update = (patch: Partial<ClassForm>) => setForm((prev) => ({ ...prev, ...patch }));

  // Editing: the listing arrives after the dialog opens; fill the rows from the saved spec once.
  const [hydrated, setHydrated] = useState(!spec);
  if (spec && !hydrated && classInfo) {
    setForm(formFromClass(spec, classInfo));
    setHydrated(true);
  }

  const pickClass = (name: string) => {
    const info = moduleInfo.info?.classes?.find((c) => c.name === name);
    setForm((prev) => (info ? applyClass(prev, info, nameTouched) : { ...prev, className: name }));
  };

  const submit = async () => {
    const built = buildClassSpec(form, classInfo, live.targets.map((tg) => tg.id), editing?.id);
    if (!built.ok) {
      setError(built.error);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (editing) {
        await api.updateClass(built.value);
        await api.targetAction(built.value.id, 'restart');
      } else {
        await api.addClass(built.value, true);
      }
      const out = built.value.methods.flatMap((m) => m.outputs)[0]?.topic;
      if (out) select({ kind: 'topic', id: out });
      closeDialog();
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="input-form function-form class-form" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
      <p className="muted small">{t('class.intro')}</p>
      {editing && <ClassStatusPanel target={editing} />}
      <div className="row wrap">
        <label>
          {t('function.module')}
          <select value={form.module} onChange={(e) => update({ module: e.target.value, className: '', methods: [], params: {} })} disabled={Boolean(editing)} data-testid="class-module">
            <option value="">{t('function.moduleChoose')}</option>
            {modules.modules.map((m) => <option key={m.module} value={m.module}>{m.module}</option>)}
          </select>
          {modules.modules.length === 0 && !modules.error && <span className="muted small">{t('function.noModules')}</span>}
          {modules.error && <span className="error-text small">{modules.error}</span>}
        </label>
        <label>
          {t('class.class')}
          <select value={form.className} onChange={(e) => pickClass(e.target.value)} disabled={!moduleInfo.info || Boolean(editing)} data-testid="class-name">
            <option value="">{t('class.classChoose')}</option>
            {(moduleInfo.info?.classes ?? []).map((c) => <option key={c.name} value={c.name}>{c.signature}</option>)}
          </select>
          {moduleInfo.info && (moduleInfo.info.classes ?? []).length === 0 && <span className="muted small">{t('class.noClasses')}</span>}
          {moduleInfo.error && <span className="error-text small" role="alert">{moduleInfo.error}</span>}
        </label>
      </div>
      {classInfo && moduleInfo.info && (
        <p className="function-signature small" data-testid="class-signature">
          <code className="mono">{classInfo.signature}</code>
          <span className="muted"> — {moduleInfo.info.file}:{classInfo.line}</span>
        </p>
      )}
      <label>
        <span>{t('function.name')} <Term term="node" /></span>
        <input value={form.name} onChange={(e) => { setForm((prev) => renameNode(prev, e.target.value)); setNameTouched(true); }} disabled={Boolean(editing)} data-testid="class-node-name" />
      </label>
      {classInfo && <ClassNodeFields form={form} info={classInfo} topicTypes={topicTypes} onChange={setForm} />}
      <label className="check">
        <input type="checkbox" checked={form.autostart} onChange={(e) => update({ autostart: e.target.checked })} />
        {t('function.autostart')}
      </label>
      {editing && <ExportClassCode id={editing.id} />}
      {error && <p className="error-box" role="alert" data-testid="class-error-box">{error}</p>}
      <div className="row end">
        <button type="button" onClick={closeDialog}>{t('common.cancel')}</button>
        <button type="submit" className="primary" disabled={busy} data-testid="class-submit">
          {editing ? t('function.saveRestart') : t('function.submit')}
        </button>
      </div>
    </form>
  );
}
