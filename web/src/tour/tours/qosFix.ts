// 届かない原因を見つけて直す: a BEST_EFFORT sender and a RELIABLE receiver; read the reason, fix it.

import type { DummySpec } from '../../api/types';
import { prepareQosPair, QOS_PUB, QOS_TOPIC } from '../fixtures';
import type { TourDef } from '../types';
import { hasQosProblem, isDialog } from './helpers';

const PUB_NODE = `/${QOS_PUB}`;

export const qosFixTour: TourDef = {
  id: 'qosFix',
  docPath: 'docs/design/map-and-traffic.md',
  keepable: false,
  prepare: () => prepareQosPair(),
  steps: [
    { id: 'prepare', kind: 'do', tab: 'graph', target: 'map', side: 'right', done: (ctx) => hasQosProblem(ctx, QOS_TOPIC) },
    { id: 'look', kind: 'show', target: 'map', side: 'right' },
    {
      id: 'diag', kind: 'do', target: `[data-tour="diag-item"][data-tour-topic="${QOS_TOPIC}"]`, side: 'left',
      done: (ctx) => ctx.selection?.kind === 'topic' && ctx.selection.id === QOS_TOPIC,
    },
    { id: 'reason', kind: 'show', target: 'detail-pane', side: 'left' },
    { id: 'sender', resume: true, kind: 'do', target: 'map', side: 'right', done: (ctx) => ctx.selection?.kind === 'node' && ctx.selection.id === PUB_NODE },
    {
      id: 'edit', kind: 'do', target: 'node-edit', side: 'left',
      done: (ctx) => ctx.dialog?.kind === 'createInput' && ctx.dialog.dummyId === QOS_PUB,
    },
    {
      id: 'save', kind: 'do', target: 'input-submit', side: 'top',
      done: (ctx) => ctx.targets.some((tg) => tg.id === QOS_PUB && (tg.spec as DummySpec).qos?.reliability === 'reliable') && !isDialog(ctx, 'createInput'),
    },
    { id: 'fixed', kind: 'do', target: 'map', side: 'right', done: (ctx) => !hasQosProblem(ctx, QOS_TOPIC) },
    { id: 'finish', kind: 'show' },
  ],
};

