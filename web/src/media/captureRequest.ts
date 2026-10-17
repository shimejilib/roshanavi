// Browser capture form -> /ws/capture start message (pure, unit-tested).

import type { CaptureStartMessage, SupportedType } from '../api/mediaTypes';
import { t } from '../i18n';
import type { Result } from './buildMediaRequest';

export type CaptureKind = 'audio' | 'camera';

export interface CaptureForm {
  kind: CaptureKind;
  topic: string;
  /** '' = use the detected type */
  type: string;
  sampleRate: number;
  chunkSamples: number;
  fps: number;
  width: number;
  height: number;
  encoding: 'rgb8' | 'bgr8' | 'mono8';
  frameId: string;
  companionInfo: boolean;
}

export const DEFAULT_CAPTURE: CaptureForm = {
  kind: 'audio',
  topic: '',
  type: '',
  sampleRate: 16000,
  chunkSamples: 1024,
  fps: 15,
  width: 640,
  height: 480,
  encoding: 'rgb8',
  frameId: '',
  companionInfo: true,
};

export const RESOLUTIONS: readonly [number, number][] = [[320, 240], [640, 480], [1280, 720]];

/** Supported types for the capture kind (camera -> image types, mic -> audio types). */
export function typesFor(kind: CaptureKind, supported: readonly SupportedType[]): string[] {
  const want = kind === 'audio' ? 'audio' : 'image';
  return supported.filter((s) => s.kind === want).map((s) => s.type);
}

export function buildCaptureStart(form: CaptureForm, detected: string | null): Result<CaptureStartMessage> {
  const topic = form.topic.trim();
  if (!topic.startsWith('/')) return { ok: false, error: t('capture.needTopic') };
  const type = form.type || detected || '';
  if (!type) return { ok: false, error: t('capture.needType') };
  const base: CaptureStartMessage = { kind: form.kind, topic, type };
  if (form.frameId.trim()) base.frame_id = form.frameId.trim();
  if (form.kind === 'audio') {
    return { ok: true, value: { ...base, sample_rate: form.sampleRate, channels: 1, chunk_samples: form.chunkSamples, audio_info: form.companionInfo } };
  }
  return { ok: true, value: { ...base, fps: form.fps, encoding: form.encoding, camera_info: form.companionInfo } };
}
