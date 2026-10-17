// Inject tab: send the browser microphone / camera to a topic (docs/design/input-and-media.md).

import { useEffect, useRef, useState } from 'react';
import { t } from '../i18n';
import { buildCaptureStart, DEFAULT_CAPTURE, RESOLUTIONS, typesFor, type CaptureForm, type CaptureKind } from './captureRequest';
import { listDevices, mediaAvailable } from './devices';
import { useCapture } from './useCapture';
import { useMediaTypes } from './useMediaTypes';

function useDevices(kind: CaptureKind, refresh: number): MediaDeviceInfo[] {
  const [devices, setDevices] = useState<MediaDeviceInfo[]>([]);
  useEffect(() => {
    let cancelled = false;
    listDevices(kind === 'audio' ? 'audioinput' : 'videoinput')
      .then((list) => !cancelled && setDevices(list))
      .catch(() => !cancelled && setDevices([]));
    return () => {
      cancelled = true;
    };
  }, [kind, refresh]);
  return devices;
}

function Meter({ level }: { level: number }) {
  return (
    <div className="meter" role="meter" aria-label={t('capture.level')} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(level)} data-testid="capture-level">
      <div className="meter-fill" style={{ width: `${level}%` }} />
    </div>
  );
}

export function CapturePanel({ topics }: { topics: string[] }) {
  const [form, setForm] = useState<CaptureForm>(DEFAULT_CAPTURE);
  const [deviceId, setDeviceId] = useState('');
  const [error, setError] = useState<string | null>(null);
  const video = useRef<HTMLVideoElement | null>(null);
  const { status, start, stop } = useCapture(video);
  const devices = useDevices(form.kind, status.running ? 1 : 0);
  const types = useMediaTypes(form.topic, true);
  const detected = types.info?.detected && types.info.detected_supported ? types.info.detected : null;
  const choices = typesFor(form.kind, types.info?.supported ?? []);
  const update = (patch: Partial<CaptureForm>) => setForm((f) => ({ ...f, ...patch }));

  if (!mediaAvailable()) return <section className="capture"><p className="muted small">{t('capture.unsupported')}</p></section>;

  const onStart = () => {
    const built = buildCaptureStart(form, detected && choices.includes(detected) ? detected : null);
    if (!built.ok) {
      setError(built.error);
      return;
    }
    setError(null);
    void start(built.value, deviceId, { width: form.width, height: form.height });
  };

  return (
    <section className="capture" aria-labelledby="capture-title" data-testid="capture-panel">
      <h3 id="capture-title">{t('capture.title')}</h3>
      <div className="seg" role="radiogroup">
        {(['audio', 'camera'] as const).map((kind) => (
          <label key={kind} className="radio">
            <input type="radio" name="capture-kind" checked={form.kind === kind} disabled={status.running} onChange={() => { update({ kind, type: '' }); setDeviceId(''); }} />
            {kind === 'audio' ? t('capture.mic') : t('capture.camera')}
          </label>
        ))}
      </div>
      <label>
        {t('capture.device')}
        <select value={deviceId} disabled={status.running} onChange={(e) => setDeviceId(e.target.value)} data-testid="capture-device">
          <option value="">{t('capture.deviceDefault')}</option>
          {devices.map((d, i) => <option key={d.deviceId || i} value={d.deviceId}>{d.label || `${d.kind} ${i + 1}`}</option>)}
        </select>
      </label>
      <label>
        {t('capture.topic')}
        <input list="capture-topics" value={form.topic} disabled={status.running} placeholder={form.kind === 'audio' ? '/audio/audio' : '/camera/image_raw'} onChange={(e) => update({ topic: e.target.value })} data-testid="capture-topic" />
        <datalist id="capture-topics">{topics.map((name) => <option key={name} value={name} />)}</datalist>
      </label>
      <label>
        {t('capture.type')}
        <select value={form.type} disabled={status.running} onChange={(e) => update({ type: e.target.value })} data-testid="capture-type">
          <option value="">{detected ? t('capture.typeAuto', { type: detected }) : '—'}</option>
          {choices.map((type) => <option key={type} value={type}>{type}</option>)}
        </select>
      </label>
      {form.kind === 'camera' ? (
        <div className="row">
          <label>
            {t('capture.resolution')}
            <select value={`${form.width}x${form.height}`} disabled={status.running} onChange={(e) => { const [w, h] = e.target.value.split('x').map(Number); update({ width: w ?? 640, height: h ?? 480 }); }}>
              {RESOLUTIONS.map(([w, h]) => <option key={w} value={`${w}x${h}`}>{w}×{h}</option>)}
            </select>
          </label>
          <label>
            {t('capture.fps')}
            <input type="number" min="1" max="30" value={form.fps} disabled={status.running} onChange={(e) => update({ fps: Math.max(1, Math.min(30, Number(e.target.value) || 15)) })} />
          </label>
        </div>
      ) : (
        <label>
          {t('media.sampleRate')}
          <select value={form.sampleRate} disabled={status.running} onChange={(e) => update({ sampleRate: Number(e.target.value) })}>
            {[8000, 16000, 44100, 48000].map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </label>
      )}
      {form.kind === 'camera' && <video ref={video} className="capture-preview" muted playsInline hidden={!status.running} data-testid="capture-preview" />}
      {form.kind === 'audio' && status.running && <Meter level={status.level} />}
      {status.running ? (
        <button type="button" className="danger" onClick={stop} data-testid="capture-stop">{t('capture.stop')}</button>
      ) : (
        <button type="button" className="primary" onClick={onStart} data-testid="capture-start">{t('capture.start')}</button>
      )}
      {status.ready && <p className="ok-text small" data-testid="capture-status">{t('capture.running', { sent: status.sent, dropped: status.dropped })} · {status.ready.type}</p>}
      {(error ?? status.error) && <p className="error-box small" role="alert">{error ?? status.error}</p>}
      <p className="muted small">{t('capture.latency')}</p>
    </section>
  );
}
