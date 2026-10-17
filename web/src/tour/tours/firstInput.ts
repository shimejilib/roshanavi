// はじめての入力ノード: make a node that sends the text "hello" on /hello and look at the data.

import type { TourContext, TourDef } from '../types';
import { isDialog, newInputsOn, publishersOf, typedTopic } from './helpers';

const TOPIC = '/hello';

const createdHello = (ctx: TourContext, known: readonly string[]) => newInputsOn(ctx, TOPIC, known);

export const firstInputTour: TourDef = {
  id: 'firstInput',
  docPath: 'docs/design/nodes.md',
  keepable: true,
  adopt: (ctx, baseline) => createdHello(ctx, baseline.targets).map((id) => ({ kind: 'target', id })),
  steps: [
    { id: 'open', resume: true, kind: 'do', tab: 'graph', target: 'create-input', side: 'bottom', done: (ctx) => isDialog(ctx, 'createInput') },
    { id: 'kind', kind: 'show', target: 'input-type-kind', side: 'left' },
    { id: 'topic', kind: 'do', target: 'input-topic', side: 'left', done: (ctx) => typedTopic(ctx, 'input-topic') === TOPIC },
    { id: 'value', kind: 'show', target: 'input-text', side: 'left' },
    {
      id: 'create', kind: 'do', target: 'input-submit', side: 'top',
      done: (ctx) => createdHello(ctx, ctx.baseline.targets).length > 0,
    },
    { id: 'appear', resume: true, kind: 'do', tab: 'graph', target: 'map', side: 'right', done: (ctx) => publishersOf(ctx, TOPIC).length > 0 },
    {
      id: 'node', kind: 'do', target: 'map', side: 'right',
      done: (ctx) => ctx.selection?.kind === 'node' && publishersOf(ctx, TOPIC).includes(ctx.selection.id),
    },
    { id: 'topicClick', kind: 'do', target: 'map', side: 'right', done: (ctx) => ctx.selection?.kind === 'topic' && ctx.selection.id === TOPIC },
    { id: 'data', kind: 'show', target: 'detail-pane', side: 'left' },
    { id: 'finish', kind: 'show' },
  ],
};

export const FIRST_INPUT_TOPIC = TOPIC;
