// Top-level tab registry. Later phases (Scenarios, ...) register here.

import type { ReactNode } from 'react';
import { GraphTab } from '../graph/GraphTab';
import type { MessageKey } from '../i18n';
import { InjectTab } from '../inject/InjectTab';
import { LauncherTab } from '../launcher/LauncherTab';
import { TrafficTab } from '../traffic/TrafficTab';

export interface TabDefinition {
  id: string;
  label: MessageKey;
  /** Keep the tab mounted while hidden (expensive views such as the graph). */
  keepMounted: boolean;
  render: (active: boolean) => ReactNode;
}

export const TABS: readonly TabDefinition[] = [
  { id: 'graph', label: 'tab.graph', keepMounted: true, render: (active) => <GraphTab active={active} /> },
  { id: 'traffic', label: 'tab.traffic', keepMounted: false, render: () => <TrafficTab /> },
  { id: 'inject', label: 'tab.inject', keepMounted: true, render: () => <InjectTab /> },
  { id: 'launcher', label: 'tab.launcher', keepMounted: true, render: () => <LauncherTab /> },
];

export const DEFAULT_TAB = 'graph';
