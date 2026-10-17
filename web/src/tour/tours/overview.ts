// 画面の見方: a look around, nothing to operate.

import type { TourDef } from '../types';

export const overviewTour: TourDef = {
  id: 'overview',
  docPath: 'docs/design/ui.md',
  keepable: false,
  steps: [
    { id: 'intro', resume: true, kind: 'show', tab: 'graph' },
    { id: 'map', resume: true, kind: 'show', tab: 'graph', target: 'map', side: 'right' },
    { id: 'legend', resume: true, kind: 'show', tab: 'graph', target: 'legend', side: 'top' },
    { id: 'diagnostics', resume: true, kind: 'show', tab: 'graph', target: 'diagnostics', side: 'left' },
    { id: 'lastUpdate', resume: true, kind: 'show', tab: 'graph', target: 'last-update', side: 'bottom' },
    { id: 'trafficTab', resume: true, kind: 'show', target: 'tab-traffic', side: 'bottom' },
    { id: 'trafficView', resume: true, kind: 'show', tab: 'traffic', target: 'traffic-view', side: 'bottom' },
    { id: 'nodes', resume: true, kind: 'show', tab: 'nodes', target: 'node-table', side: 'top' },
    { id: 'settings', resume: true, kind: 'show', target: 'settings', side: 'bottom' },
    { id: 'finish', resume: true, kind: 'show', tab: 'graph' },
  ],
};
