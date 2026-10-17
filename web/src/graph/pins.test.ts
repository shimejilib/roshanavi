import { describe, expect, it } from 'vitest';
import { loadPins, MAX_PINS, NO_PINS, parsePins, savePins, withPin } from './pins';

function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return {
    data,
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
  };
}

describe('map pins', () => {
  it('pins a vertex without mutating the previous pins, and re-pinning moves it to the end', () => {
    const first = withPin(NO_PINS, 'n:/a', { x: 1, y: 2 });
    const second = withPin(first, 'n:/b', { x: 3, y: 4 });
    const moved = withPin(second, 'n:/a', { x: 9, y: 9 });
    expect(first).toEqual({ 'n:/a': { x: 1, y: 2 } });
    expect(Object.keys(moved)).toEqual(['n:/b', 'n:/a']);
    expect(moved['n:/a']).toEqual({ x: 9, y: 9 });
  });

  it('drops the oldest pins beyond the cap', () => {
    let pins = NO_PINS;
    for (let i = 0; i < MAX_PINS + 5; i += 1) pins = withPin(pins, `n:/${i}`, { x: i, y: i });
    expect(Object.keys(pins)).toHaveLength(MAX_PINS);
    expect(pins['n:/0']).toBeUndefined();
    expect(pins[`n:/${MAX_PINS + 4}`]).toBeDefined();
  });

  it('saves and loads per project', () => {
    const storage = memoryStorage();
    savePins('/data/a.yaml', withPin(NO_PINS, 'n:/a', { x: 5, y: 6 }), storage);
    expect(loadPins('/data/a.yaml', storage)).toEqual({ 'n:/a': { x: 5, y: 6 } });
    expect(loadPins('/data/b.yaml', storage)).toEqual({});
  });

  it('removes the stored entry when everything is unpinned', () => {
    const storage = memoryStorage();
    savePins('p', withPin(NO_PINS, 'n:/a', { x: 1, y: 1 }), storage);
    savePins('p', NO_PINS, storage);
    expect(storage.data.size).toBe(0);
  });

  it('ignores corrupt or malformed stored data', () => {
    expect(parsePins('not json')).toEqual({});
    expect(parsePins('[1,2]')).toEqual({});
    expect(parsePins('null')).toEqual({});
    expect(parsePins(JSON.stringify({ ok: { x: 1, y: 2 }, bad: { x: 'a', y: 2 }, worse: 3, nan: { x: null, y: 1 } }))).toEqual({ ok: { x: 1, y: 2 } });
  });

  it('works without storage and when storage throws', () => {
    const throwing = {
      getItem: () => { throw new Error('blocked'); },
      setItem: () => { throw new Error('blocked'); },
      removeItem: () => { throw new Error('blocked'); },
    };
    expect(loadPins('p', null)).toEqual({});
    expect(loadPins('p', throwing)).toEqual({});
    expect(() => savePins('p', withPin(NO_PINS, 'n:/a', { x: 1, y: 1 }), throwing)).not.toThrow();
    expect(() => savePins('p', NO_PINS, throwing)).not.toThrow();
    expect(() => savePins('p', withPin(NO_PINS, 'n:/a', { x: 1, y: 1 }), null)).not.toThrow();
  });
});
