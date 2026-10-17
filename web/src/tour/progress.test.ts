import { describe, expect, it } from 'vitest';
import { EMPTY_PROGRESS, loadProgress, markCompleted, parseProgress, saveProgress, STORAGE_KEY, type KeyValueStore } from './progress';

function memoryStore(initial: Record<string, string> = {}): KeyValueStore & { data: Record<string, string> } {
  const data = { ...initial };
  return { data, getItem: (k) => data[k] ?? null, setItem: (k, v) => { data[k] = v; } };
}

const RUN = { tourId: 'qosFix', step: 4, status: 'running', fixtures: [{ kind: 'target', id: 'tour_qos_pub' }], baseline: { targets: ['talker'], scenarios: [] } };

describe('progress', () => {
  it('starts empty', () => {
    expect(loadProgress(memoryStore())).toEqual(EMPTY_PROGRESS);
  });

  it('round-trips completed tours, the welcome flag and the run (restored paused)', () => {
    const store = memoryStore();
    saveProgress({ completed: ['overview'], welcomeSeen: true, run: { ...RUN, status: 'running' } as never }, store);
    const back = loadProgress(store);
    expect(back.completed).toEqual(['overview']);
    expect(back.welcomeSeen).toBe(true);
    expect(back.run).toMatchObject({ tourId: 'qosFix', step: 4, status: 'paused', fixtures: [{ id: 'tour_qos_pub' }] });
  });

  it('ignores garbage: broken JSON, unknown tours, malformed runs', () => {
    expect(parseProgress('{nope')).toEqual(EMPTY_PROGRESS);
    expect(parseProgress(JSON.stringify({ completed: ['overview', 'bogus', 3], welcomeSeen: 'yes', run: { tourId: 'bogus' } }))).toEqual({ completed: ['overview'], welcomeSeen: false, run: null });
    expect(parseProgress(JSON.stringify({ run: { ...RUN, baseline: null } })).run).toBeNull();
  });

  it('drops malformed fixtures from a stored run (only well-formed ones can ever be removed)', () => {
    const run = { ...RUN, fixtures: [{ kind: 'target', id: 'tour_x' }, { kind: 'bogus', id: 'y' }, { kind: 'target' }, 'z', null] };
    expect(parseProgress(JSON.stringify({ run })).run?.fixtures).toEqual([{ kind: 'target', id: 'tour_x' }]);
  });

  it('works without storage, and when storage throws (private window, quota)', () => {
    const broken: KeyValueStore = { getItem: () => { throw new Error('denied'); }, setItem: () => { throw new Error('quota'); } };
    expect(loadProgress(broken)).toEqual(EMPTY_PROGRESS);
    expect(() => saveProgress(EMPTY_PROGRESS, broken)).not.toThrow();
    expect(loadProgress(null)).toEqual(EMPTY_PROGRESS);
    expect(() => saveProgress(EMPTY_PROGRESS, null)).not.toThrow();
  });

  it('marks a tour completed once', () => {
    const once = markCompleted(EMPTY_PROGRESS, 'overview');
    expect(markCompleted(once, 'overview')).toBe(once);
    expect(once.completed).toEqual(['overview']);
  });

  it('uses one versioned key', () => {
    const store = memoryStore();
    saveProgress(EMPTY_PROGRESS, store);
    expect(Object.keys(store.data)).toEqual([STORAGE_KEY]);
  });
});
