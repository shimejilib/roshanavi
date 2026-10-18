import { describe, expect, it } from 'vitest';
import type { ImportNode, ImportPlan } from '../api/nodeListTypes';
import {
  changedArgs, commitRequest, defaultSelection, importBlocker, initialArgValues, nodeFacts, nodeTitle, problemText, reasonText,
  sourceFromForm, warningText,
} from './importModel';

function node(index: number, over: Partial<ImportNode> = {}): ImportNode {
  return {
    index, fq_name: `/r1/n${index}`, lifecycle: false, file: null,
    spec: { id: `n${index}`, kind: 'run', package: 'demo_nodes_cpp', executable: 'talker', params: { rate: 5 }, remaps: { chatter: '/c' } },
    file_params: {}, param_files: [], warnings: [], importable: true, problem: null, duplicate_of: null, ...over,
  };
}

const plan = (over: Partial<ImportPlan> = {}): ImportPlan => ({
  preview_id: 'a'.repeat(32), file: '/x.launch.py', origin: 'pkg/x.launch.py', args: {},
  arguments: [{ name: 'robot', default: 'r1', description: '', choices: null, conditional: false },
    { name: 'rate', default: null, description: '', choices: null, conditional: false }],
  missing_args: [], nodes: [node(0), node(1, { importable: false, problem: { code: 'unknown_executable', message: 'x' } }), node(2, { duplicate_of: 'n2' })],
  blocked: [], skipped: [], warnings: [], whole: null, whole_reason: 'not_in_package', ...over,
});

describe('import model', () => {
  it('builds the source from the form', () => {
    expect(sourceFromForm({ kind: 'package', package: 'p', launchFile: '', path: '' })).toBeNull();
    expect(sourceFromForm({ kind: 'package', package: 'p', launchFile: 'a.launch.py', path: '' })).toEqual({ kind: 'package', package: 'p', launch_file: 'a.launch.py' });
    expect(sourceFromForm({ kind: 'path', package: '', launchFile: '', path: ' src/a.launch.py ' })).toEqual({ kind: 'path', path: 'src/a.launch.py' });
  });

  it('pre-fills argument defaults and sends only changed values', () => {
    const p = plan();
    const values = initialArgValues(p.arguments, { rate: '5' });
    expect(values).toEqual({ robot: 'r1', rate: '5' });
    expect(changedArgs(p.arguments, values)).toEqual({ rate: '5' });
    expect(changedArgs(p.arguments, { robot: 'r2', rate: '' })).toEqual({ robot: 'r2' });
  });

  it('selects importable, non-duplicate nodes by default', () => {
    expect([...defaultSelection(plan())]).toEqual([0]);
  });

  it('describes nodes, problems and reasons in plain language', () => {
    const n = node(0, { file_params: { ids: [1] }, lifecycle: true, spec: { ...node(0).spec, args: ['--x'] } });
    expect(nodeTitle(node(0, { fq_name: null }))).toBe('(名前なし) demo_nodes_cpp/talker');
    expect(nodeFacts(n)).toEqual(['demo_nodes_cpp / talker', '設定値 (パラメータ) 1 個', '設定値のファイル (パラメータファイル) に書き出す値 1 個', '名前の付け替え (リマップ) chatter → /c', '引数 --x', 'lifecycle ノード']);
    expect(problemText(plan().nodes[1] as ImportNode)).toContain('そのパッケージにその実行ファイルがありません');
    expect(problemText(plan().nodes[2] as ImportNode)).toContain('すでに起動リストにあります');
    expect(reasonText('composable_container')).toContain('composable container');
    expect(reasonText('mystery')).toBe('分解できません (mystery)');
    expect(warningText('opaque_function_ran')).toContain('OpaqueFunction');
  });

  it('builds the commit request and explains what blocks it', () => {
    const p = plan();
    expect(commitRequest(p, 'nodes', new Set([0, 1]), 'mine')).toEqual({ preview_id: p.preview_id, mode: 'nodes', indices: [0], role: 'mine', autostart: false });
    expect(commitRequest(p, 'whole', new Set([0]), 'mine').indices).toEqual([]);
    expect(importBlocker(p, 'nodes', new Set([0]))).toBeNull();
    expect(importBlocker(p, 'nodes', new Set())).toBe('取り込むノードを選んでください');
    expect(importBlocker(p, 'whole', new Set())).toContain('パッケージの起動セット (launch ファイル) ではない');
    expect(importBlocker(plan({ missing_args: ['rate'] }), 'nodes', new Set([0]))).toContain('rate');
    expect(importBlocker(plan({ whole: { kind: 'launch' } }), 'whole', new Set())).toBeNull();
  });
});
