// Tour framework types (docs/design/ui.md "アプリ内チュートリアル").
// A tour is plain data: steps that point at `data-tour` elements and say when they are done.

import type { RecordEvent, RunResult } from '../api/scenarioTypes';
import type { GraphSnapshot, Target } from '../api/types';
import type { DialogRequest } from '../dialogs/dialogTypes';
import type { Selection } from '../state/AppState';

export type TourId = 'overview' | 'firstInput' | 'qosFix' | 'functionNode' | 'scenario';

/** What a "do" step may look at in the page (a fake in the unit tests). */
export interface DomEl {
  value: string;
  checked: boolean;
  text: string;
  attr: (name: string) => string | null;
}

/** Visible elements matching a selector (hidden tabs / closed dialogs yield nothing). */
export interface DomProbe {
  all: (selector: string) => DomEl[];
}

/** Everything a step condition can read: app state, live data, the page. Never written to. */
export interface TourContext {
  tab: string;
  selection: Selection;
  dialog: DialogRequest | null;
  graph: GraphSnapshot | null;
  targets: readonly Target[];
  recordActive: boolean;
  recordEvents: readonly RecordEvent[];
  scenarioRun: RunResult | null;
  /** Ids that existed before this tour started. */
  baseline: Baseline;
  dom: DomProbe;
}

export type Side = 'top' | 'right' | 'bottom' | 'left';

export interface StepDef {
  /** Part of the message keys: `tour.<tour>.<step>.title|body|hint`. */
  id: string;
  /** show: the learner presses 次へ. do: moves on by itself when `done` becomes true. */
  kind: 'show' | 'do';
  /** `data-tour` name, a CSS selector (contains `[`), or a function of the context. Absent: centered. */
  target?: string | ((ctx: TourContext) => string);
  /** Tab to switch to before looking for the target. */
  tab?: string;
  side?: Side;
  /** Condition of a "do" step. */
  done?: (ctx: TourContext) => boolean;
  /** A safe place to continue from after the page was reloaded (a dialog does not survive that). */
  resume?: boolean;
}

/** Something a tour created: removed again when the tour ends. */
export interface Fixture {
  kind: 'target' | 'scenario';
  id: string;
}

/** Ids that existed before the tour started: never adopted, never removed. */
export interface Baseline {
  targets: string[];
  scenarios: string[];
  /** The last scenario run before the tour (its result may still be on screen). */
  runId?: string | null;
}

export interface TourDef {
  id: TourId;
  steps: readonly StepDef[];
  /** Repo-relative doc page shown at the end (the docs are not reachable offline). */
  docPath: string;
  /** The tour offers to keep what the learner built (otherwise it is always removed). */
  keepable: boolean;
  /** Creates what the lesson needs (through the API); returns it so it can be removed again. */
  prepare?: (graph: GraphSnapshot | null) => Promise<Fixture[]>;
  /** Things the learner created by following the steps and that the tour should remove at the end. */
  adopt?: (ctx: TourContext, baseline: Baseline) => Fixture[];
}

export type RunStatus = 'preparing' | 'running' | 'paused';

/** The one tour in progress (persisted, so a reload resumes it). */
export interface RunState {
  tourId: TourId;
  step: number;
  status: RunStatus;
  fixtures: Fixture[];
  baseline: Baseline;
}

export interface Progress {
  completed: TourId[];
  welcomeSeen: boolean;
  run: RunState | null;
}
