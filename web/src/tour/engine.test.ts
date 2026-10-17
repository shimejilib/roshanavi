import { describe, expect, it } from 'vitest';
import { adoptFixtures, fixturesToRemove, goBack, goNext, isLastStep, planStep, rewindToResumePoint, settle, startRun, stepOf, targetSelector } from './engine';
import { ctxOf, dummyTarget } from './testing';
import type { RunState, StepDef, TourContext, TourDef } from './types';

const flag = (name: string) => (ctx: TourContext) => ctx.dom.all(`[data-tour="${name}"]`).length > 0;

const TOUR: TourDef = {
  id: 'overview', docPath: 'docs/x.md', keepable: true,
  adopt: (ctx, baseline) => ctx.targets.filter((tg) => !baseline.targets.includes(tg.id)).map((tg) => ({ kind: 'target', id: tg.id })),
  steps: [
    { id: 'a', kind: 'do', target: 'one', done: flag('one') },
    { id: 'b', kind: 'do', target: 'two', done: flag('two') },
    { id: 'c', kind: 'show', target: 'three' },
    { id: 'd', kind: 'do', done: () => true },
    { id: 'e', kind: 'show' },
  ],
};

const fresh = (over: Partial<RunState> = {}): RunState => ({ ...startRun(TOUR, { targets: [], scenarios: [] }, []), ...over });
const withDom = (...names: string[]) => ctxOf({ dom: { all: (sel) => names.filter((n) => sel === `[data-tour="${n}"]`).map(() => ({ value: '', checked: false, text: '', attr: () => null })) } });

describe('settle', () => {
  it('stays on a "do" step until its condition holds', () => {
    const run = fresh();
    expect(settle(TOUR, run, withDom())).toBe(run);
  });

  it('advances over every "do" step that is already done, and stops at a "show" step', () => {
    expect(settle(TOUR, fresh(), withDom('one', 'two')).step).toBe(2);
  });

  it('never skips a "show" step by itself', () => {
    expect(settle(TOUR, fresh({ step: 2 }), withDom('one', 'two')).step).toBe(2);
  });

  it('continues after the learner pressed 次へ on the show step', () => {
    expect(settle(TOUR, goNext(TOUR, fresh({ step: 2 })), withDom()).step).toBe(4);
  });

  it('does not leave the last step', () => {
    const last: TourDef = { ...TOUR, steps: [{ id: 'z', kind: 'do', done: () => true }] };
    expect(settle(last, startRun(last, { targets: [], scenarios: [] }, []), ctxOf()).step).toBe(0);
  });

  it('treats a condition that throws as "not done" (a broken tour must not break the app)', () => {
    const boom: StepDef = { id: 'x', kind: 'do', done: () => { throw new Error('boom'); } };
    const tour: TourDef = { ...TOUR, steps: [boom, { id: 'y', kind: 'show' }] };
    const run = startRun(tour, { targets: [], scenarios: [] }, []);
    expect(settle(tour, run, ctxOf())).toBe(run);
  });

  it('does nothing while paused or preparing', () => {
    for (const status of ['paused', 'preparing'] as const) {
      const run = fresh({ status });
      expect(settle(TOUR, run, withDom('one', 'two'))).toBe(run);
    }
  });
});

describe('adopting what the learner made', () => {
  it('adds new things once and never what existed before the tour', () => {
    const run = fresh({ baseline: { targets: ['old'], scenarios: [] } });
    const ctx = ctxOf({ targets: [dummyTarget('old', '/a'), dummyTarget('mine', '/b')] });
    const once = adoptFixtures(TOUR, run, ctx);
    expect(once.fixtures).toEqual([{ kind: 'target', id: 'mine' }]);
    expect(adoptFixtures(TOUR, once, ctx)).toBe(once);
  });

  it('settle adopts while the tour runs', () => {
    const ctx = ctxOf({ targets: [dummyTarget('mine', '/b')] });
    expect(settle(TOUR, fresh(), ctx).fixtures).toEqual([{ kind: 'target', id: 'mine' }]);
  });
});

describe('moving around', () => {
  it('goNext / goBack stay inside the tour', () => {
    expect(goBack(fresh()).step).toBe(0);
    expect(goNext(TOUR, fresh({ step: 4 })).step).toBe(4);
    expect(goNext(TOUR, fresh()).step).toBe(1);
    expect(isLastStep(TOUR, fresh({ step: 4 }))).toBe(true);
  });

  it('stepOf clamps an out-of-range step (steps changed between versions)', () => {
    expect(stepOf(TOUR, fresh({ step: 99 })).id).toBe('e');
    expect(stepOf(TOUR, fresh({ step: -3 })).id).toBe('a');
  });

  it('after a reload it goes back to the nearest safe step, or the start', () => {
    const tour: TourDef = {
      ...TOUR,
      steps: [{ id: 'a', kind: 'show' }, { id: 'b', kind: 'do', resume: true }, { id: 'c', kind: 'do' }, { id: 'd', kind: 'do' }],
    };
    const run = startRun(tour, { targets: [], scenarios: [] }, []);
    expect(rewindToResumePoint(tour, { ...run, step: 3 }).step).toBe(1);
    expect(rewindToResumePoint({ ...tour, steps: [{ id: 'a', kind: 'show' }, { id: 'b', kind: 'do' }] }, { ...run, step: 1 }).step).toBe(0);
  });
});

describe('target and plan', () => {
  it('a name becomes a data-tour selector; a selector is used as it is; a function sees the context', () => {
    const ctx = ctxOf({ tab: 'inject' });
    expect(targetSelector({ id: 'x', kind: 'show', target: 'map' }, ctx)).toBe('[data-tour="map"]');
    expect(targetSelector({ id: 'x', kind: 'show', target: '[data-tour="a"][data-x="1"]' }, ctx)).toBe('[data-tour="a"][data-x="1"]');
    expect(targetSelector({ id: 'x', kind: 'show', target: (c) => `tab-${c.tab}` }, ctx)).toBe('[data-tour="tab-inject"]');
    expect(targetSelector({ id: 'x', kind: 'show' }, ctx)).toBeNull();
  });

  it('a target that is not on the page gives a centered step with the missing-target note', () => {
    const plan = planStep(TOUR, fresh(), ctxOf(), false);
    expect(plan).toMatchObject({ selector: '[data-tour="one"]', centered: true, missingTarget: true, kind: 'do', total: 5 });
  });

  it('a found target is highlighted; a step without a target is centered without a warning', () => {
    expect(planStep(TOUR, fresh(), ctxOf(), true)).toMatchObject({ centered: false, missingTarget: false });
    expect(planStep(TOUR, fresh({ step: 4 }), ctxOf(), true)).toMatchObject({ centered: true, missingTarget: false, last: true, canBack: true });
  });
});

describe('cleanup', () => {
  it('removes everything unless the learner keeps what a keepable tour built', () => {
    const run = fresh({ fixtures: [{ kind: 'target', id: 't' }] });
    expect(fixturesToRemove(run, false, true)).toHaveLength(1);
    expect(fixturesToRemove(run, true, true)).toHaveLength(0);
    expect(fixturesToRemove(run, true, false)).toHaveLength(1);
  });
});
