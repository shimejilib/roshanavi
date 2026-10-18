import { describe, expect, it } from 'vitest';
import type { GraphNode, Target } from '../api/types';
import { actionLabel, affectedNodes, confirmText, nodeControl } from './nodeControl';

const node = (over: Partial<GraphNode> = {}): GraphNode => ({ id: '/talker', name: 'talker', namespace: '/', role: 'other', ...over });

function target(over: Partial<Target> = {}): Target {
  return {
    id: 'talker', kind: 'run', role: 'mine',
    spec: { id: 'talker', kind: 'run', package: 'demo_nodes_cpp', executable: 'talker' },
    status: 'running', exit_code: null, problem: null, pid: 1, pids: [1], command: null,
    started_at: 0, uptime_sec: 1, restart_count: 0, pending_restart: false,
    nodes: [{ node: '/talker', confidence: 'exact', pid: 1 }],
    ...over,
  } as Target;
}

describe('nodeControl availability', () => {
  it('offers nothing for nodes roshanavi did not start', () => {
    const c = nodeControl(node(), []);
    expect(c.kind).toBe('none');
    if (c.kind === 'none') expect(c.reason).toContain('ランチャーから起動すると');
  });

  it('stops inject jobs (virtual dummy nodes)', () => {
    const c = nodeControl(node({ id: 'dummy:j1', role: 'dummy', job_id: 'j1' }), []);
    expect(c).toEqual({ kind: 'job', jobId: 'j1', actions: ['stop'] });
    expect(actionLabel('stop', c)).toBe('ジョブを停止');
  });

  it('stop / restart a running target, start a stopped one', () => {
    const owned = node({ role: 'mine', target_id: 'talker' });
    expect(nodeControl(owned, [target()])).toMatchObject({ kind: 'target', actions: ['stop', 'restart'] });
    expect(nodeControl(owned, [target({ status: 'exited' })])).toMatchObject({ actions: ['start'] });
    expect(nodeControl(owned, [target({ status: 'invalid' })])).toMatchObject({ actions: [] });
    // persistent dummies are targets too
    const dummy = node({ id: '/dummy_cam', role: 'dummy', target_id: 'cam' });
    expect(nodeControl(dummy, [target({ id: 'cam', kind: 'dummy', role: 'dummy' })])).toMatchObject({ kind: 'target' });
  });
});

describe('confirmText', () => {
  it('asks a simple question for a single node', () => {
    const c = nodeControl(node({ role: 'mine', target_id: 'talker' }), [target()]);
    expect(confirmText('stop', c, '/talker')).toBe('/talker を停止します。よろしいですか?');
    expect(confirmText('restart', c, '/talker')).toBeNull();
    expect(confirmText('start', c, '/talker')).toBeNull();
  });

  it('lists every node of a launch file', () => {
    const tg = target({
      kind: 'launch',
      spec: { id: 'demo', kind: 'launch', package: 'demo', launch_file: 'demo.launch.py' },
      nodes: [{ node: '/b', confidence: 'exact', pid: 2 }, { node: '/a', confidence: 'exact', pid: 3 }],
    });
    const c = nodeControl(node({ id: '/a', role: 'dependency', target_id: 'talker' }), [tg]);
    expect(confirmText('stop', c, '/a')).toBe(
      'このノードは起動セット (launch ファイル) demo.launch.py で起動されています。停止すると次の 2 個のノードも停止します: /a, /b',
    );
    expect(confirmText('restart', c, '/a')).toContain('2 個のノード');
  });

  it('lists nodes sharing one process (composable container)', () => {
    const tg = target({ nodes: [{ node: '/x', confidence: 'exact', pid: 1 }, { node: '/y', confidence: 'heuristic', pid: 1 }] });
    const c = nodeControl(node({ id: '/x', role: 'mine', target_id: 'talker' }), [tg]);
    expect(confirmText('stop', c, '/x')).toContain('起動リストの talker のプロセス');
    expect(affectedNodes(target({ nodes: [] }), '/z')).toEqual(['/z']);
  });

  it('does not confirm job stops', () => {
    expect(confirmText('stop', nodeControl(node({ job_id: 'j' }), []), 'dummy:j')).toBeNull();
  });
});
