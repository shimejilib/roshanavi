import { describe, expect, it } from 'vitest';
import type { TakeoverStatus } from '../api/takeoverTypes';
import { banners, changedText, entryText, itemText, NO_DISMISS } from './model';

const report = {
  mode: 'node' as const, notes: [], separate: 3, suggest_whole: true, rest: [{ code: 'timer', detail: 'TimerAction' }],
  carried: [{ code: 'env', nodes: ['/a'], detail: 'TK_COLOR' }],
  lost: [{ code: 'required', nodes: ['/b'], detail: '' }, { code: 'events', nodes: [], detail: '' }],
};
const status: TakeoverStatus = {
  active: true, state: 'ready', package: 'tk', launch_file: 'x.launch.py', args: {}, mode: 'node', mine: [],
  error: null, report, pending: null, targets: ['a'], watched: 2,
};

describe('takeover banners', () => {
  it('shows leftovers first, then the pending re-import and the lost-behaviour hint', () => {
    const pending = { preview_id: 'p1', reason: 'file_changed' as const, files: [], added: [], removed: [], changed: [], unchanged: [], report };
    expect(banners({ ...status, pending }, { count: 2, processes: [] }, NO_DISMISS)).toEqual(['leftovers', 'pending', 'lost']);
    expect(banners({ ...status, pending }, { count: 0, processes: [] }, { ...NO_DISMISS, pending: 'p1', lost: true })).toEqual([]);
    expect(banners({ ...status, state: 'error', error: { code: 'x', message: 'm' } }, null, NO_DISMISS)).toEqual(['error']);
    expect(banners({ ...status, active: false }, null, NO_DISMISS)).toEqual([]);
    expect(banners(null, { count: 1, processes: [] }, { ...NO_DISMISS, leftovers: true })).toEqual([]);
  });

  it('explains carried and lost behaviour in plain words', () => {
    expect(itemText('carried', report.carried[0]!)).toContain('環境変数を、ノードの起動設定に引き継ぎました: TK_COLOR (対象: /a)');
    expect(itemText('lost', report.lost[0]!)).toContain('起動セット (launch ファイル) 全体を止める');
    expect(itemText('lost', { code: 'brand_new' })).toContain('brand_new');
  });

  it('labels diff entries', () => {
    expect(entryText({ id: 'r', label: 'x.launch.py', kind: 'rest' })).toContain('x.launch.py の残りの部分');
    expect(changedText({ id: 'a', label: '/a', kind: 'node', fields: ['params', 'env'] })).toBe('/a: 設定値 (パラメータ)・環境変数');
  });
});
