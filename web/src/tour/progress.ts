// Tour progress remembered by this browser (localStorage). Every access is guarded: private
// windows and blocked storage must leave the tours working, just without memory.

import type { Fixture, Progress, RunState, TourId } from './types';

export const STORAGE_KEY = 'roshanavi.tour.v1';
const TOUR_IDS: readonly TourId[] = ['overview', 'firstInput', 'qosFix', 'functionNode', 'scenario'];

export interface KeyValueStore {
  getItem: (key: string) => string | null;
  setItem: (key: string, value: string) => void;
}

export const EMPTY_PROGRESS: Progress = { completed: [], welcomeSeen: false, run: null };

function isTourId(value: unknown): value is TourId {
  return typeof value === 'string' && (TOUR_IDS as readonly string[]).includes(value);
}

function isFixture(value: unknown): value is Fixture {
  if (typeof value !== 'object' || value === null) return false;
  const v = value as Partial<Fixture>;
  return (v.kind === 'target' || v.kind === 'scenario') && typeof v.id === 'string' && v.id !== '';
}

function parseRun(value: unknown): RunState | null {
  if (typeof value !== 'object' || value === null) return null;
  const v = value as Partial<RunState>;
  if (!isTourId(v.tourId) || typeof v.step !== 'number' || !Array.isArray(v.fixtures)) return null;
  const baseline = v.baseline;
  if (!baseline || !Array.isArray(baseline.targets) || !Array.isArray(baseline.scenarios)) return null;
  // A page that was closed mid-tour comes back paused: the learner decides to continue.
  const runId = typeof baseline.runId === 'string' ? baseline.runId : null;
  return { tourId: v.tourId, step: Math.max(0, Math.floor(v.step)), status: 'paused', fixtures: v.fixtures.filter(isFixture), baseline: { ...baseline, runId } };
}

export function parseProgress(raw: string | null): Progress {
  if (!raw) return EMPTY_PROGRESS;
  try {
    const data = JSON.parse(raw) as Partial<Progress>;
    return {
      completed: Array.isArray(data.completed) ? data.completed.filter(isTourId) : [],
      welcomeSeen: data.welcomeSeen === true,
      run: parseRun(data.run),
    };
  } catch {
    return EMPTY_PROGRESS;
  }
}

export function defaultStore(): KeyValueStore | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage;
  } catch {
    return null;
  }
}

export function loadProgress(store: KeyValueStore | null = defaultStore()): Progress {
  try {
    return parseProgress(store?.getItem(STORAGE_KEY) ?? null);
  } catch {
    return EMPTY_PROGRESS;
  }
}

export function saveProgress(progress: Progress, store: KeyValueStore | null = defaultStore()): void {
  try {
    store?.setItem(STORAGE_KEY, JSON.stringify(progress));
  } catch {
    // Quota / blocked storage: the tour still works, it just will not be remembered.
  }
}

export function markCompleted(progress: Progress, id: TourId): Progress {
  return progress.completed.includes(id) ? progress : { ...progress, completed: [...progress.completed, id] };
}
