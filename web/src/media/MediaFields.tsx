// Inject tab, mode "media": file / folder, type detection and conversion options.

import type { MediaTypeInfo } from '../api/mediaTypes';
import type { DataFile } from '../api/types';
import { t, type MessageKey } from '../i18n';
import { formatBytes } from '../lib/format';
import { chunkMs, siblingTopic, type MediaForm } from './buildMediaRequest';

export const MEDIA_FILE_KINDS = ['image', 'image_dir', 'video', 'audio'];

interface Props {
  topic: string;
  source: string;
  rateHz: string;
  count: string;
  loop: boolean;
  media: MediaForm;
  files: DataFile[];
  typeInfo: MediaTypeInfo | null;
  onChange: (patch: { source?: string; rateHz?: string; count?: string; loop?: boolean; media?: MediaForm }) => void;
}

function kindOf(files: DataFile[], source: string): string | null {
  return files.find((f) => f.path === source)?.kind ?? null;
}

export function TypeDetection({ info }: { info: MediaTypeInfo | null }) {
  if (!info?.topic) return null;
  if (info.detected && info.detected_supported) return <p className="ok-text small" data-testid="media-detected">{t('media.detected', { type: info.detected })}</p>;
  if (info.detected) return <p className="error-box small">{t('media.detectedUnsupported', { type: info.detected })}</p>;
  return <p className="muted small">{t('media.noEndpoints')}</p>;
}

function ImageOptions({ topic, media, set }: { topic: string; media: MediaForm; set: (p: Partial<MediaForm>) => void }) {
  return (
    <>
      <fieldset className="inline">
        <legend>{t('media.resize')}</legend>
        <input type="number" placeholder={t('media.width')} aria-label={t('media.width')} value={media.width} onChange={(e) => set({ width: e.target.value })} />
        <input type="number" placeholder={t('media.height')} aria-label={t('media.height')} value={media.height} onChange={(e) => set({ height: e.target.value })} />
      </fieldset>
      <label>
        {t('media.encoding')}
        <select value={media.encoding} onChange={(e) => set({ encoding: e.target.value as MediaForm['encoding'] })}>
          <option value="rgb8">rgb8</option>
          <option value="bgr8">bgr8 (OpenCV)</option>
          <option value="mono8">mono8</option>
        </select>
      </label>
      <label>
        {t('media.format')}
        <select value={media.format} onChange={(e) => set({ format: e.target.value as MediaForm['format'] })}>
          <option value="jpeg">JPEG</option>
          <option value="png">PNG</option>
        </select>
      </label>
      <label>
        {t('media.frameId')}
        <input value={media.frameId} placeholder="camera" onChange={(e) => set({ frameId: e.target.value })} />
      </label>
      <label className="check">
        <input type="checkbox" checked={media.cameraInfo} onChange={(e) => set({ cameraInfo: e.target.checked })} />
        {t('media.cameraInfo', { topic: siblingTopic(topic, 'camera_info') })}
      </label>
      {media.cameraInfo && (
        <label>
          {t('media.calibration')}
          <input value={media.calibration} placeholder="calib/camera.yaml" onChange={(e) => set({ calibration: e.target.value })} />
        </label>
      )}
    </>
  );
}

function AudioOptions({ topic, media, set }: { topic: string; media: MediaForm; set: (p: Partial<MediaForm>) => void }) {
  const ms = chunkMs(media);
  return (
    <>
      <label>
        {t('media.sampleRate')}
        <select value={media.sampleRate} onChange={(e) => set({ sampleRate: e.target.value })}>
          {['8000', '16000', '22050', '44100', '48000'].map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
      </label>
      <label>
        {t('media.channels')}
        <input type="number" min="1" max="8" value={media.channels} onChange={(e) => set({ channels: e.target.value })} />
      </label>
      <label>
        {t('media.chunk')}
        <input type="number" min="32" step="32" value={media.chunkSamples} onChange={(e) => set({ chunkSamples: e.target.value })} />
        {ms != null && <span className="muted small">{t('media.chunkHint', { ms })}</span>}
      </label>
      <fieldset className="inline">
        <legend>{t('media.jitter')} / {t('media.drop')}</legend>
        <input type="number" min="0" placeholder="0" aria-label={t('media.jitter')} value={media.jitterMs} onChange={(e) => set({ jitterMs: e.target.value })} />
        <input type="number" min="0" max="90" placeholder="0" aria-label={t('media.drop')} value={media.dropPct} onChange={(e) => set({ dropPct: e.target.value })} />
      </fieldset>
      <label className="check">
        <input type="checkbox" checked={media.audioInfo} onChange={(e) => set({ audioInfo: e.target.checked })} />
        {t('media.audioInfo', { topic: siblingTopic(topic, 'audio_info') })}
      </label>
    </>
  );
}

function SectionFields({ media, set }: { media: MediaForm; set: (p: Partial<MediaForm>) => void }) {
  return (
    <fieldset className="inline">
      <legend>{t('media.section')}</legend>
      <input type="number" min="0" step="any" placeholder={t('media.start')} aria-label={t('media.start')} value={media.startSec} onChange={(e) => set({ startSec: e.target.value })} />
      <input type="number" min="0" step="any" placeholder={t('media.end')} aria-label={t('media.end')} value={media.endSec} onChange={(e) => set({ endSec: e.target.value })} />
    </fieldset>
  );
}

export function MediaFields(props: Props) {
  const { media, onChange, files } = props;
  const set = (patch: Partial<MediaForm>) => onChange({ media: { ...media, ...patch } });
  const usable = files.filter((f) => MEDIA_FILE_KINDS.includes(f.kind));
  const kind = kindOf(files, props.source);
  const isImage = kind === 'image' || kind === 'image_dir';
  return (
    <div className="mode-fields media-fields" data-testid="media-fields">
      {usable.length === 0 ? (
        <p className="muted">{t('media.fileNone')}</p>
      ) : (
        <label>
          {t('media.file')}
          <select value={props.source} onChange={(e) => onChange({ source: e.target.value })} data-testid="media-source">
            <option value="">—</option>
            {usable.map((f) => (
              <option key={f.path} value={f.path}>
                {f.path} ({t(`media.kind.${f.kind}` as MessageKey)}, {formatBytes(f.size)})
              </option>
            ))}
          </select>
        </label>
      )}
      {(isImage || kind === 'video') && (
        <label>
          {isImage ? t('media.rateImage') : t('media.rateVideo')}
          <input type="number" min="0.01" step="any" value={props.rateHz} onChange={(e) => onChange({ rateHz: e.target.value })} data-testid="media-rate" />
        </label>
      )}
      {kind && (
        <label className="check">
          <input type="checkbox" checked={props.loop} onChange={(e) => onChange({ loop: e.target.checked })} />
          {t('inject.loop')}
        </label>
      )}
      {(kind === 'video' || kind === 'audio') && <SectionFields media={media} set={set} />}
      {(isImage || kind === 'video') && <ImageOptions topic={props.topic} media={media} set={set} />}
      {kind === 'audio' && <AudioOptions topic={props.topic} media={media} set={set} />}
    </div>
  );
}
