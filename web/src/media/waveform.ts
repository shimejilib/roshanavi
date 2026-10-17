// Waveform drawing data and a sample ring buffer for the audio viewer (pure).

export interface Peak {
  min: number;
  max: number;
}

/** Min / max per bucket of int16 samples, normalized to [-1, 1]. */
export function peaks(samples: Int16Array, buckets: number): Peak[] {
  const out: Peak[] = [];
  if (buckets <= 0) return out;
  const per = samples.length / buckets;
  for (let b = 0; b < buckets; b += 1) {
    const start = Math.floor(b * per);
    const end = Math.max(start + 1, Math.floor((b + 1) * per));
    let min = 0;
    let max = 0;
    for (let i = start; i < end && i < samples.length; i += 1) {
      const v = (samples[i] ?? 0) / 32768;
      if (v < min) min = v;
      if (v > max) max = v;
    }
    out.push({ min, max });
  }
  return out;
}

/** Keeps the most recent `capacity` samples. */
export class SampleRing {
  private data: Int16Array;
  private size = 0;

  constructor(readonly capacity: number) {
    this.data = new Int16Array(capacity);
  }

  push(samples: Int16Array): void {
    if (samples.length >= this.capacity) {
      this.data.set(samples.subarray(samples.length - this.capacity));
      this.size = this.capacity;
      return;
    }
    const keep = Math.min(this.size, this.capacity - samples.length);
    this.data.copyWithin(0, this.size - keep, this.size);
    this.data.set(samples, keep);
    this.size = keep + samples.length;
  }

  /** Oldest -> newest. */
  values(): Int16Array {
    return this.data.slice(0, this.size);
  }
}

/** int16 PCM bytes (little endian) -> Float32 for WebAudio. */
export function int16ToFloat(samples: Int16Array): Float32Array {
  const out = new Float32Array(samples.length);
  for (let i = 0; i < samples.length; i += 1) out[i] = (samples[i] ?? 0) / 32768;
  return out;
}
