// PCM helpers for browser microphone capture (pure, unit-tested).

const INT16_MAX = 32767;
const INT16_MIN = -32768;

/** Float samples in [-1, 1] -> int16 (clipped, rounded). */
export function floatToInt16(input: Float32Array): Int16Array {
  const out = new Int16Array(input.length);
  for (let i = 0; i < input.length; i += 1) {
    const v = Math.max(-1, Math.min(1, input[i] ?? 0));
    out[i] = Math.max(INT16_MIN, Math.min(INT16_MAX, Math.round(v < 0 ? v * 32768 : v * INT16_MAX)));
  }
  return out;
}

/** Average several channels into one. */
export function downmix(channels: readonly Float32Array[]): Float32Array {
  const first = channels[0];
  if (!first) return new Float32Array(0);
  if (channels.length === 1) return first;
  const out = new Float32Array(first.length);
  for (const ch of channels) {
    for (let i = 0; i < out.length; i += 1) out[i] = (out[i] ?? 0) + (ch[i] ?? 0) / channels.length;
  }
  return out;
}

/** Collects int16 samples and emits fixed-size chunks (the remainder is kept). */
export class PcmChunker {
  private buffer: Int16Array;
  private filled = 0;

  constructor(readonly chunkSamples: number) {
    if (!Number.isInteger(chunkSamples) || chunkSamples <= 0) throw new Error('chunkSamples must be a positive integer');
    this.buffer = new Int16Array(chunkSamples);
  }

  push(samples: Int16Array): Int16Array[] {
    const out: Int16Array[] = [];
    let offset = 0;
    while (offset < samples.length) {
      const take = Math.min(this.chunkSamples - this.filled, samples.length - offset);
      this.buffer.set(samples.subarray(offset, offset + take), this.filled);
      this.filled += take;
      offset += take;
      if (this.filled === this.chunkSamples) {
        out.push(this.buffer);
        this.buffer = new Int16Array(this.chunkSamples);
        this.filled = 0;
      }
    }
    return out;
  }

  get pending(): number {
    return this.filled;
  }
}

/** Samples per chunk for a duration (e.g. 20 ms at 16 kHz -> 320). */
export function samplesFor(ms: number, sampleRate: number): number {
  return Math.max(1, Math.round((ms / 1000) * sampleRate));
}
