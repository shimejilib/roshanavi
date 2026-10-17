import { describe, expect, it } from 'vitest';
import { hasTruncation, preferFull } from './sampleTruncation';

describe('hasTruncation', () => {
  it('finds a truncated array at any depth', () => {
    expect(hasTruncation({ data: { _truncated: true, length: 100, head: [1, 2] } })).toBe(true);
    expect(hasTruncation({ a: [{ b: { c: { _truncated: true, length: 40, head: [] } } }] })).toBe(true);
  });
  it('finds a truncated string', () => {
    expect(hasTruncation({ name: 'x'.repeat(10) + '...(+5000 chars)' })).toBe(true);
    expect(hasTruncation({ list: ['ok', 'abc...(+12 chars)'] })).toBe(true);
  });
  it('is false for whole messages', () => {
    expect(hasTruncation({ data: [1, 2, 3], name: 'hello...', nested: { _truncated: false } })).toBe(false);
    expect(hasTruncation(null)).toBe(false);
    expect(hasTruncation(5)).toBe(false);
  });
});

describe('preferFull', () => {
  it('uses the whole message where there is one and keeps the rest', () => {
    const display = { '/a': { data: { _truncated: true, length: 3, head: [1] } }, '/b': { n: 1 } };
    const merged = preferFull(display, { '/a': { data: [1, 2, 3] } });
    expect(merged['/a']).toEqual({ data: [1, 2, 3] });
    expect(merged['/b']).toEqual({ n: 1 });
  });
});
