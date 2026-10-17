// "＋ 入力ノードを作る" / "ここにトピックを追加": one dialog that creates (or edits)
// a persistent dummy node. A new topic name makes the topic appear with it.

import { useEffect, useMemo, useState } from 'react';
import { api, describeError } from '../api/client';
import type { DataFile, DummySpec } from '../api/types';
import { t } from '../i18n';
import { templateToYaml } from '../inject/buildRequest';
import { suggestDummyName } from '../inject/dummyName';
import { Modal } from '../lib/Modal';
import { Term } from '../lib/Term';
import { templatePath } from '../lib/topics';
import { useAppState } from '../state/AppState';
import { useLive } from '../state/LiveProvider';
import { DataKindField } from '../datakind/DataKindField';
import type { PortValue } from '../datakind/kinds';
import { InputContentFields } from './InputContentFields';
import { buildInputNode, contentKindsFor, defaultInputForm, formFromDummy, normalizeTopic, textForKind, type InputForm } from './inputForm';

interface Props {
  topic?: string;
  type?: string;
  dummyId?: string;
}

function useList<T>(load: () => Promise<T[]>): T[] {
  const [items, setItems] = useState<T[]>([]);
  useEffect(() => {
    let cancelled = false;
    load()
      .then((list) => !cancelled && setItems(list))
      .catch(() => !cancelled && setItems([])); // lists are only suggestions; the form still works
    return () => {
      cancelled = true;
    };
    // `load` is a module-level API call.
  }, []);
  return items;
}

export function CreateInputDialog({ topic, type, dummyId }: Props) {
  const { closeDialog, select } = useAppState();
  const { live } = useLive();
  const editing = live.targets.find((tg) => tg.id === dummyId && tg.kind === 'dummy');
  const [form, setForm] = useState<InputForm>(() =>
    editing ? formFromDummy(editing.spec as DummySpec, templateToYaml) : defaultInputForm(topic, type),
  );
  const [nameTouched, setNameTouched] = useState(Boolean(editing));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const files = useList<DataFile>(() => api.files().then((r) => r.files));
  const topicTypes = useMemo(() => new Map((live.graph?.topics ?? []).map((tp) => [tp.name, tp.types])), [live.graph]);
  const known = topicTypes.get(normalizeTopic(form.topic));
  const update = (patch: Partial<InputForm>) => setForm((prev) => ({ ...prev, ...patch }));

  const setTopic = (value: string) => {
    update({
      topic: value,
      ...(nameTouched ? {} : { name: suggestDummyName(normalizeTopic(value) || null) }),
    });
  };

  const setPort = (port: PortValue) => {
    if (port.kind === form.kind && port.type === form.type) return;
    const allowed = contentKindsFor(port.kind);
    const content = allowed.includes(form.content) ? form.content : (allowed[0] ?? 'text');
    update({ kind: port.kind, type: port.type, content, text: editing ? form.text : textForKind(port.kind, form.text, content) });
  };

  useEffect(() => {
    const path = templatePath(form.type);
    if (!path || (form.kind !== 'message' && form.kind !== '') || editing) return undefined;
    let cancelled = false;
    api
      .template(path)
      .then((body) => !cancelled && update({ yaml: templateToYaml(body.template) }))
      .catch((err: unknown) => !cancelled && setError(describeError(err)));
    return () => {
      cancelled = true;
    };
  }, [form.type, form.kind]);

  const submit = async () => {
    const built = buildInputNode(form, live.targets.map((tg) => tg.id), editing?.id);
    if (!built.ok) {
      setError(built.error);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (editing) {
        await api.updateDummy(built.value);
        await api.targetAction(built.value.id, 'restart');
      } else {
        await api.addDummy(built.value, true);
      }
      select({ kind: 'topic', id: built.value.topic });
      closeDialog();
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={editing ? t('input.editTitle', { name: form.name }) : t('input.title')} onClose={closeDialog} wide testId="create-input-dialog">
      <form className="input-form" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
        <p className="muted small">{t('input.intro')}</p>
        <label>
          <span>{t('input.topic')} <Term term="topic" /></span>
          <input list="input-topics" value={form.topic} placeholder="/my_topic" onChange={(e) => setTopic(e.target.value)} disabled={Boolean(editing)} data-testid="input-topic" data-tour="input-topic" />
          <datalist id="input-topics">
            {[...topicTypes.keys()].map((name) => <option key={name} value={name} />)}
          </datalist>
          {form.topic.trim() && !known && <span className="muted small">{t('input.newTopic')}</span>}
        </label>
        <DataKindField testId="input-type" label={t('kind.label')} topicTypes={known ?? []}
          value={{ kind: form.kind, type: form.type }} onChange={setPort} />
        <label>
          <span>{t('input.name')} <Term term="node" /></span>
          <input value={form.name} onChange={(e) => { update({ name: e.target.value }); setNameTouched(true); }} disabled={Boolean(editing)} data-testid="input-name" />
        </label>
        <InputContentFields form={form} files={files} onChange={update} />
        <label className="check">
          <input type="checkbox" checked={form.autostart} onChange={(e) => update({ autostart: e.target.checked })} />
          {t('input.autostart')}
        </label>
        {error && <p className="error-box" role="alert">{error}</p>}
        <div className="row end">
          <button type="button" onClick={closeDialog}>{t('common.cancel')}</button>
          <button type="submit" className="primary" disabled={busy} data-testid="input-submit" data-tour="input-submit">
            {editing ? t('input.saveRestart') : t('input.submit')}
          </button>
        </div>
      </form>
    </Modal>
  );
}
