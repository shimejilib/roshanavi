import { describe, expect, it } from 'vitest';
import { buildInjectRequest, DEFAULT_FORM, parsePayload, templateToYaml } from './buildRequest';

const form = { ...DEFAULT_FORM, topic: '/chatter', type: 'std_msgs/msg/String', yaml: 'data: "hello ${i}"' };

describe('parsePayload', () => {
  it('accepts mappings and empty text', () => {
    expect(parsePayload('data: 1')).toEqual({ ok: true, value: { data: 1 } });
    expect(parsePayload('')).toEqual({ ok: true, value: {} });
  });

  it('rejects broken YAML and non-mappings in plain language', () => {
    const broken = parsePayload('data: [1, 2');
    expect(broken.ok).toBe(false);
    if (!broken.ok) expect(broken.error).toContain('YAML の形式が正しくありません');
    const list = parsePayload('- 1\n- 2');
    expect(list.ok).toBe(false);
    if (!list.ok) expect(list.error).toContain('マッピング');
  });

  it('round-trips a template', () => {
    const yaml = templateToYaml({ x: 0.0, header: { frame_id: '' } });
    expect(parsePayload(yaml)).toEqual({ ok: true, value: { x: 0, header: { frame_id: '' } } });
  });
});

describe('buildInjectRequest', () => {
  it('builds a once request with payload and qos', () => {
    const r = buildInjectRequest(form);
    expect(r).toEqual({
      ok: true,
      value: {
        mode: 'once',
        topic: '/chatter',
        type: 'std_msgs/msg/String',
        payload: { data: 'hello ${i}' },
        qos: { reliability: 'reliable', durability: 'volatile', depth: 10 },
      },
    });
  });

  it('validates required fields per mode', () => {
    expect(buildInjectRequest({ ...form, topic: ' ' }).ok).toBe(false);
    expect(buildInjectRequest({ ...form, type: '' }).ok).toBe(false);
    expect(buildInjectRequest({ ...form, mode: 'periodic', rateHz: '0' }).ok).toBe(false);
    expect(buildInjectRequest({ ...form, mode: 'stream', source: '' }).ok).toBe(false);
  });

  it('builds periodic, stream and bag requests', () => {
    const periodic = buildInjectRequest({ ...form, mode: 'periodic', rateHz: '5', count: '3' });
    expect(periodic.ok && periodic.value).toMatchObject({ mode: 'periodic', rate_hz: 5, count: 3 });
    const stream = buildInjectRequest({ ...form, mode: 'stream', rateHz: '10', source: 's.jsonl', loop: true });
    expect(stream.ok && stream.value).toMatchObject({ mode: 'stream', source: 's.jsonl', loop: true, rate_hz: 10 });
    expect(stream.ok && 'payload' in stream.value).toBe(false);
    const bag = buildInjectRequest({ ...DEFAULT_FORM, mode: 'bag', source: 'bags/a', bagRate: '2', bagTopics: '/a, /b' });
    expect(bag).toEqual({ ok: true, value: { mode: 'bag', source: 'bags/a', loop: false, bag_rate: 2, topics: ['/a', '/b'] } });
  });
});

describe('media mode', () => {
  it('builds a media request with an optional type and rate', () => {
    const r = buildInjectRequest({ ...DEFAULT_FORM, mode: 'media', topic: '/cam', source: 'clip.mp4', rateHz: '', media: { ...DEFAULT_FORM.media, width: '320' } });
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r.value.type).toBeUndefined();
    expect(r.value.rate_hz).toBeUndefined();
    expect(r.value.source).toBe('clip.mp4');
    expect(r.value.media?.width).toBe(320);
  });

  it('requires a file and valid media numbers', () => {
    expect(buildInjectRequest({ ...DEFAULT_FORM, mode: 'media', topic: '/cam' }).ok).toBe(false);
    const bad = buildInjectRequest({ ...DEFAULT_FORM, mode: 'media', topic: '/cam', source: 'a.wav', media: { ...DEFAULT_FORM.media, sampleRate: '5' } });
    expect(bad.ok).toBe(false);
  });
});
