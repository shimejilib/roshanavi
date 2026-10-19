import { describe, expect, it } from 'vitest';
import { bulkConfirmText, isEmptyPlan, planBulk, planFromSnapshot } from './bulk';
import { row, target } from './testRows';

describe('bulk plan', () => {
  const pair = target('pair', ['/talker', '/listener'], { kind: 'launch', spec: { id: 'pair', kind: 'launch', package: 'demo_nodes_cpp', launch_file: 'talker_listener_launch.py' } });
  const solo = target('solo', ['/solo']);
  const stopped = target('cam', [], { status: 'stopped' });
  const targets = [pair, solo, stopped];

  it('acts once per target and lists every node that stops with it', () => {
    const plan = planBulk('stop', [row('/talker', { target_id: 'pair', group: 'pair' }), row('/solo', { target_id: 'solo' })], targets);
    expect(plan.targets.map((s) => s.targetId)).toEqual(['pair', 'solo']);
    expect(plan.targets[0]?.nodes).toEqual(['/listener', '/talker']);
    expect(plan.alsoStopped).toEqual(['/listener']);
    const text = bulkConfirmText(plan);
    expect(text).toContain('次の 2 個を停止します');
    expect(text).toContain('launch ファイル talker_listener_launch.py: /listener, /talker');
    expect(text).toContain('選択していない次の 1 個のノードも一緒に止まります: /listener');
  });

  it('skips targets the action does not apply to', () => {
    const plan = planBulk('start', [row('/solo', { target_id: 'solo' }), row('target:cam', { target_id: 'cam', running: false })], targets);
    expect(plan.targets.map((s) => s.targetId)).toEqual(['cam']);
    expect(plan.skipped).toEqual([{ name: '/solo', reason: 'すでに動いています' }]);
    expect(bulkConfirmText(plan)).toContain('対象外: /solo (すでに動いています)');
  });

  it('switches lifecycle nodes with transitions, never signals', () => {
    const lc = row('/lc', { role: 'other', target_id: null, control: 'lifecycle', lifecycle: { state: 'active' } });
    const off = planBulk('stop', [lc], targets);
    expect(off.lifecycle).toEqual([{ node: '/lc', goal: 'inactive', external: true }]);
    const text = bulkConfirmText(off);
    expect(text).toContain('lifecycle ノード 1 個を無効 (inactive) にします');
    expect(text).toContain('roshanavi が起動していない lifecycle ノード');
    expect(planBulk('start', [lc], targets).skipped[0]?.reason).toBe('すでに動いています');
    expect(isEmptyPlan(planBulk('restart', [lc], targets))).toBe(true);
    const inactive = row('/lc', { ...lc, lifecycle: { state: 'unconfigured' } });
    expect(planBulk('start', [inactive], targets).lifecycle[0]?.goal).toBe('active');
  });

  it('ignores rows that cannot be controlled', () => {
    const plan = planBulk('stop', [row('/x', { target_id: null, control: 'none' })], targets);
    expect(isEmptyPlan(plan)).toBe(true);
    expect(plan.skipped[0]?.reason).toBe('操作できません');
  });

  it('plans from one snapshot: a row shown stopped is started even if live state lags', () => {
    // Issue Right after a stop the node list says stopped; the plan must use the targets of
    // that same response, not another (websocket) source that may still say running.
    const snapshot = {
      rows: [row('target:talker', { target_id: 'talker', running: false, status: 'stopped' })],
      targets: [target('talker', [], { status: 'stopped' })],
    };
    const plan = planFromSnapshot('start', snapshot, new Set(['target:talker']));
    expect(plan.targets.map((s) => s.targetId)).toEqual(['talker']);
    expect(planFromSnapshot('start', snapshot, new Set(['/gone'])).targets).toEqual([]);
  });

  it('only plans the selected rows of the snapshot', () => {
    const snapshot = { rows: [row('/solo', { target_id: 'solo' }), row('/talker', { target_id: 'pair', group: 'pair' })], targets };
    const plan = planFromSnapshot('stop', snapshot, new Set(['/solo']));
    expect(plan.targets.map((s) => s.targetId)).toEqual(['solo']);
  });
});
