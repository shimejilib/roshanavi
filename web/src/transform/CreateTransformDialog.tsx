// "＋ 変換ノードを作る" / topic menu "このトピックを受けて変換するノードを作る": create or edit
// a transform node, with a live preview computed by the server (same evaluator as the node).

import { useEffect, useMemo, useState } from 'react';
import { api, describeError } from '../api/client';
import type { TransformSpec } from '../api/transformTypes';
import { t } from '../i18n';
import { templateToYaml } from '../inject/buildRequest';
import { normalizeTopic } from '../input/inputForm';
import { Modal } from '../lib/Modal';
import { Term } from '../lib/Term';
import { templatePath } from '../lib/topics';
import { useAppState } from '../state/AppState';
import { useLive } from '../state/LiveProvider';
import { TransformInputsFields } from './TransformInputsFields';
import { TransformPreview } from './TransformPreview';
import { TransformTimingFields } from './TransformTimingFields';
import { buildTransformSpec, defaultTransformForm, formFromTransform, isHeavy, mappingFromTemplate, type TransformForm } from './transformForm';
import { useLatestMessages } from './useLatestMessages';
import { useTransformPreview } from './useTransformPreview';

interface Props {
  topic?: string;
  type?: string;
  transformId?: string;
}

async function loadTemplate(type: string): Promise<Record<string, unknown> | null> {
  const path = templatePath(type);
  if (!path) return null;
  return (await api.template(path)).template;
}

export function CreateTransformDialog({ topic, type, transformId }: Props) {
  const { closeDialog, select } = useAppState();
  const { live } = useLive();
  const editing = live.targets.find((tg) => tg.id === transformId && tg.kind === 'transform');
  const [form, setForm] = useState<TransformForm>(() =>
    editing ? formFromTransform(editing.spec as TransformSpec, templateToYaml) : defaultTransformForm(topic, type),
  );
  const [mappingTouched, setMappingTouched] = useState(Boolean(editing));
  const [types, setTypes] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const topicTypes = useMemo(() => new Map((live.graph?.topics ?? []).map((tp) => [tp.name, tp.types])), [live.graph]);
  const update = (patch: Partial<TransformForm>) => setForm((prev) => ({ ...prev, ...patch }));
  const firstInput = form.inputs[0];
  const heavy = form.inputs.some((row) => isHeavy(row.type));

  useEffect(() => {
    api.types().then(setTypes).catch(() => setTypes([])); // only suggestions; typing still works
  }, []);

  // A fresh starting mapping whenever the types change (until the user edits the YAML).
  useEffect(() => {
    if (mappingTouched || form.mode !== 'map' || !form.outputType.trim() || !firstInput) return undefined;
    let cancelled = false;
    Promise.all([loadTemplate(form.outputType), loadTemplate(firstInput.type).catch(() => null)])
      .then(([out, input]) => {
        if (cancelled || !out) return;
        setError(null);
        update({ mappingYaml: templateToYaml(mappingFromTemplate(out, input, firstInput.alias || 'msg')) });
      })
      .catch((err: unknown) => !cancelled && setError(describeError(err)));
    return () => {
      cancelled = true;
    };
  }, [form.outputType, firstInput?.type, firstInput?.alias, form.mode, mappingTouched]);

  useEffect(() => {
    if (heavy && form.mode !== 'relay') update({ mode: 'relay' });
  }, [heavy]);

  const latest = useLatestMessages(form.inputs.map((row) => normalizeTopic(row.topic)));
  const samples = useMemo(() => Object.fromEntries(form.inputs
    .filter((row) => latest[normalizeTopic(row.topic)])
    .map((row) => [row.alias, latest[normalizeTopic(row.topic)] as Record<string, unknown>])), [latest, form.inputs]);
  const takenIds = live.targets.map((tg) => tg.id);
  const previewSpec = useMemo(() => buildTransformSpec(form, takenIds, editing?.id, true), [form, editing?.id]);
  const preview = useTransformPreview(previewSpec, samples);

  const submit = async () => {
    const built = buildTransformSpec(form, takenIds, editing?.id);
    if (!built.ok) {
      setError(built.error);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (editing) {
        await api.updateTransform(built.value);
        await api.targetAction(built.value.id, 'restart');
      } else {
        await api.addTransform(built.value, true);
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
    <Modal title={editing ? t('transform.editTitle', { name: form.name }) : t('transform.title')} onClose={closeDialog} wide testId="create-transform-dialog">
      <form className="input-form transform-form" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
        <p className="muted small">{t('transform.intro')}</p>
        <label>
          <span>{t('transform.name')} <Term term="node" /></span>
          <input value={form.name} onChange={(e) => update({ name: e.target.value })} disabled={Boolean(editing)} data-testid="transform-name" />
        </label>
        <TransformInputsFields form={form} topicTypes={topicTypes} types={types} disabled={Boolean(editing)} onChange={setForm} />
        <fieldset>
          <legend>{t('transform.mode')}</legend>
          <label className="check">
            <input type="radio" name="transform-mode" checked={form.mode === 'map'} disabled={heavy} onChange={() => update({ mode: 'map' })} />
            {t('transform.mode.map')}
          </label>
          <label className="check">
            <input type="radio" name="transform-mode" checked={form.mode === 'relay'} disabled={form.inputs.length > 1}
              onChange={() => update({ mode: 'relay' })} data-testid="transform-mode-relay" />
            {t('transform.mode.relay')}
          </label>
          {heavy && <p className="muted small">{t('transform.heavyNote', { type: form.inputs.find((row) => isHeavy(row.type))?.type ?? '' })}</p>}
        </fieldset>
        <div className="row wrap">
          <label>
            {t('transform.outputTopic')}
            <input value={form.outputTopic} onChange={(e) => update({ outputTopic: e.target.value })} data-testid="transform-output-topic" />
          </label>
          {form.mode === 'map' && (
            <label>
              {t('transform.outputType')}
              <input list="transform-types" value={form.outputType} onChange={(e) => update({ outputType: e.target.value })} data-testid="transform-output-type" />
            </label>
          )}
        </div>
        {form.mode === 'map' && (
          <>
            <label>
              {t('transform.mapping')}
              <textarea className="yaml" rows={4} spellCheck={false} value={form.mappingYaml}
                onChange={(e) => { setMappingTouched(true); update({ mappingYaml: e.target.value }); }} data-testid="transform-mapping" />
              <span className="muted small">{t('transform.mappingHelp')}</span>
              <code className="hint small">{t('transform.functions')}</code>
            </label>
            <label>
              {t('transform.condition')}
              <input value={form.condition} placeholder={t('transform.conditionPlaceholder')} onChange={(e) => update({ condition: e.target.value })} data-testid="transform-condition" />
            </label>
          </>
        )}
        <TransformPreview samples={samples} aliases={form.inputs.map((row) => row.alias)} preview={preview} />
        <TransformTimingFields form={form} onChange={update} />
        <label className="check">
          <input type="checkbox" checked={form.autostart} onChange={(e) => update({ autostart: e.target.checked })} />
          {t('transform.autostart')}
        </label>
        <p className="muted small">{t('transform.tracingNote')}</p>
        {error && <p className="error-box" role="alert">{error}</p>}
        <div className="row end">
          <button type="button" onClick={closeDialog}>{t('common.cancel')}</button>
          <button type="submit" className="primary" disabled={busy} data-testid="transform-submit">
            {editing ? t('transform.saveRestart') : t('transform.submit')}
          </button>
        </div>
      </form>
    </Modal>
  );
}
