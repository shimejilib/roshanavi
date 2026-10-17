// Shared fixtures for the node-list tests.

import type { NodeRow } from '../api/nodeListTypes';
import type { Target } from '../api/types';

export function row(key: string, over: Partial<NodeRow> = {}): NodeRow {
  return {
    key, node: key.startsWith('target:') ? null : key, name: key, role: 'mine', status: 'running', running: true,
    origin: { kind: 'run', package: 'demo_nodes_cpp', executable: 'talker' }, pid: 1, confidence: 'exact',
    target_id: 'talker', group: null, lifecycle: null, control: 'target', reason: null, ...over,
  };
}

export function target(id: string, nodes: string[], over: Partial<Target> = {}): Target {
  return {
    id, kind: 'run', role: 'mine', spec: { id, kind: 'run', package: 'demo_nodes_cpp', executable: id },
    status: 'running', exit_code: null, problem: null, pid: 1, pids: [1], command: null, started_at: 0,
    uptime_sec: 1, restart_count: 0, pending_restart: false,
    nodes: nodes.map((node) => ({ node, confidence: 'exact' as const, pid: 1 })), ...over,
  } as Target;
}
