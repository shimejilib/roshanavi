import { describe, expect, it } from 'vitest';
import type { DummySpec } from '../api/types';
import { buildInputNode, contentKindsFor, defaultInputForm, filesFor, formFromDummy, idFromName, normalizeTopic, textForKind, type InputForm } from './inputForm';

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

  it('uses YAML for 専用の型 (kind message)', () => {
    const built = buildInputNode(form({ kind: 'message', type: 'std_msgs/msg/Int32', yaml: 'data: 7' }), []);
    expect(built.ok && built.value.payload).toEqual({ data: 7 });
    expect(built.ok && built.value.kind).toBe('message');
    expect(buildInputNode(form({ kind: 'message', type: 'std_msgs/msg/Int32', yaml: 'data: [' }), []).ok).toBe(false);
  });

  it('builds the payload from the data kind without YAML', () => {
    const payload = (patch: Partial<InputForm>) => {
      const built = buildInputNode(form(patch), []);
      return built.ok ? built.value.payload : built.error;
    };
    expect(payload({ kind: 'float', type: 'std_msgs/msg/Float64', text: '2.5' })).toEqual({ data: 2.5 });
    expect(payload({ kind: 'int', type: 'std_msgs/msg/Int64', text: '3' })).toEqual({ data: 3 });
    expect(payload({ kind: 'int', type: 'std_msgs/msg/Int64', text: '3.5' })).toContain('整数');
    expect(payload({ kind: 'bool', type: 'std_msgs/msg/Bool', text: 'false' })).toEqual({ data: false });
    expect(payload({ kind: 'numbers', type: 'std_msgs/msg/Float64MultiArray', text: '1, 2.5,3' })).toEqual({ data: [1, 2.5, 3] });
    expect(payload({ kind: 'bytes', type: 'std_msgs/msg/UInt8MultiArray', text: '0, 255' })).toEqual({ data: [0, 255] });
    expect(payload({ kind: 'bytes', type: 'std_msgs/msg/UInt8MultiArray', text: '256' })).toContain('バイト列');
    expect(payload({ kind: 'json', text: '{"a": 1}' })).toEqual({ data: '{"a": 1}' });
    expect(payload({ kind: 'json', text: '{oops' })).toContain('JSON');
    expect(payload({ kind: 'float', type: 'std_msgs/msg/Float64', content: 'expression', text: 'sin(t)' })).toEqual({ data: '${sin(t)}' });
    expect(payload({ kind: 'float', type: 'std_msgs/msg/Float64', content: 'expression', text: '${t}' })).toEqual({ data: '${t}' });
  });

  it('offers only the contents a kind can use and swaps starting values', () => {
    expect(contentKindsFor('image')).toEqual(['media']);
    expect(contentKindsFor('numbers')).toEqual(['text', 'file']);
    expect(contentKindsFor('message')).toContain('media');
    expect(buildInputNode(form({ kind: 'image', content: 'text' }), []).ok).toBe(false);
    expect(textForKind('float', 'hello', 'text')).toBe('1.5');
    expect(textForKind('float', 'my own', 'text')).toBe('my own');
    expect(textForKind('string', '1.5', 'expression')).toBe('hello ${i}');
  });

  it('builds media and data-file modes', () => {
    const media = buildInputNode(form({ kind: 'image', type: 'sensor_msgs/msg/Image', content: 'media', source: 'clip.mp4', rateHz: '' }), []);
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
