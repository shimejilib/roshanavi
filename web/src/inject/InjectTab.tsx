import { useEffect, useMemo, useState } from 'react';
import { api, describeError } from '../api/client';
import type { DataFile } from '../api/types';
import { t } from '../i18n';
import { templatePath } from '../lib/topics';
import { useAppState } from '../state/AppState';
import { useLive } from '../state/LiveProvider';
import { buildInjectRequest, DEFAULT_FORM, parsePayload, templateToYaml, type InjectForm } from './buildRequest';
import { JobsList } from './JobsList';
import { ModeFields, ModeSelector, QosFields } from './ModeFields';
import { CapturePanel } from '../media/CapturePanel';
import { MediaFields, TypeDetection } from '../media/MediaFields';
import { useMediaTypes } from '../media/useMediaTypes';
import { DataKindField } from '../datakind/DataKindField';
import type { PortKind } from '../datakind/kinds';

type Notice = { kind: 'ok' | 'error'; text: string } | null;

function useRemoteList<T>(load: () => Promise<T[]>, enabled: boolean, reloadKey = ''): { items: T[]; error: string | null } {
  const [items, setItems] = useState<T[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;
    load()
      .then((list) => !cancelled && setItems(list))
      .catch((err: unknown) => !cancelled && setError(describeError(err)));
    return () => {
      cancelled = true;
    };
    // `load` is a stable module-level function; `reloadKey` refetches (e.g. on mode change).
  }, [enabled, reloadKey]);
  return { items, error };
}

export function InjectTab() {
  const { live } = useLive();
  const { injectTopic, openDialog } = useAppState();
  const [form, setForm] = useState<InjectForm>(DEFAULT_FORM);
  const [kind, setKind] = useState<PortKind | ''>('');
  const [notice, setNotice] = useState<Notice>(null);
  const [busy, setBusy] = useState(false);
  // Until the user edits the YAML, changing the type replaces it with the new template.
  const [yamlTouched, setYamlTouched] = useState(false);
  const needsFiles = form.mode === 'stream' || form.mode === 'bag' || form.mode === 'media';
  const files = useRemoteList<DataFile>(() => api.files().then((r) => r.files), needsFiles, form.mode);
  const mediaTypes = useMediaTypes(form.topic, form.mode === 'media');

  const topicTypes = useMemo(
    () => new Map((live.graph?.topics ?? []).map((tp) => [tp.name, tp.types])),
    [live.graph],
  );
  const update = (patch: Partial<InjectForm>) => setForm((prev) => ({ ...prev, ...patch }));

  // The type of an existing topic is detected by DataKindField; a new topic gets a kind.
  const setTopic = (topic: string) => update({ topic });

  useEffect(() => {
    if (injectTopic) setTopic(injectTopic);
    // Prefill only when the shortcut sets a new topic.
  }, [injectTopic]);

  const loadTemplate = async (type: string) => {
    const path = templatePath(type);
    if (!path) return;
    try {
      const body = await api.template(path);
      update({ yaml: templateToYaml(body.template) });
      setYamlTouched(false);
      setNotice(null);
    } catch (err) {
      setNotice({ kind: 'error', text: describeError(err) });
    }
  };

  useEffect(() => {
    if (!yamlTouched && templatePath(form.type)) void loadTemplate(form.type);
  }, [form.type]);

  const yamlCheck = parsePayload(form.yaml);

  const start = async () => {
    const built = buildInjectRequest(form);
    if (!built.ok) {
      setNotice({ kind: 'error', text: built.error });
      return;
    }
    setBusy(true);
    try {
      const job = await api.startInject(built.value);
      setNotice({ kind: 'ok', text: t('inject.started', { id: job.id }) });
    } catch (err) {
      setNotice({ kind: 'error', text: describeError(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="inject-tab">
      <div className="inject-intro">
        <p className="muted small">{t('inject.tryIntro')}</p>
        <button type="button" className="primary" onClick={() => openDialog({ kind: 'createInput', topic: form.topic || undefined, type: form.type || undefined })} data-testid="inject-create-input">
          {t('input.create')}
        </button>
        <button type="button" onClick={() => openDialog({ kind: 'createTransform', topic: form.topic || undefined, type: form.type || undefined })} data-testid="inject-create-transform">
          {t('transform.create')}
        </button>
      </div>
      <form
        className="inject-form"
        onSubmit={(e) => {
          e.preventDefault();
          void start();
        }}
      >
        {form.mode !== 'bag' && (
          <>
            <label>
              {t('inject.topic')}
              <input list="inject-topics" value={form.topic} placeholder={t('inject.topicPlaceholder')} onChange={(e) => setTopic(e.target.value)} data-testid="inject-topic" />
              <datalist id="inject-topics">
                {[...topicTypes.keys()].map((name) => (
                  <option key={name} value={name} />
                ))}
              </datalist>
            </label>
            <div className="inject-type-row">
              <DataKindField testId="inject-type" label={t('kind.label')} topicTypes={topicTypes.get(form.topic) ?? []}
                value={{ kind, type: form.type }} onChange={(port) => { setKind(port.kind); update({ type: port.type }); }} />
              <button type="button" onClick={() => void loadTemplate(form.type)} disabled={!templatePath(form.type)}>
                {t('inject.loadTemplate')}
              </button>
              {form.mode === 'media' && <span className="muted small">{t('inject.typeAutoHint')}</span>}
            </div>
          </>
        )}
        <ModeSelector form={form} onChange={update} />
        {(form.mode === 'once' || form.mode === 'periodic') && (
          <label>
            {t('inject.payload')}
            <textarea className="yaml" rows={10} spellCheck={false} value={form.yaml} onChange={(e) => { update({ yaml: e.target.value }); setYamlTouched(true); }} data-testid="inject-yaml" />
            <span className={yamlCheck.ok ? 'ok-text small' : 'error-text small'}>{yamlCheck.ok ? t('inject.yamlOk') : yamlCheck.error}</span>
            <span className="muted small">{t('inject.payloadHelp')}</span>
            <code className="hint small">{t('inject.exprExamples')}</code>
          </label>
        )}
        {form.mode === 'media' ? (
          <>
            <TypeDetection info={mediaTypes.info} />
            <MediaFields
              topic={form.topic}
              source={form.source}
              rateHz={form.rateHz}
              count={form.count}
              loop={form.loop}
              media={form.media}
              files={files.items}
              typeInfo={mediaTypes.info}
              onChange={update}
            />
          </>
        ) : (
          <ModeFields form={form} files={files.items} onChange={update} />
        )}
        {files.error && <p className="error-text small">{files.error}</p>}
        {form.mode !== 'bag' && <QosFields form={form} onChange={update} />}
        <button type="submit" className="primary" disabled={busy} data-testid="inject-start">
          {t('inject.start')}
        </button>
        {notice && (
          <p className={notice.kind === 'ok' ? 'ok-box' : 'error-box'} role={notice.kind === 'error' ? 'alert' : 'status'}>
            {notice.text}
          </p>
        )}
      </form>
      <div className="inject-side">
        <CapturePanel topics={[...topicTypes.keys()]} />
        <JobsList jobs={live.jobs} targets={live.targets} />
      </div>
    </div>
  );
}
