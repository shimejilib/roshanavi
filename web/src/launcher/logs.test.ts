import { describe, expect, it } from 'vitest';
import type { LogLine } from '../api/types';
import { filterLines, lineLevel, mergeLines } from './logs';

const line = (seq: number, text: string, stream: LogLine['stream'] = 'stdout'): LogLine => ({ seq, ts: seq, stream, text });

describe('log viewer', () => {
  it('appends only newer lines and caps the length', () => {
    const a = mergeLines([], [line(1, 'a'), line(2, 'b')]);
    const b = mergeLines(a, [line(2, 'b'), line(3, 'c')]);
    expect(b.map((l) => l.seq)).toEqual([1, 2, 3]);
    expect(mergeLines(b, [line(4, 'd')], 2).map((l) => l.seq)).toEqual([3, 4]);
    expect(mergeLines(b, [line(1, 'a')])).toBe(b);
  });

  it('classifies ROS log levels and stderr', () => {
    expect(lineLevel(line(1, '[ERROR] [1.0] [talker]: boom'))).toBe('error');
    expect(lineLevel(line(1, 'src/a.cpp:1:2: error: x'))).toBe('error');
    expect(lineLevel(line(1, '[WARN] [1.0] [talker]: hmm'))).toBe('warn');
    expect(lineLevel(line(1, '[INFO] ok', 'stderr'))).toBe('warn');
    expect(lineLevel(line(1, '[INFO] ok'))).toBe('info');
    expect(lineLevel(line(1, '$ ros2 run', 'system'))).toBe('system');
  });

  it('filters by text and problems', () => {
    const lines = [line(1, 'Publishing: hello'), line(2, 'oops', 'stderr'), line(3, '[ERROR] bad')];
    expect(filterLines(lines, { query: 'publish', problemsOnly: false }).map((l) => l.seq)).toEqual([1]);
    expect(filterLines(lines, { query: '', problemsOnly: true }).map((l) => l.seq)).toEqual([2, 3]);
  });
});
