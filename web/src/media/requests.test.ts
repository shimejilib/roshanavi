import { describe, expect, it } from 'vitest';
import { buildMediaOptions, chunkMs, DEFAULT_MEDIA_FORM, siblingTopic } from './buildMediaRequest';
import { buildCaptureStart, DEFAULT_CAPTURE, typesFor } from './captureRequest';
import { addAll, inputTopics, myNodeOutputs, toggle } from '../recordings/presets';
import { chatterGraph } from '../test/fixtures';
import type { Job } from '../api/types';

describe('buildMediaOptions', () => {
  it('sends only filled numbers and converts the drop percentage', () => {
    const r = buildMediaOptions({ ...DEFAULT_MEDIA_FORM, width: '320', dropPct: '10', frameId: ' cam ', startSec: '1', endSec: '3' });
    expect(r).toEqual({
      ok: true,
      value: {
        encoding: 'rgb8', format: 'jpeg', camera_info: true, audio_info: true, frame_id: 'cam',
        width: 320, start_sec: 1, end_sec: 3, sample_rate: 16000, channels: 1, chunk_samples: 1024, drop_ratio: 0.1,
      },
    });
  });

  it('rejects bad numbers in plain language', () => {
    const bad = buildMediaOptions({ ...DEFAULT_MEDIA_FORM, width: 'abc' });
    expect(bad).toEqual({ ok: false, error: '幅 は正しい数にしてください' });
    expect(buildMediaOptions({ ...DEFAULT_MEDIA_FORM, chunkSamples: '10.5' }).ok).toBe(false);
    expect(buildMediaOptions({ ...DEFAULT_MEDIA_FORM, startSec: '5', endSec: '2' })).toEqual({ ok: false, error: '終了は開始より後にしてください' });
  });

  it('computes the chunk duration and sibling topics', () => {
    expect(chunkMs({ chunkSamples: '1024', sampleRate: '16000' })).toBe(64);
    expect(chunkMs({ chunkSamples: 'x', sampleRate: '16000' })).toBeNull();
    expect(siblingTopic('/audio/audio', 'audio_info')).toBe('/audio/audio_info');
    expect(siblingTopic('/image', 'camera_info')).toBe('/camera_info');
  });
});

describe('buildCaptureStart', () => {
  const supported = [
    { type: 'sensor_msgs/msg/Image', kind: 'image' as const },
    { type: 'std_msgs/msg/Int16MultiArray', kind: 'audio' as const },
  ];

  it('filters types by kind', () => {
    expect(typesFor('camera', supported)).toEqual(['sensor_msgs/msg/Image']);
    expect(typesFor('audio', supported)).toEqual(['std_msgs/msg/Int16MultiArray']);
  });

  it('builds mic and camera start messages', () => {
    expect(buildCaptureStart({ ...DEFAULT_CAPTURE, topic: '/mic' }, 'std_msgs/msg/Int16MultiArray')).toEqual({
      ok: true,
      value: { kind: 'audio', topic: '/mic', type: 'std_msgs/msg/Int16MultiArray', sample_rate: 16000, channels: 1, chunk_samples: 1024, audio_info: true },
    });
    const cam = buildCaptureStart({ ...DEFAULT_CAPTURE, kind: 'camera', topic: '/cam', type: 'sensor_msgs/msg/Image', fps: 10 }, null);
    expect(cam).toEqual({ ok: true, value: { kind: 'camera', topic: '/cam', type: 'sensor_msgs/msg/Image', fps: 10, encoding: 'rgb8', camera_info: true } });
  });

  it('asks for a topic and a type', () => {
    expect(buildCaptureStart({ ...DEFAULT_CAPTURE, topic: 'mic' }, 'x/msg/Y').ok).toBe(false);
    expect(buildCaptureStart({ ...DEFAULT_CAPTURE, topic: '/mic' }, null)).toEqual({ ok: false, error: '型を選んでください' });
  });
});

describe('recording presets', () => {
  const job = (over: Partial<Job>): Job => ({
    id: 'j', mode: 'media', topic: '/cam/image_raw', type: 't', rate_hz: 1, count: null, source: null,
    state: 'running', sent: 0, error: null, created_at: 0, finished_at: null, ...over,
  });

  it('collects running input topics with companions', () => {
    expect(inputTopics([
      job({ companions: ['/cam/camera_info'] }),
      job({ id: 'k', topic: '/old', state: 'done' }),
      job({ id: 'm', mode: 'capture', topic: '/mic' }),
    ])).toEqual(['/cam/camera_info', '/cam/image_raw', '/mic']);
  });

  it('collects outputs of my nodes', () => {
    const g = chatterGraph();
    expect(myNodeOutputs(g)).toEqual([]);
    g.nodes[0] = { ...g.nodes[0]!, role: 'mine' };
    expect(myNodeOutputs(g)).toEqual(['/chatter']);
    expect(myNodeOutputs(null)).toEqual([]);
  });

  it('toggles and merges selections', () => {
    expect(toggle(['/a'], '/b')).toEqual(['/a', '/b']);
    expect(toggle(['/a', '/b'], '/a')).toEqual(['/b']);
    expect(addAll(['/b'], ['/a', '/b'])).toEqual(['/a', '/b']);
  });
});
