// Tour engine: pure functions over RunState (unit-tested; no DOM, no React, no network).

import type { Baseline, Fixture, RunState, StepDef, TourContext, TourDef } from './types';

export function startRun(tour: TourDef, baseline: Baseline, fixtures: Fixture[]): RunState {
  return { tourId: tour.id, step: 0, status: 'running', fixtures: dedupe(fixtures), baseline };
}

export function stepOf(tour: TourDef, run: RunState): StepDef {
  return tour.steps[Math.min(Math.max(run.step, 0), tour.steps.length - 1)] as StepDef;
}

export const isLastStep = (tour: TourDef, run: RunState): boolean => run.step >= tour.steps.length - 1;

function dedupe(fixtures: readonly Fixture[]): Fixture[] {
  const seen = new Set<string>();
  return fixtures.filter((f) => {
    const key = `${f.kind}:${f.id}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/** Adds what the learner created since the start (never something that existed before). */
export function adoptFixtures(tour: TourDef, run: RunState, ctx: TourContext): RunState {
  if (!tour.adopt) return run;
  const known = new Set(run.fixtures.map((f) => `${f.kind}:${f.id}`));
  const fresh = tour.adopt(ctx, run.baseline).filter((f) => !known.has(`${f.kind}:${f.id}`));
  return fresh.length ? { ...run, fixtures: [...run.fixtures, ...fresh] } : run;
}

/** A condition that throws counts as "not done yet": a broken tour must not break the app. */
function isDone(step: StepDef, ctx: TourContext): boolean {
  try {
    return Boolean(step.done?.(ctx));
  } catch {
    return false;
  }
}

/**
 * Moves forward over every "do" step whose condition already holds (one step per call is not
 * enough: finishing the dialog also satisfies "dialog closed" of the step after it). The last
 * step is only left by the learner.
 */
export function settle(tour: TourDef, run: RunState, ctx: TourContext): RunState {
  if (run.status !== 'running') return run;
  let next = adoptFixtures(tour, run, ctx);
  for (let guard = 0; guard < tour.steps.length; guard += 1) {
    const step = stepOf(tour, next);
    if (step.kind !== 'do' || isLastStep(tour, next) || !isDone(step, ctx)) break;
    next = { ...next, step: next.step + 1 };
  }
  return next;
}

export function goNext(tour: TourDef, run: RunState): RunState {
  return isLastStep(tour, run) ? run : { ...run, step: run.step + 1 };
}

/** After a reload: back to the nearest step that can be continued from (or the first). */
export function rewindToResumePoint(tour: TourDef, run: RunState): RunState {
  for (let i = Math.min(run.step, tour.steps.length - 1); i > 0; i -= 1) {
    if (tour.steps[i]?.resume) return { ...run, step: i };
  }
  return { ...run, step: 0 };
}

export function goBack(run: RunState): RunState {
  return run.step <= 0 ? run : { ...run, step: run.step - 1 };
}

export function targetSelector(step: StepDef, ctx: TourContext): string | null {
  const raw = typeof step.target === 'function' ? step.target(ctx) : step.target;
  if (!raw) return null;
  return raw.includes('[') ? raw : `[data-tour="${raw}"]`;
}

export function messageKey(tour: TourDef, step: StepDef, part: 'title' | 'body' | 'hint'): string {
  return `tour.${tour.id}.${step.id}.${part}`;
}

export interface StepPlan {
  selector: string | null;
  /** The target is missing: the popover is centered and says so. */
  centered: boolean;
  showHint: boolean;
  step: number;
  total: number;
  kind: StepDef['kind'];
  last: boolean;
  canBack: boolean;
  /** Shown when the target is missing, so the learner is never stuck on an invisible step. */
  missingTarget: boolean;
}

/** What to draw for the current step; `targetFound` comes from the page. */
export function planStep(tour: TourDef, run: RunState, ctx: TourContext, targetFound: boolean): StepPlan {
  const step = stepOf(tour, run);
  const selector = targetSelector(step, ctx);
  const missing = selector !== null && !targetFound;
  return {
    selector,
    centered: selector === null || missing,
    showHint: step.kind === 'do',
    step: run.step,
    total: tour.steps.length,
    kind: step.kind,
    last: isLastStep(tour, run),
    canBack: run.step > 0,
    missingTarget: missing,
  };
}

/** Fixtures that must be removed when the tour ends or is abandoned. */
export function fixturesToRemove(run: RunState, keep: boolean, keepable: boolean): Fixture[] {
  return keep && keepable ? [] : run.fixtures;
}
