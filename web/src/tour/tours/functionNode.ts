// 関数ノードを作る: roshanavi_examples.logic.shout as a node, /chatter -> /shouted.

import { CHATTER_SOURCE, ensurePublisher } from '../fixtures';
import type { StepDef, TourDef } from '../types';
import { domText, domValue, isDialog, newFunctionsTo, publishersOf, typedTopic } from './helpers';

const IN = '/chatter';
const OUT = '/shouted';

/** The echo shows `"data": "HELLO WORLD!"`: the text after `data` has capitals and no small letters. */
export function isShouted(echo: string): boolean {
  const match = /"?data"?\s*:\s*(.+)/.exec(echo);
  const text = match?.[1] ?? '';
  return /[A-Z]{2,}/.test(text) && !/[a-z]/.test(text);
}

const steps: StepDef[] = [
  { id: 'open', resume: true, kind: 'do', tab: 'graph', target: 'create-function', side: 'bottom', done: (ctx) => isDialog(ctx, 'createFunction') },
  { id: 'module', kind: 'do', target: 'function-module', side: 'left', done: (ctx) => domValue(ctx, 'function-module') === 'roshanavi_examples.logic' },
  { id: 'function', kind: 'do', target: 'function-name', side: 'left', done: (ctx) => domValue(ctx, 'function-name') === 'shout' },
  { id: 'input', kind: 'do', target: 'function-input-0-topic', side: 'left', done: (ctx) => typedTopic(ctx, 'function-input-0-topic') === IN },
  { id: 'output', kind: 'do', target: 'function-output-topic', side: 'left', done: (ctx) => typedTopic(ctx, 'function-output-topic') === OUT },
  {
    id: 'create', kind: 'do', target: 'function-submit', side: 'top',
    done: (ctx) => newFunctionsTo(ctx, OUT, ctx.baseline.targets).length > 0,
  },
  { id: 'appear', resume: true, kind: 'do', tab: 'graph', target: 'map', side: 'right', done: (ctx) => publishersOf(ctx, OUT).length > 0 },
  { id: 'echo', kind: 'do', target: 'detail-pane', side: 'left', done: (ctx) => isShouted(domText(ctx, 'echo-body')) },
  { id: 'finish', kind: 'show' },
];

export const functionNodeTour: TourDef = {
  id: 'functionNode',
  docPath: 'docs/design/nodes.md',
  keepable: true,
  prepare: (graph) => ensurePublisher(graph, IN, CHATTER_SOURCE, 'hello world'),
  adopt: (ctx, baseline) => newFunctionsTo(ctx, OUT, baseline.targets).map((id) => ({ kind: 'target', id })),
  steps,
};
