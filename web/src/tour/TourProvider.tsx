// Tour state: the run in progress, what is done, and the actions (start / next / pause / finish).
// All decisions are made by the pure engine (engine.ts); this file only connects it to the app.

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { describeError } from '../api/client';
import { t } from '../i18n';
import { useAppState } from '../state/AppState';
import { useLive } from '../state/LiveProvider';
import { useScenarioLive } from '../scenarios/ScenarioLive';
import { DOM_PROBE, findVisible } from './dom';
import { fixturesToRemove, goBack, goNext, planStep, rewindToResumePoint, settle, startRun, stepOf, targetSelector, type StepPlan } from './engine';
import { removeFixtures, takeBaseline } from './fixtures';
import { loadProgress, markCompleted, saveProgress } from './progress';
import type { Progress, RunState, TourContext, TourDef, TourId } from './types';
import { tourById } from './tours';

const TICK_MS = 250;

interface TourApi {
  progress: Progress;
  run: RunState | null;
  def: TourDef | null;
  plan: StepPlan | null;
  message: string | null;
  showWelcome: boolean;
  start: (id: TourId) => void;
  next: () => void;
  back: () => void;
  pause: () => void;
  resume: () => void;
  quit: () => void;
  finish: (keep: boolean) => void;
  dismissWelcome: () => void;
  clearMessage: () => void;
}

const TourContextValue = createContext<TourApi | null>(null);

const NO_BASELINE = { targets: [], scenarios: [], runId: null };

/** A page reload leaves the run paused at a step it can be continued from. */
function initialProgress(): Progress {
  const stored = loadProgress();
  if (!stored.run) return stored;
  return { ...stored, run: rewindToResumePoint(tourById(stored.run.tourId), stored.run) };
}

export function TourProvider({ children }: { children: ReactNode }) {
  const app = useAppState();
  const { live } = useLive();
  const scenarios = useScenarioLive();
  const [progress, setProgress] = useState<Progress>(initialProgress);
  const [message, setMessage] = useState<string | null>(null);
  const [targetFound, setTargetFound] = useState(true);
  const progressRef = useRef(progress);
  const busy = useRef(false);

  // The newest app state for the timer callback (which must not capture stale values).
  const latest = useRef<Omit<TourContext, 'baseline' | 'dom'>>({
    tab: app.tab, selection: app.selection, dialog: app.dialog, graph: live.graph, targets: live.targets,
    recordActive: scenarios.record.active, recordEvents: scenarios.events, scenarioRun: scenarios.run,
  });
  latest.current = {
    tab: app.tab, selection: app.selection, dialog: app.dialog, graph: live.graph, targets: live.targets,
    recordActive: scenarios.record.active, recordEvents: scenarios.events, scenarioRun: scenarios.run,
  };

  const update = useCallback((change: (p: Progress) => Progress) => {
    const next = change(progressRef.current);
    progressRef.current = next;
    setProgress(next);
    saveProgress(next);
  }, []);
  const updateRun = useCallback((change: (r: RunState) => RunState) => {
    update((p) => (p.run ? { ...p, run: change(p.run) } : p));
  }, [update]);

  const contextFor = (run: RunState): TourContext => ({ ...latest.current, baseline: run.baseline, dom: DOM_PROBE });

  // Re-checks the current step on a timer: conditions read form fields and the page, which
  // do not announce changes.
  useEffect(() => {
    const timer = window.setInterval(() => {
      const run = progressRef.current.run;
      if (!run || run.status !== 'running') return;
      try {
        const def = tourById(run.tourId);
        const ctx = contextFor(run);
        const next = settle(def, run, ctx);
        if (next !== run) updateRun(() => next);
        const selector = targetSelector(stepOf(def, next), ctx);
        setTargetFound(selector === null || findVisible(selector) !== null);
      } catch (err) {
        console.error('[tour] step check failed', err);
      }
    }, TICK_MS);
    return () => window.clearInterval(timer);
    // contextFor only reads refs.
  }, [updateRun]);

  // Entering a step on another tab switches to it.
  const runTour = progress.run?.tourId;
  const runStep = progress.run?.step;
  const runStatus = progress.run?.status;
  useEffect(() => {
    if (!runTour || runStep === undefined || runStatus !== 'running') return;
    const wanted = stepOf(tourById(runTour), { tourId: runTour, step: runStep, status: 'running', fixtures: [], baseline: NO_BASELINE }).tab;
    if (wanted && latest.current.tab !== wanted) app.setTab(wanted);
    setTargetFound(true);
    // `app.setTab` is a state setter.
  }, [runTour, runStep, runStatus]);

  const end = useCallback(async (run: RunState, keep: boolean, completed: boolean) => {
    const def = tourById(run.tourId);
    update((p) => ({ ...(completed ? markCompleted(p, run.tourId) : p), run: null }));
    const failed = await removeFixtures(fixturesToRemove(run, keep, def.keepable));
    if (failed.length) setMessage(t('tour.ui.cleanupFailed', { ids: failed.join(', ') }));
  }, [update]);

  const start = useCallback((id: TourId) => {
    if (busy.current) return;
    const current = progressRef.current.run;
    if (current && current.tourId === id && current.status === 'paused') {
      updateRun((r) => ({ ...r, status: 'running' }));
      return;
    }
    busy.current = true;
    void (async () => {
      try {
        if (current) await end(current, false, false);
        const def = tourById(id);
        setMessage(null);
        app.closeDialog();
        app.select(null);
        app.setIsolation(null);
        update((p) => ({ ...p, welcomeSeen: true, run: { tourId: id, step: 0, status: 'preparing', fixtures: [], baseline: NO_BASELINE } }));
        const baseline = await takeBaseline();
        const fixtures = (await def.prepare?.(latest.current.graph)) ?? [];
        if (progressRef.current.run?.status !== 'preparing') {
          await removeFixtures(fixtures); // the learner quit while it was being prepared
          return;
        }
        update((p) => ({ ...p, run: startRun(def, baseline, fixtures) }));
      } catch (err) {
        setMessage(t('tour.ui.prepareFailed', { message: describeError(err) }));
        update((p) => ({ ...p, run: null }));
      } finally {
        busy.current = false;
      }
    })();
    // The app actions are state setters.
  }, [update, updateRun, end]);

  const api = useMemo<TourApi>(() => {
    const run = progress.run;
    const def = run ? tourById(run.tourId) : null;
    const plan = run && def ? planStep(def, run, { ...latest.current, baseline: run.baseline, dom: DOM_PROBE }, targetFound) : null;
    return {
      progress, run, def, plan, message,
      showWelcome: !progress.welcomeSeen && !progress.run && live.graph !== null && app.dialog === null,
      start,
      next: () => def && updateRun((r) => goNext(def, r)),
      back: () => updateRun(goBack),
      pause: () => updateRun((r) => (r.status === 'running' ? { ...r, status: 'paused' } : r)),
      resume: () => updateRun((r) => ({ ...r, status: 'running' })),
      quit: () => { if (run) void end(run, false, false); },
      finish: (keep) => { if (run) void end(run, keep, true); },
      dismissWelcome: () => update((p) => ({ ...p, welcomeSeen: true })),
      clearMessage: () => setMessage(null),
    };
    // `latest` is read at render time on purpose; the timer keeps `targetFound` fresh.
  }, [progress, message, targetFound, live.graph, app.dialog, start, updateRun, update, end]);

  // Esc pauses the tour. A dialog handles its own Esc first (it stops the event).
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented) return;
      if (progressRef.current.run?.status === 'running') api.pause();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [api]);

  return <TourContextValue.Provider value={api}>{children}</TourContextValue.Provider>;
}

export function useTour(): TourApi {
  const ctx = useContext(TourContextValue);
  if (!ctx) throw new Error('useTour must be used inside <TourProvider>');
  return ctx;
}
