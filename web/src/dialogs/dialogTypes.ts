// Modal dialogs that can be opened from anywhere (map menus, tabs, right pane).

export type DialogRequest =
  /** Create a persistent input (dummy) node; with `dummyId`, edit that one. */
  | { kind: 'createInput'; topic?: string; type?: string; dummyId?: string }
  /** Create a transform node (変換ノード) from `topic`; with `transformId`, edit that one. */
  | { kind: 'createTransform'; topic?: string; type?: string; transformId?: string }
  /** Create a function node (関数ノード); with `functionId`, edit that one. */
  | { kind: 'createFunction'; topic?: string; functionId?: string }
  | { kind: 'projects' }
  | { kind: 'params'; nodeId: string }
  | { kind: 'interface'; type: string }
  | { kind: 'edge'; topic: string; node: string; dir: 'pub' | 'sub' }
  | { kind: 'exportLaunch'; dummyId: string }
  | { kind: 'lifecycle'; nodeId: string }
  | { kind: 'launchImport' };
