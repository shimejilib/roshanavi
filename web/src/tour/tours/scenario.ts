// シナリオを記録する: record "send hello -> HELLO comes back", save it, run it, see it pass.

import { prepareShoutNode, SHOUT_IN, SHOUT_OUT } from '../fixtures';
import type { StepDef, TourContext, TourDef } from '../types';
import { domChecked, domExists, domValue, publishersOf, sel, typedTopic } from './helpers';

/** Project scenarios shown in the list that did not exist before the tour. */
function newScenarios(ctx: TourContext): string[] {
  return ctx.dom
    .all(sel('scn-item'))
    .filter((el) => el.attr('data-scn-source') === 'project')
    .map((el) => el.attr('data-scn-id') ?? '')
    .filter((id) => id !== '' && !ctx.baseline.scenarios.includes(id));
}

const sentOnInput = (ctx: TourContext): boolean =>
  ctx.recordEvents.some((ev) => ev.kind === 'op' && ev.op.kind === 'inject' && ev.op.request.topic === SHOUT_IN);

/** A value inside a quoted attribute selector (scenario file names are the learner's). */
const cssString = (value: string): string => value.replace(/["\\]/g, '\\$&');

/** The run the learner started in this tour (an older result may still be on screen). */
const ownRun = (ctx: TourContext) => (ctx.scenarioRun && ctx.scenarioRun.run_id !== (ctx.baseline.runId ?? null) ? ctx.scenarioRun : null);

const steps: StepDef[] = [
  { id: 'prepare', kind: 'do', tab: 'graph', target: 'map', side: 'right', done: (ctx) => publishersOf(ctx, SHOUT_OUT).length > 0 },
  { id: 'tab', resume: true, kind: 'do', target: 'tab-scenarios', side: 'bottom', done: (ctx) => ctx.tab === 'scenarios' },
  { id: 'record', kind: 'do', tab: 'scenarios', target: 'scn-record-open', side: 'right', done: (ctx) => domExists(ctx, 'scn-rec-start') },
  { id: 'watch', kind: 'do', target: `scn-watch-${SHOUT_OUT}`, side: 'right', done: (ctx) => domChecked(ctx, `scn-watch-${SHOUT_OUT}`) },
  { id: 'start', kind: 'do', target: 'scn-rec-start', side: 'top', done: (ctx) => ctx.recordActive },
  { id: 'injectTab', resume: true, kind: 'do', target: 'tab-inject', side: 'bottom', done: (ctx) => ctx.tab === 'inject' },
  { id: 'topic', kind: 'do', target: 'inject-topic', side: 'right', done: (ctx) => typedTopic(ctx, 'inject-topic') === SHOUT_IN },
  { id: 'message', kind: 'do', target: 'inject-yaml', side: 'right', done: (ctx) => /data:\s*["']?[^\s"']/.test(domValue(ctx, 'inject-yaml')) },
  { id: 'send', kind: 'do', target: 'inject-start', side: 'top', done: sentOnInput },
  { id: 'back', resume: true, kind: 'do', target: 'tab-scenarios', side: 'bottom', done: (ctx) => ctx.tab === 'scenarios' },
  {
    id: 'answer', kind: 'do', target: `[data-tour="scn-tl-msg"][data-topic="${SHOUT_OUT}"]`, side: 'left',
    done: (ctx) => domExists(ctx, 'scn-expect-this'),
  },
  { id: 'expect', kind: 'do', target: 'scn-expect-this', side: 'left', done: (ctx) => domExists(ctx, 'scn-pick-add') },
  { id: 'add', kind: 'do', target: 'scn-pick-add', side: 'left', done: (ctx) => ctx.dom.all(`${sel('scn-rec-steps')} li`).length >= 2 },
  { id: 'stop', kind: 'do', target: 'scn-rec-stop', side: 'bottom', done: (ctx) => !ctx.recordActive },
  { id: 'name', kind: 'show', target: 'scn-rec-name', side: 'top' },
  { id: 'save', kind: 'do', target: 'scn-rec-save', side: 'top', done: (ctx) => newScenarios(ctx).length > 0 },
  {
    id: 'run', kind: 'do', tab: 'scenarios',
    target: (ctx) => `[data-tour="scn-run"][data-scn-id="${cssString(newScenarios(ctx)[0] ?? '')}"]`, side: 'right',
    done: (ctx) => ownRun(ctx) !== null,
  },
  {
    id: 'passed', kind: 'do', target: 'scn-result', side: 'left',
    done: (ctx) => ownRun(ctx)?.status === 'passed',
  },
  { id: 'finish', kind: 'show' },
];

export const scenarioTour: TourDef = {
  id: 'scenario',
  docPath: 'docs/design/scenarios.md',
  keepable: false,
  prepare: () => prepareShoutNode(),
  adopt: (ctx) => newScenarios(ctx).map((id) => ({ kind: 'scenario', id })),
  steps,
};
