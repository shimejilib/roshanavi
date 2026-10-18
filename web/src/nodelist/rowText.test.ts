import { describe, expect, it } from 'vitest';
import { row } from './testRows';
import { confidenceText, disabledReason, lifecycleStateText, originText, statusText } from './rowText';

describe('row text', () => {
  it('describes where a node came from', () => {
    expect(originText(row('/t'))).toBe('demo_nodes_cpp / talker');
    expect(originText(row('/t', { origin: { kind: 'run', package: 'p', executable: 'e', imported_from: 'p/a.launch.py' } }))).toBe('p / e (取り込み元: p/a.launch.py)');
    expect(originText(row('/t', { origin: { kind: 'launch', package: 'p', launch_file: 'a.launch.py' } }))).toBe('p / a.launch.py');
    expect(originText(row('/t', { origin: { kind: 'external' } }))).toBe('roshanavi の外で起動');
  });

  it('labels status, mapping and lifecycle state', () => {
    expect(statusText(row('/t', { target_id: null }))).toBe('実行中 (外部)');
    expect(statusText(row('/t', { status: 'crashed', exit_code: 3 }))).toBe('異常終了 (コード 3)');
    expect(confidenceText(row('target:x', { node: null }))).toBe('ノード未確認');
    expect(confidenceText(row('/t', { confidence: 'heuristic' }))).toBe('推定');
    expect(lifecycleStateText('inactive')).toBe('停止中 (inactive)');
    expect(lifecycleStateText(null)).toBe('状態を取得できません');
    expect(lifecycleStateText('weird')).toBe('weird');
  });

  it('explains why a checkbox is disabled, with the import hint', () => {
    expect(disabledReason(row('/t'))).toBeNull();
    expect(disabledReason(row('/x', { control: 'none', reason: 'external' }))).toContain('起動セット (launch ファイル) を取り込むと');
    expect(disabledReason(row('/x', { control: 'none', reason: 'invalid', problem: 'gone' }))).toContain('gone');
  });
});
