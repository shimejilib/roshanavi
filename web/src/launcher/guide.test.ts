import { describe, expect, it } from 'vitest';
import type { Target, WorkspacePackage } from '../api/types';
import { canTryTalker, needsGuide, tryTalkerSpec } from './guide';

const target = (id: string, kind: Target['kind']): Target => ({
  id, kind, role: kind === 'dummy' ? 'dummy' : 'mine', spec: { id, kind: 'run', package: 'p', executable: 'e' },
  status: 'stopped', exit_code: null, problem: null, pid: null, pids: [], command: null, started_at: null,
  uptime_sec: null, restart_count: 0, pending_restart: false,
});

describe('launcher first-run guide', () => {
  it('shows only when no run / launch target exists', () => {
    expect(needsGuide([])).toBe(true);
    expect(needsGuide([target('in', 'dummy')])).toBe(true);
    expect(needsGuide([target('t', 'run')])).toBe(false);
  });

  it('builds a named talker with a free id', () => {
    expect(tryTalkerSpec([])).toEqual(expect.objectContaining({ id: 'talker', name: 'talker', package: 'demo_nodes_cpp', executable: 'talker', role: 'mine' }));
    expect(tryTalkerSpec([target('talker', 'dummy')]).id).toBe('talker-2');
    expect(tryTalkerSpec([target('talker', 'dummy')]).name).toBe('talker_2');
  });

  it('needs demo_nodes_cpp to offer the button', () => {
    const pkg = { name: 'demo_nodes_cpp', executables: ['talker'] } as WorkspacePackage;
    expect(canTryTalker([pkg])).toBe(true);
    expect(canTryTalker([])).toBe(false);
  });
});
