import { useEffect, useRef, useState } from 'react';
import { ApiError, describeError } from '../api/client';
import { t } from '../i18n';
import { int16ToFloat, peaks, SampleRing } from '../media/waveform';
import { openViewer } from '../media/viewerSocket';

const WINDOW_SEC = 2;
const PLAY_LEAD_SEC = 0.05;

function draw(canvas: HTMLCanvasElement, samples: Int16Array): void {
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  const { width, height } = canvas;
  ctx.clearRect(0, 0, width, height);
  ctx.strokeStyle = getComputedStyle(canvas).color;
  ctx.beginPath();
  peaks(samples, width).forEach((p, x) => {
    ctx.moveTo(x + 0.5, height / 2 - p.max * (height / 2));
    ctx.lineTo(x + 0.5, height / 2 - p.min * (height / 2) + 1);
  });
  ctx.stroke();
}

/** Plays mono PCM chunks back to back through WebAudio. */
class Player {
  private ctx: AudioContext | null = null;
  private next = 0;

  play(samples: Int16Array, rate: number): void {
    this.ctx ??= new AudioContext();
    const buffer = this.ctx.createBuffer(1, samples.length, rate);
    buffer.copyToChannel(int16ToFloat(samples) as Float32Array<ArrayBuffer>, 0);
    const node = this.ctx.createBufferSource();
    node.buffer = buffer;
    node.connect(this.ctx.destination);
    this.next = Math.max(this.next, this.ctx.currentTime + PLAY_LEAD_SEC);
    node.start(this.next);
    this.next += buffer.duration;
  }

  close(): void {
    void this.ctx?.close();
    this.ctx = null;
    this.next = 0;
  }
}

/** Waveform + playback of an audio topic. `needsRate`: arrays carry no sample rate. */
export function AudioViewer({ topic, needsRate }: { topic: string; needsRate: boolean }) {
  const [running, setRunning] = useState(true);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(16000);
  const [received, setReceived] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const playingRef = useRef(false);
  playingRef.current = playing;

  useEffect(() => {
    if (!running) return undefined;
    setError(null);
    const ring = new SampleRing(rate * WINDOW_SEC);
    const player = new Player();
    const close = openViewer(topic, `?sample_rate=${rate}`, {
      onMeta: () => undefined,
      onData: (meta, data) => {
        const samples = new Int16Array(data);
        ring.push(samples);
        setReceived(meta.sample_rate ?? rate);
        if (canvas.current) draw(canvas.current, ring.values());
        if (playingRef.current) player.play(samples, meta.sample_rate ?? rate);
      },
      onError: (code, message) => setError(describeError(new ApiError(code, message, 400))),
    });
    return () => {
      close();
      player.close();
    };
  }, [topic, running, rate]);

  return (
    <section className="viewer" aria-labelledby="audio-viewer-title">
      <h4 id="audio-viewer-title">
        {t('viewer.audio')}{' '}
        <button type="button" onClick={() => setRunning(!running)}>{running ? t('viewer.stop') : t('viewer.start')}</button>{' '}
        {running && <button type="button" aria-pressed={playing} onClick={() => setPlaying(!playing)} data-testid="audio-play">{playing ? t('viewer.mute') : `▶ ${t('viewer.play')}`}</button>}
      </h4>
      {needsRate && (
        <label className="small">
          {t('viewer.sampleRate')}{' '}
          <select value={rate} onChange={(e) => setRate(Number(e.target.value))}>
            {[8000, 16000, 22050, 44100, 48000].map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </label>
      )}
      {error && <p className="error-box">{error}</p>}
      {running && received == null && !error && <p className="muted">{t('viewer.waiting')}</p>}
      <canvas ref={canvas} width={320} height={80} className="waveform" hidden={received == null} data-testid="audio-waveform" data-received={received ?? undefined} />
      {received != null && <div className="muted small">{t('viewer.audioInfo', { rate: received })}</div>}
    </section>
  );
}
