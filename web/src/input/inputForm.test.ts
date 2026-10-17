import { describe, expect, it } from 'vitest';
import type { DummySpec } from '../api/types';
import { buildInputNode, defaultInputForm, filesFor, formFromDummy, idFromName, normalizeTopic, type InputForm } from './inputForm';

const form = (patch: Partial<InputForm> = {}): InputForm => ({ ...defaultInputForm('/greeting', 'std_msgs/msg/String'), ...patch });

describe('create input node request', () => {
  it('turns text into a periodic String dummy on a new topic', () => {
    const built = buildInputNode(form({ text: 'hi', rateHz: '2' }), []);
    expect(built).toEqual({
      ok: true,
      value: expect.objectContaining({ id: 'dummy_greeting', name: 'dummy_greeting', topic: '/greeting', type: 'std_msgs/msg/String', mode: 'periodic', payload: { data: 'hi' }, rate_hz: 2, autostart: true }),
    });
  });

  it('adds the leading slash and keeps expressions as-is', () => {
    const built = buildInputNode(form({ topic: 'counter', content: 'expression', text: 'n=${i}' }), []);
    expect(built.ok && built.value.topic).toBe('/counter');
    expect(built.ok && built.value.payload).toEqual({ data: 'n=${i}' });
  });

  it('uses YAML for non-String types', () => {
    const built = buildInputNode(form({ type: 'std_msgs/msg/Int32', yaml: 'data: 7' }), []);
    expect(built.ok && built.value.payload).toEqual({ data: 7 });
    expect(buildInputNode(form({ type: 'std_msgs/msg/Int32', yaml: 'data: [' }), []).ok).toBe(false);
  });

  it('builds media and data-file modes', () => {
    const media = buildInputNode(form({ type: 'sensor_msgs/msg/Image', content: 'media', source: 'clip.mp4', rateHz: '' }), []);
    expect(media.ok && media.value.mode).toBe('media');
    expect(media.ok && media.value.rate_hz).toBeUndefined();
    const file = buildInputNode(form({ content: 'file', source: 'rows.jsonl', rateHz: '5' }), []);
    expect(file.ok && file.value).toEqual(expect.objectContaining({ mode: 'stream', source: 'rows.jsonl', rate_hz: 5, loop: true }));
    expect(buildInputNode(form({ content: 'file', source: '' }), []).ok).toBe(false);
  });

  it('rejects bad topic, type, name and rate with plain messages', () => {
    for (const patch of [{ topic: '/bad topic' }, { type: 'String' }, { name: '1abc' }, { rateHz: '0' }]) {
      const built = buildInputNode(form(patch), []);
      expect(built.ok).toBe(false);
      if (!built.ok) expect(built.error.length).toBeGreaterThan(3);
    }
  });

  it('keeps the id when editing and avoids taken ids when creating', () => {
    const created = buildInputNode(form(), ['dummy_greeting']);
    expect(created.ok && created.value.id).toBe('dummy_greeting-2');
    const edited = buildInputNode(form(), ['dummy_greeting'], 'keep-me');
    expect(edited.ok && edited.value.id).toBe('keep-me');
  });
});

describe('helpers', () => {
  it('derives ids like the server', () => {
    expect(idFromName('My Node', [])).toBe('my_node');
    expect(idFromName('_x', [])).toBe('x');
    expect(idFromName('???', [])).toBe('input');
    expect(idFromName('a', ['a', 'a-2'])).toBe('a-3');
  });

  it('normalizes topics', () => {
    expect(normalizeTopic(' chatter ')).toBe('/chatter');
    expect(normalizeTopic('/a/b')).toBe('/a/b');
    expect(normalizeTopic('')).toBe('');
  });

  it('filters files by content kind', () => {
    const files = [
      { path: 'a.png', size: 1, kind: 'image' },
      { path: 'b.jsonl', size: 1, kind: 'jsonl' },
      { path: 'c.bag', size: 1, kind: 'bag' },
    ];
    expect(filesFor('media', files).map((f) => f.path)).toEqual(['a.png']);
    expect(filesFor('file', files).map((f) => f.path)).toEqual(['b.jsonl']);
    expect(filesFor('text', files)).toEqual([]);
  });

  it('prefills the dialog from an existing dummy', () => {
    const spec: DummySpec = { id: 'd', name: 'dummy_x', topic: '/x', type: 'std_msgs/msg/String', mode: 'periodic', payload: { data: 'v ${i}' }, rate_hz: 3, autostart: false };
    const prefilled = formFromDummy(spec, () => '');
    expect(prefilled).toEqual(expect.objectContaining({ content: 'expression', text: 'v ${i}', rateHz: '3', autostart: false }));
    const round = buildInputNode(prefilled, [], 'd');
    expect(round.ok && round.value).toEqual(expect.objectContaining({ id: 'd', payload: { data: 'v ${i}' }, rate_hz: 3 }));
  });
});
