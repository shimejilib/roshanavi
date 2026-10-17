import { describe, expect, it } from 'vitest';
import type { PreviewError } from '../api/transformTypes';
import { errorPlace, fieldErrors, previewErrorText } from './previewText';

const err = (patch: Partial<PreviewError>): PreviewError => ({ path: 'data', code: 'syntax', message: 'syntax error: x', params: {}, ...patch });

describe('preview error text', () => {
  it('explains codes in plain Japanese with params', () => {
    expect(previewErrorText(err({ code: 'no_field', params: { field: 'x', fields: 'data' } }))).toBe('フィールド「x」はありません。あるのは: data');
    expect(previewErrorText(err({ code: 'unknown_function', params: { name: 'getattr' } }))).toContain('getattr');
    expect(previewErrorText(err({ code: 'syntax', params: { detail: "'(' was never closed" } }))).toContain('かっこ');
  });

  it('falls back to the server message for unknown codes', () => {
    expect(previewErrorText(err({ code: 'brand_new', message: 'boom' }))).toBe('式を計算できません: boom');
  });

  it('places errors at the condition, a field or the whole node', () => {
    expect(errorPlace(err({ path: '(condition)' }))).toBe('condition');
    expect(errorPlace(err({ path: 'linear.x' }))).toBe('field');
    expect(errorPlace(err({ path: 'inputs', code: 'bad_sample' }))).toBe('general');
    expect(errorPlace(err({ path: 'output', code: 'spec_invalid' }))).toBe('general');
    expect(fieldErrors([err({ path: 'a' }), err({ path: '(condition)' })]).map((e) => e.path)).toEqual(['a']);
  });
});
