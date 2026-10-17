// Modal dialogs that can be opened from anywhere (map menus, tabs, right pane).

export type DialogRequest =
  /** Create a persistent input (dummy) node; with `dummyId`, edit that one. */
  | { kind: 'createInput'; topic?: string; type?: string; dummyId?: string }
  | { kind: 'params'; nodeId: string }
  | { kind: 'interface'; type: string }
  | { kind: 'edge'; topic: string; node: string; dir: 'pub' | 'sub' }
  | { kind: 'exportLaunch'; dummyId: string }
  | { kind: 'lifecycle'; nodeId: string }
  | { kind: 'launchImport' };
