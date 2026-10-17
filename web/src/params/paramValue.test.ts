import { describe, expect, it } from 'vitest';
import type { ParamInfo } from '../api/nodeTypes';
import { editState, paramText, parseParamInput } from './paramValue';

const param = (patch: Partial<ParamInfo> = {}): ParamInfo => ({
  name: 'rate', type: 'double', value: 1, description: '', read_only: false, dynamic_typing: false,
  declared_type: 'double', additional_constraints: '', range: null, ...patch,
});

describe('parameter values', () => {
  it('parses scalars by type', () => {
    expect(parseParamInput('true', 'bool')).toEqual({ ok: true, value: true });
    expect(parseParamInput('yes', 'bool').ok).toBe(false);
    expect(parseParamInput('-42', 'integer')).toEqual({ ok: true, value: -42 });
    expect(parseParamInput('1.5', 'integer').ok).toBe(false);
    expect(parseParamInput('2.5e1', 'double')).toEqual({ ok: true, value: 25 });
    expect(parseParamInput('', 'double').ok).toBe(false);
    expect(parseParamInput(' keep spaces ', 'string')).toEqual({ ok: true, value: ' keep spaces ' });
  });

  it('parses arrays from commas or JSON', () => {
    expect(parseParamInput('1, 2,3', 'integer_array')).toEqual({ ok: true, value: [1, 2, 3] });
    expect(parseParamInput('[0.5, 1]', 'double_array')).toEqual({ ok: true, value: [0.5, 1] });
    expect(parseParamInput('["a,b", "c"]', 'string_array')).toEqual({ ok: true, value: ['a,b', 'c'] });
    expect(parseParamInput('', 'bool_array')).toEqual({ ok: true, value: [] });
    expect(parseParamInput('1, x', 'integer_array').ok).toBe(false);
    expect(parseParamInput('300', 'byte_array').ok).toBe(false);
    expect(parseParamInput('[1,', 'integer_array').ok).toBe(false);
  });

  it('formats values for the text field', () => {
    expect(paramText([1, 2], 'integer_array')).toBe('1, 2');
    expect(paramText(['a'], 'string_array')).toBe('["a"]');
    expect(paramText(false, 'bool')).toBe('false');
    expect(paramText(null, 'not_set')).toBe('');
  });

  it('locks external nodes until confirmed and never edits read-only', () => {
    expect(editState(param(), false, false)).toBe('editable');
    expect(editState(param(), true, false)).toBe('locked');
    expect(editState(param(), true, true)).toBe('editable');
    expect(editState(param({ read_only: true }), false, true)).toBe('readOnly');
    expect(editState(param({ type: 'not_set' }), false, true)).toBe('unknownType');
  });
});
