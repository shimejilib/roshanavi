// Inject form -> POST /api/inject body, with plain-language validation (pure, unit-tested).

import { dump, load } from 'js-yaml';
import type { InjectMode, InjectRequest } from '../api/types';
import { t } from '../i18n';

export interface InjectForm {
  topic: string;
  type: string;
  yaml: string;
  mode: InjectMode;
  rateHz: string;
  count: string;
  source: string;
  loop: boolean;
  bagRate: string;
  bagTopics: string;
  reliability: 'reliable' | 'best_effort';
  durability: 'volatile' | 'transient_local';
  depth: string;
}

export const DEFAULT_FORM: InjectForm = {
  topic: '',
  type: '',
  yaml: '',
  mode: 'once',
  rateHz: '1',
  count: '',
  source: '',
  loop: false,
  bagRate: '1',
  bagTopics: '',
  reliability: 'reliable',
  durability: 'volatile',
  depth: '10',
};

export type Result<T> = { ok: true; value: T } | { ok: false; error: string };

export function parsePayload(text: string): Result<Record<string, unknown>> {
  if (!text.trim()) return { ok: true, value: {} };
  let value: unknown;
  try {
    value = load(text);
  } catch (err) {
    const message = err instanceof Error ? err.message.split('\n')[0] ?? '' : String(err);
    return { ok: false, error: t('inject.yamlError', { message }) };
  }
  if (value == null) return { ok: true, value: {} };
  if (typeof value !== 'object' || Array.isArray(value)) return { ok: false, error: t('inject.yamlNotMap') };
  return { ok: true, value: value as Record<string, unknown> };
}

export function templateToYaml(template: Record<string, unknown>): string {
  return dump(template, { noRefs: true });
}

function positive(text: string): number | null {
  const n = Number(text);
  return text.trim() !== '' && Number.isFinite(n) && n > 0 ? n : null;
}

function needsMessage(mode: InjectMode): boolean {
  return mode === 'once' || mode === 'periodic';
}

export function buildInjectRequest(form: InjectForm): Result<InjectRequest> {
  const req: InjectRequest = { mode: form.mode };
  if (form.mode !== 'bag') {
    if (!form.topic.trim()) return { ok: false, error: t('inject.needTopic') };
    if (!form.type.trim()) return { ok: false, error: t('inject.needType') };
    req.topic = form.topic.trim();
    req.type = form.type.trim();
    req.qos = { reliability: form.reliability, durability: form.durability, depth: positive(form.depth) ?? 10 };
  }
  if (needsMessage(form.mode)) {
    const payload = parsePayload(form.yaml);
    if (!payload.ok) return payload;
    req.payload = payload.value;
  }
  if (form.mode === 'periodic' || form.mode === 'stream') {
    const rate = positive(form.rateHz);
    if (rate == null) return { ok: false, error: t('inject.needRate') };
    req.rate_hz = rate;
  }
  if (form.mode === 'periodic') {
    const count = positive(form.count);
    if (count != null) req.count = Math.floor(count);
  }
  if (form.mode === 'stream' || form.mode === 'bag') {
    if (!form.source) return { ok: false, error: t('inject.needSource') };
    req.source = form.source;
    req.loop = form.loop;
  }
  if (form.mode === 'bag') {
    req.bag_rate = positive(form.bagRate) ?? 1;
    const topics = form.bagTopics.split(',').map((s) => s.trim()).filter(Boolean);
    if (topics.length) req.topics = topics;
  }
  return { ok: true, value: req };
}
