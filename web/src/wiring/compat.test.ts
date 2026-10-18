import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { verdictText, wireCompat, type WireEnd } from './compat';
import { CATALOG } from './testFixtures';

// The same cases the backend test (test/test_wiring.py) runs against data_kinds.wire_compat.
const CASES_URL = new URL('../../../ros2_ws/src/roshanavi/test/data/wire_compat_cases.json', import.meta.url);
const cases = (JSON.parse(readFileSync(CASES_URL, 'utf-8')) as {
  cases: { sender: WireEnd; receiver: WireEnd; expect: [string, string] }[];
}).cases;

describe('wire compatibility (shared with the backend)', () => {
  it.each(cases)('$sender.kind/$sender.type -> $receiver.kind/$receiver.type', ({ sender, receiver, expect: want }) => {
    expect(wireCompat(sender, receiver, CATALOG.type_kinds)).toEqual(want);
  });

  it('covers every outcome the UI explains', () => {
    const codes = new Set(cases.map((c) => c.expect[1]));
    for (const code of ['', 'int_to_float', 'string_to_json', 'json_to_string', 'float_to_int', 'kind_mismatch', 'type_mismatch']) expect(codes).toContain(code);
  });
});

describe('plain reasons', () => {
  const tk = CATALOG.type_kinds;
  it('refuses an image channel into a text input with a plain sentence', () => {
    const sender = { kind: null, type: 'sensor_msgs/msg/Image' };
    const receiver = { kind: 'string' as const, type: null };
    expect(verdictText(wireCompat(sender, receiver, tk), sender, receiver, tk, true)).toBe('文字列の入力口に、画像のチャンネル (トピック) はつなげません');
  });

  it('words an output that cannot be sent to a channel from the port side', () => {
    const sender = { kind: 'string' as const, type: null };
    const receiver = { kind: null, type: 'std_msgs/msg/Float64' };
    expect(verdictText(wireCompat(sender, receiver, tk), sender, receiver, tk, false)).toBe('文字列の出力口は、数値 (小数)のチャンネル (トピック) にはつなげません');
  });

  it('notes a conversion and says nothing for an exact match', () => {
    const sender = { kind: null, type: 'std_msgs/msg/Int32' };
    const receiver = { kind: 'float' as const, type: null };
    expect(verdictText(wireCompat(sender, receiver, tk), sender, receiver, tk, true)).toBe('整数を小数として渡します。');
    expect(verdictText(['same', ''], sender, receiver, tk, true)).toBe('');
  });
});
