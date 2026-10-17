// "＋ 入力ノードを作る" dialog <-> DummySpec (pure, unit-tested; DESIGN §6.5).
// One step: topic + type + content -> a named, persistent dummy node that the
// server registers, autosaves and starts (POST /api/dummies?start=true).

import type { DataFile, DummySpec } from '../api/types';
import { t } from '../i18n';
import { parsePayload, type Result } from '../inject/buildRequest';
import { suggestDummyName } from '../inject/dummyName';
import { buildMediaOptions, DEFAULT_MEDIA_FORM } from '../media/buildMediaRequest';

export type ContentKind = 'text' | 'expression' | 'media' | 'file';
export const CONTENT_KINDS: readonly ContentKind[] = ['text', 'expression', 'media', 'file'];

export interface InputForm {
  topic: string;
  type: string;
  name: string;
  content: ContentKind;
  /** Text / expression for std_msgs/msg/String. */
  text: string;
  /** Message as YAML for every other type. */
  yaml: string;
  rateHz: string;
  source: string;
  loop: boolean;
  autostart: boolean;
}

export const TEXT_TYPE = 'std_msgs/msg/String';
const TYPE_RE = /^[A-Za-z][A-Za-z0-9_]*\/msg\/[A-Za-z][A-Za-z0-9_]*$/;
const TOPIC_RE = /^(\/[A-Za-z_][A-Za-z0-9_]*)+$/;
const NODE_NAME_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;
const ID_MAX = 56;
const MEDIA_KINDS = new Set(['image', 'video', 'audio', 'image_dir']);
const DATA_KINDS = new Set(['jsonl', 'csv']);

export const DEFAULT_TEXT = 'hello';
export const DEFAULT_EXPRESSION = 'hello ${i}';

export function defaultInputForm(topic = '', type = ''): InputForm {
  return {
    topic,
    type: type || (topic ? '' : TEXT_TYPE),
    name: suggestDummyName(topic || null),
    content: 'text',
    text: DEFAULT_TEXT,
    yaml: '',
    rateHz: '1',
    source: '',
    loop: true,
    autostart: true,
  };
}

/** `chatter` -> `/chatter` (beginners often omit the slash). */
export function normalizeTopic(topic: string): string {
  const trimmed = topic.trim();
  return trimmed && !trimmed.startsWith('/') ? `/${trimmed}` : trimmed;
}

/** Same rule as the backend `_id_from_name`: lowercase, safe characters, unique. */
export function idFromName(name: string, taken: readonly string[]): string {
  let base = name.toLowerCase().replace(/[^a-z0-9_-]/g, '_').replace(/^[_-]+|[_-]+$/g, '') || 'input';
  if (!/^[a-z0-9]/.test(base)) base = `d_${base}`;
  base = base.slice(0, ID_MAX);
  const used = new Set(taken);
  let candidate = base;
  for (let n = 2; used.has(candidate); n += 1) candidate = `${base}-${n}`;
  return candidate;
}

export function isTextType(type: string): boolean {
  return type.trim() === TEXT_TYPE;
}

/** Files offered for a content kind (media files or JSONL / CSV records). */
export function filesFor(content: ContentKind, files: readonly DataFile[]): DataFile[] {
  const kinds = content === 'media' ? MEDIA_KINDS : content === 'file' ? DATA_KINDS : new Set<string>();
  return files.filter((f) => kinds.has(f.kind));
}

function positive(text: string): number | null {
  const n = Number(text);
  return text.trim() !== '' && Number.isFinite(n) && n > 0 ? n : null;
}

function payloadOf(form: InputForm): Result<Record<string, unknown>> {
  if (isTextType(form.type)) return { ok: true, value: { data: form.text } };
  return parsePayload(form.yaml);
}

function checkBasics(form: InputForm): string | null {
  if (!TOPIC_RE.test(normalizeTopic(form.topic))) return t('input.error.topic');
  if (!TYPE_RE.test(form.type.trim())) return t('input.error.type');
  if (!NODE_NAME_RE.test(form.name.trim())) return t('input.error.name');
  return null;
}

function contentFields(form: InputForm): Result<Partial<DummySpec>> {
  const rate = positive(form.rateHz);
  if (form.content === 'text' || form.content === 'expression') {
    if (rate == null) return { ok: false, error: t('inject.needRate') };
    const payload = payloadOf(form);
    return payload.ok ? { ok: true, value: { mode: 'periodic', payload: payload.value, rate_hz: rate } } : payload;
  }
  if (!form.source) return { ok: false, error: t('inject.needSource') };
  if (form.content === 'file') {
    if (rate == null) return { ok: false, error: t('inject.needRate') };
    return { ok: true, value: { mode: 'stream', source: form.source, rate_hz: rate, loop: form.loop } };
  }
  if (form.rateHz.trim() && rate == null) return { ok: false, error: t('inject.needRate') };
  const media = buildMediaOptions(DEFAULT_MEDIA_FORM);
  if (!media.ok) return media;
  const value: Partial<DummySpec> = { mode: 'media', source: form.source, loop: form.loop, media: media.value };
  return { ok: true, value: rate != null ? { ...value, rate_hz: rate } : value };
}

/** Build the DummySpec; `existingId` keeps the id when editing. */
export function buildInputNode(form: InputForm, takenIds: readonly string[], existingId?: string): Result<DummySpec> {
  const problem = checkBasics(form);
  if (problem) return { ok: false, error: problem };
  const content = contentFields(form);
  if (!content.ok) return content;
  const name = form.name.trim();
  const spec: DummySpec = {
    id: existingId ?? idFromName(name, takenIds),
    name,
    topic: normalizeTopic(form.topic),
    type: form.type.trim(),
    mode: 'periodic',
    qos: { reliability: 'reliable', durability: 'volatile', depth: 10 },
    autostart: form.autostart,
    ...content.value,
  };
  return { ok: true, value: spec };
}

function contentOf(spec: DummySpec): ContentKind {
  if (spec.mode === 'media') return 'media';
  if (spec.mode === 'stream') return 'file';
  const data = spec.payload?.data;
  return typeof data === 'string' && data.includes('${') ? 'expression' : 'text';
}

/** Prefill the dialog from an existing input node (edit "内容・レートの変更"). */
export function formFromDummy(spec: DummySpec, yamlOf: (payload: Record<string, unknown>) => string): InputForm {
  const data = spec.payload?.data;
  return {
    topic: spec.topic,
    type: spec.type,
    name: spec.name,
    content: contentOf(spec),
    text: typeof data === 'string' ? data : DEFAULT_TEXT,
    yaml: spec.payload && !isTextType(spec.type) ? yamlOf(spec.payload) : '',
    rateHz: spec.rate_hz != null ? String(spec.rate_hz) : '',
    source: spec.source ?? '',
    loop: spec.loop ?? true,
    autostart: spec.autostart ?? false,
  };
}
