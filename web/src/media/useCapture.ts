// Runs one browser capture: media source -> CaptureSocket, with status and level.

import { useEffect, useRef, useState } from 'react';
import type { CaptureStartMessage } from '../api/mediaTypes';
import { ApiError, describeError } from '../api/client';
import { t } from '../i18n';
import { CaptureSocket } from './captureSocket';
import { startCamera, startMic, type MediaHandle } from './devices';
import { dbfs, meterPercent, rms, smoothLevel } from './level';
import { floatToInt16, PcmChunker, samplesFor } from './pcm';

const SEND_CHUNK_MS = 20;
const LEVEL_UPDATE_MS = 100;

export interface CaptureStatus {
  running: boolean;
  ready: { type: string; companions: string[] } | null;
  sent: number;
  dropped: number;
  error: string | null;
  level: number;
}

const IDLE: CaptureStatus = { running: false, ready: null, sent: 0, dropped: 0, error: null, level: 0 };

function serverError(code: string, message: string): string {
  return describeError(new ApiError(code, message, 400));
}

export function useCapture(video: React.RefObject<HTMLVideoElement | null>) {
  const [status, setStatus] = useState<CaptureStatus>(IDLE);
  const handle = useRef<MediaHandle | null>(null);
  const socket = useRef<CaptureSocket | null>(null);

  const stop = () => {
    handle.current?.stop();
    handle.current = null;
    socket.current?.close();
    socket.current = null;
    setStatus((s) => ({ ...s, running: false, level: 0 }));
  };

  useEffect(() => stop, []);

  const openSocket = (start: CaptureStartMessage) =>
    new CaptureSocket(start, (event) => {
      if ('closed' in event) {
        handle.current?.stop();
        handle.current = null;
        setStatus((s) => ({ ...s, running: false, level: 0 }));
      } else if ('error' in event) {
        setStatus((s) => ({ ...s, error: serverError(event.error.code, event.error.message) }));
      } else if (event.event === 'ready') {
        setStatus((s) => ({ ...s, ready: { type: event.type, companions: event.companions } }));
      } else if (event.event === 'stats') {
        setStatus((s) => ({ ...s, sent: event.sent, dropped: event.dropped }));
      }
    });

  const startAudio = async (sock: CaptureSocket, start: CaptureStartMessage, deviceId: string) => {
    const rate = start.sample_rate ?? 16000;
    const chunker = new PcmChunker(samplesFor(SEND_CHUNK_MS, rate));
    let level = 0;
    let lastLevel = 0;
    handle.current = await startMic(deviceId, rate, (block) => {
      for (const chunk of chunker.push(floatToInt16(block))) sock.send(chunk);
      level = smoothLevel(level, meterPercent(dbfs(rms(block))));
      const now = performance.now();
      if (now - lastLevel > LEVEL_UPDATE_MS) {
        lastLevel = now;
        const shown = level;
        setStatus((s) => ({ ...s, level: shown }));
      }
    });
  };

  const start = async (startMsg: CaptureStartMessage, deviceId: string, size: { width: number; height: number }) => {
    stop();
    setStatus({ ...IDLE, running: true });
    const sock = openSocket(startMsg);
    socket.current = sock;
    try {
      if (startMsg.kind === 'audio') await startAudio(sock, startMsg, deviceId);
      else if (video.current) {
        handle.current = await startCamera(video.current, { deviceId, ...size, fps: startMsg.fps ?? 15 }, (jpeg) => sock.send(jpeg));
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      sock.close();
      socket.current = null;
      setStatus({ ...IDLE, error: t('capture.denied', { message }) });
    }
  };

  return { status, start, stop };
}
