// Media inject form -> `media` options of POST /api/inject (pure, unit-tested).

import type { MediaOptions } from '../api/mediaTypes';
import { t, type MessageKey } from '../i18n';

export type Result<T> = { ok: true; value: T } | { ok: false; error: string };

export interface MediaForm {
  encoding: 'rgb8' | 'bgr8' | 'mono8';
  format: 'jpeg' | 'png';
  frameId: string;
  width: string;
  height: string;
  cameraInfo: boolean;
  calibration: string;
  startSec: string;
  endSec: string;
  sampleRate: string;
  channels: string;
  chunkSamples: string;
  jitterMs: string;
  dropPct: string;
  audioInfo: boolean;
}

export const DEFAULT_MEDIA_FORM: MediaForm = {
  encoding: 'rgb8',
  format: 'jpeg',
  frameId: '',
  width: '',
  height: '',
  cameraInfo: true,
  calibration: '',
  startSec: '',
  endSec: '',
  sampleRate: '16000',
  channels: '1',
  chunkSamples: '1024',
  jitterMs: '',
  dropPct: '',
  audioInfo: true,
};

type NumberCheck = { min: number; max: number; integer?: boolean };

/** '' -> undefined, valid number -> number, otherwise an error naming the field. */
function optionalNumber(text: string, field: MessageKey, check: NumberCheck): Result<number | undefined> {
  if (!text.trim()) return { ok: true, value: undefined };
  const n = Number(text);
  const valid = Number.isFinite(n) && n >= check.min && n <= check.max && (!check.integer || Number.isInteger(n));
  return valid ? { ok: true, value: n } : { ok: false, error: t('media.badNumber', { field: t(field) }) };
}

const CHECKS: Record<string, [keyof MediaForm, keyof MediaOptions, MessageKey, NumberCheck]> = {
  width: ['width', 'width', 'media.width', { min: 16, max: 7680, integer: true }],
  height: ['height', 'height', 'media.height', { min: 16, max: 4320, integer: true }],
  start: ['startSec', 'start_sec', 'media.start', { min: 0, max: 86400 }],
  end: ['endSec', 'end_sec', 'media.end', { min: 0.001, max: 86400 }],
  rate: ['sampleRate', 'sample_rate', 'media.sampleRate', { min: 8000, max: 192000, integer: true }],
  channels: ['channels', 'channels', 'media.channels', { min: 1, max: 8, integer: true }],
  chunk: ['chunkSamples', 'chunk_samples', 'media.chunk', { min: 32, max: 65536, integer: true }],
  jitter: ['jitterMs', 'jitter_ms', 'media.jitter', { min: 0, max: 1000 }],
  drop: ['dropPct', 'drop_ratio', 'media.drop', { min: 0, max: 90 }],
};

export function buildMediaOptions(form: MediaForm): Result<MediaOptions> {
  const out: MediaOptions = {
    encoding: form.encoding,
    format: form.format,
    camera_info: form.cameraInfo,
    audio_info: form.audioInfo,
  };
  if (form.frameId.trim()) out.frame_id = form.frameId.trim();
  if (form.calibration.trim()) out.calibration = form.calibration.trim();
  const numbers: Record<string, number> = {};
  for (const [formKey, optKey, label, check] of Object.values(CHECKS)) {
    const parsed = optionalNumber(String(form[formKey]), label, check);
    if (!parsed.ok) return parsed;
    if (parsed.value !== undefined) numbers[optKey] = optKey === 'drop_ratio' ? parsed.value / 100 : parsed.value;
  }
  Object.assign(out, numbers);
  if (out.end_sec !== undefined && out.end_sec <= (out.start_sec ?? 0)) return { ok: false, error: t('media.badSection') };
  return { ok: true, value: out };
}

/** Milliseconds per published audio chunk (for the hint next to the field). */
export function chunkMs(form: Pick<MediaForm, 'chunkSamples' | 'sampleRate'>): number | null {
  const samples = Number(form.chunkSamples);
  const rate = Number(form.sampleRate);
  if (!(samples > 0) || !(rate > 0)) return null;
  return Math.round((samples / rate) * 10000) / 10;
}

/** Sibling topic used by default for CameraInfo / AudioInfo (same rule as the backend). */
export function siblingTopic(topic: string, name: string): string {
  const trimmed = topic.trim();
  if (!trimmed.startsWith('/')) return name;
  const parent = trimmed.slice(0, trimmed.lastIndexOf('/'));
  return `${parent}/${name}`;
}
