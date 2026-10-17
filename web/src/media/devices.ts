// Browser microphone (AudioWorklet) and camera (canvas -> JPEG) sources.

import { downmix } from './pcm';

/** Copies each 128-frame render quantum (mono) to the main thread. */
const WORKLET_SOURCE = `
class RoshanaviPcm extends AudioWorkletProcessor {
  process(inputs) {
    const channels = inputs[0];
    if (channels && channels.length > 0 && channels[0].length > 0) {
      const out = new Float32Array(channels[0].length);
      for (const ch of channels) for (let i = 0; i < out.length; i++) out[i] += ch[i] / channels.length;
      this.port.postMessage(out, [out.buffer]);
    }
    return true;
  }
}
registerProcessor('roshanavi-pcm', RoshanaviPcm);
`;

export interface MediaHandle {
  stop: () => void;
}

export function mediaAvailable(): boolean {
  return typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia;
}

export async function listDevices(kind: 'audioinput' | 'videoinput'): Promise<MediaDeviceInfo[]> {
  if (!mediaAvailable()) return [];
  const all = await navigator.mediaDevices.enumerateDevices();
  return all.filter((d) => d.kind === kind);
}

function deviceConstraint(deviceId: string): { deviceId?: { exact: string } } {
  return deviceId ? { deviceId: { exact: deviceId } } : {};
}

/** Mic -> Float32 mono blocks at `sampleRate` (the AudioContext resamples). */
export async function startMic(deviceId: string, sampleRate: number, onBlock: (block: Float32Array) => void): Promise<MediaHandle> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { ...deviceConstraint(deviceId), channelCount: 1, echoCancellation: false, noiseSuppression: false, autoGainControl: false },
  });
  const ctx = new AudioContext({ sampleRate });
  const url = URL.createObjectURL(new Blob([WORKLET_SOURCE], { type: 'application/javascript' }));
  try {
    await ctx.audioWorklet.addModule(url);
  } finally {
    URL.revokeObjectURL(url);
  }
  const node = new AudioWorkletNode(ctx, 'roshanavi-pcm');
  node.port.onmessage = (e: MessageEvent<Float32Array>) => onBlock(downmix([e.data]));
  const silent = ctx.createGain();
  silent.gain.value = 0; // keep the graph pulled without playing the mic back
  ctx.createMediaStreamSource(stream).connect(node);
  node.connect(silent).connect(ctx.destination);
  return {
    stop: () => {
      node.port.onmessage = null;
      stream.getTracks().forEach((track) => track.stop());
      void ctx.close();
    },
  };
}

export interface CameraOptions {
  deviceId: string;
  width: number;
  height: number;
  fps: number;
  quality?: number;
}

/** Camera -> preview <video> + JPEG frames every 1/fps s (drawn on a canvas). */
export async function startCamera(video: HTMLVideoElement, opts: CameraOptions, onFrame: (jpeg: ArrayBuffer) => void): Promise<MediaHandle> {
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { ...deviceConstraint(opts.deviceId), width: { ideal: opts.width }, height: { ideal: opts.height }, frameRate: { ideal: opts.fps } },
  });
  video.srcObject = stream;
  await video.play();
  const canvas = document.createElement('canvas');
  canvas.width = opts.width;
  canvas.height = opts.height;
  const ctx = canvas.getContext('2d');
  let busy = false;
  const timer = setInterval(() => {
    if (busy || !ctx || video.readyState < 2) return;
    busy = true;
    ctx.drawImage(video, 0, 0, opts.width, opts.height);
    canvas.toBlob(
      (blob) => {
        busy = false;
        if (blob) void blob.arrayBuffer().then(onFrame);
      },
      'image/jpeg',
      opts.quality ?? 0.8,
    );
  }, 1000 / opts.fps);
  return {
    stop: () => {
      clearInterval(timer);
      stream.getTracks().forEach((track) => track.stop());
      video.srcObject = null;
    },
  };
}
