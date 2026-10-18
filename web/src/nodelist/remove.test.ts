import { describe, expect, it } from 'vitest';
import { planRemove, planRemoveFromSnapshot, removeConfirmText } from './remove';
import { row, target } from './testRows';

describe('node-list delete plan', () => {
  const pair = target('pair', ['/talker', '/listener'], { kind: 'launch', spec: { id: 'pair', kind: 'launch', package: 'demo_nodes_cpp', launch_file: 'talker_listener_launch.py', takeover: true } as never });
  const cam = target('cam', [], { kind: 'dummy', status: 'stopped', spec: { id: 'cam' } as never });
  const targets = [pair, cam];

  it('deletes each registration once and lists what stops with it', () => {
    const plan = planRemove([row('/talker', { target_id: 'pair' }), row('/listener', { target_id: 'pair' }), row('target:cam', { target_id: 'cam', running: false })], targets);
    expect(plan.steps.map((s) => [s.targetId, s.running])).toEqual([['pair', true], ['cam', false]]);
    expect(plan.alsoStopped).toEqual([]);
    const only = planRemove([row('/talker', { target_id: 'pair' })], targets);
    expect(only.alsoStopped).toEqual(['/listener']);
    const text = removeConfirmText(only);
    expect(text).toContain('次の 1 件を roshanavi から削除します');
    expect(text).toContain('launch talker_listener_launch.py (launch): /listener, /talker — 動いています。削除すると止まります');
    expect(text).toContain('一緒に止まるノード (1): /listener');
    expect(text).toContain('ソースコード・パッケージ・パラメータファイル・録画は消えません');
    expect(text).toContain('launch ファイルを取り込み直すと戻ってきます');
    expect(text).toContain('10 秒間は「元に戻す」');
  });

  it('never deletes external nodes', () => {
    const ext = row('/ext', { role: 'other', target_id: null, control: 'none', reason: 'external' });
    const plan = planRemoveFromSnapshot({ rows: [ext, row('target:cam', { target_id: 'cam' })], targets }, new Set(['/ext', 'target:cam']));
    expect(plan.steps.map((s) => s.targetId)).toEqual(['cam']);
    expect(plan.skipped).toEqual([{ name: '/ext', reason: 'roshanavi が起動したものではない (外部のノード) ため削除できません' }]);
    const text = removeConfirmText(plan);
    expect(text).toContain('cam (入力ノード)');
    expect(text).toContain('削除しないもの: /ext');
    expect(text).not.toContain('取り込み直すと');
    expect(planRemove([ext], targets).steps).toEqual([]);
  });
});
