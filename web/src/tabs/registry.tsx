// Top-level tab registry.

import type { ReactNode } from 'react';
import { GraphTab } from '../graph/GraphTab';
import type { MessageKey } from '../i18n';
import { InjectTab } from '../inject/InjectTab';
import { LauncherTab } from '../launcher/LauncherTab';
import { NodeListTab } from '../nodelist/NodeListTab';
import { RecordingsTab } from '../recordings/RecordingsTab';
import { ResourcesTab } from '../resources/ResourcesTab';
import { ScenariosTab } from '../scenarios/ScenariosTab';
import { TrafficTab } from '../traffic/TrafficTab';

export interface TabDefinition {
  id: string;
  label: MessageKey;
  /** Keep the tab mounted while hidden (expensive views such as the graph). */
  keepMounted: boolean;
  render: (active: boolean) => ReactNode;
  /** The tab needs the whole width: the detail pane on the right is hidden while it is shown. */
  fullWidth?: boolean;
}

export const TABS: readonly TabDefinition[] = [
  { id: 'graph', label: 'tab.graph', keepMounted: true, render: (active) => <GraphTab active={active} /> },
  { id: 'nodes', label: 'tab.nodes', keepMounted: true, render: (active) => <NodeListTab active={active} /> },
  { id: 'traffic', label: 'tab.traffic', keepMounted: false, render: () => <TrafficTab /> },
  { id: 'inject', label: 'tab.inject', keepMounted: true, render: () => <InjectTab /> },
  { id: 'launcher', label: 'tab.launcher', keepMounted: true, render: () => <LauncherTab /> },
  { id: 'recordings', label: 'tab.recordings', keepMounted: false, render: () => <RecordingsTab /> },
  // Kept mounted: the record-mode screen keeps its expectations while you operate other tabs.
  { id: 'scenarios', label: 'tab.scenarios', keepMounted: true, fullWidth: true, render: () => <ScenariosTab /> },
  // Not kept mounted: its 1 Hz full snapshot socket only runs while the tab is open.
  { id: 'resources', label: 'tab.resources', keepMounted: false, fullWidth: true, render: () => <ResourcesTab /> },
];

export const DEFAULT_TAB = 'graph';
