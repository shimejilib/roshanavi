import { describe, expect, it } from 'vitest';
import type { GraphNode, Job, Target, TrafficEntry } from '../api/types';
import { menuItems, menuRole, menuTitle, type MenuContext } from './menuModel';

const target = (id: string, kind: Target['kind'], pkg = 'my_pkg', status: Target['status'] = 'running'): Target => ({
  id, kind, role: kind === 'dummy' ? 'dummy' : 'mine',
  spec: kind === 'dummy' ? { id, name: id, topic: '/t', type: 'std_msgs/msg/String', mode: 'periodic' } : { id, kind: 'run', package: pkg, executable: 'e' },
  status, exit_code: null, problem: null, pid: 1, pids: [1], command: null, started_at: 0, uptime_sec: 1, restart_count: 0, pending_restart: false,
});
const node = (id: string, patch: Partial<GraphNode> = {}): GraphNode => ({ id, name: id.slice(1), namespace: '/', role: 'other', ...patch });
const ctx = (patch: Partial<MenuContext> = {}): MenuContext => ({ targets: [], jobs: [], buildable: new Set(), ...patch });
const actions = (items: ReturnType<typeof menuItems>) => items.map((i) => i.action);
const enabled = (items: ReturnType<typeof menuItems>, action: string) => items.find((i) => i.action === action)?.enabled;

describe('map menu by node role', () => {
  it('classifies roles', () => {
    const targets = [target('mine', 'run'), target('in', 'dummy')];
    expect(menuRole(node('/a', { target_id: 'mine' }), targets)).toBe('owned');
    expect(menuRole(node('/b', { target_id: 'in' }), targets)).toBe('dummy');
    expect(menuRole(node('dummy:1', { job_id: '1' }), targets)).toBe('job');
    expect(menuRole(node('/x'), targets)).toBe('external');
    expect(menuRole(node('/x', { target_id: 'gone' }), targets)).toBe('external');
  });

  it('offers full control for my nodes; build only for workspace packages', () => {
    const own = node('/a', { role: 'mine', target_id: 'mine' });
    const items = menuItems({ kind: 'node', nodeId: '/a' }, ctx({ node: own, targets: [target('mine', 'run', 'my_pkg')], buildable: new Set(['my_pkg']) }));
    expect(actions(items)).toEqual(['stop', 'restart', 'logs', 'editTarget', 'buildRestart', 'params', 'isolate']);
    expect(enabled(items, 'buildRestart')).toBe(true);
    const sys = menuItems({ kind: 'node', nodeId: '/a' }, ctx({ node: own, targets: [target('mine', 'run', 'demo_nodes_cpp')] }));
    const build = sys.find((i) => i.action === 'buildRestart');
    expect(build?.enabled).toBe(false);
    expect(build?.reason).toContain('ワークスペース');
  });

  it('offers start for a stopped target', () => {
    const items = menuItems({ kind: 'node', nodeId: '/a' }, ctx({ node: node('/a', { target_id: 'mine' }), targets: [target('mine', 'run', 'p', 'stopped')] }));
    expect(actions(items)[0]).toBe('start');
  });

  it('gives persistent dummies pause / resume / edit / export', () => {
    const items = menuItems({ kind: 'node', nodeId: '/d' }, ctx({ node: node('/d', { role: 'dummy', target_id: 'in' }), targets: [target('in', 'dummy')] }));
    expect(actions(items)).toEqual(['stop', 'restart', 'pause', 'resume', 'editDummy', 'exportLaunch', 'logs', 'params', 'isolate']);
    expect(items.every((i) => i.enabled)).toBe(true);
  });

  it('gives transform nodes edit / export but no pause and no build', () => {
    const tf: Target = {
      ...target('tf', 'run'), kind: 'transform', role: 'transform',
      spec: { id: 'tf', name: 'tf', mode: 'map', inputs: [{ topic: '/a', type: 'std_msgs/msg/String' }], output: { topic: '/b' } },
    };
    expect(menuRole(node('/tf', { target_id: 'tf' }), [tf])).toBe('transform');
    const items = menuItems({ kind: 'node', nodeId: '/tf' }, ctx({ node: node('/tf', { role: 'transform', target_id: 'tf' }), targets: [tf] }));
    expect(actions(items)).toEqual(['stop', 'restart', 'editTransform', 'exportLaunch', 'logs', 'params', 'isolate']);
  });

  it('gives function nodes their own edit item', () => {
    const fn: Target = {
      ...target('fn', 'run'), kind: 'function', role: 'function',
      spec: { id: 'fn', name: 'fn', module: 'p.logic', function: 'shout', call: 'on_message', inputs: [{ topic: '/a', kind: 'string' }], output: { topic: '/b', kind: 'string' } },
    };
    expect(menuRole(node('/fn', { target_id: 'fn' }), [fn])).toBe('function');
    const items = menuItems({ kind: 'node', nodeId: '/fn' }, ctx({ node: node('/fn', { role: 'function', target_id: 'fn' }), targets: [fn] }));
    expect(actions(items)).toEqual(['stop', 'restart', 'editFunction', 'exportLaunch', 'logs', 'params', 'isolate']);
    expect(items.find((i) => i.action === 'editFunction')?.label).toBe('関数ノードの設定を変更');
  });

  it('lets inject jobs pause but not be edited', () => {
    const job = { id: '1', state: 'running', pausable: true, paused: false } as Job;
    const items = menuItems({ kind: 'node', nodeId: 'dummy:1' }, ctx({ node: node('dummy:1', { job_id: '1', role: 'dummy' }), jobs: [job] }));
    expect(actions(items)).toEqual(['stop', 'pause', 'editDummy', 'exportLaunch', 'isolate']);
    expect(enabled(items, 'pause')).toBe(true);
    expect(enabled(items, 'editDummy')).toBe(false);
    const paused = menuItems({ kind: 'node', nodeId: 'dummy:1' }, ctx({ node: node('dummy:1', { job_id: '1' }), jobs: [{ ...job, paused: true }] }));
    expect(actions(paused)).toContain('resume');
    const once = menuItems({ kind: 'node', nodeId: 'dummy:1' }, ctx({ node: node('dummy:1', { job_id: '1' }), jobs: [{ ...job, pausable: false }] }));
    expect(enabled(once, 'pause')).toBe(false);
  });

  it('keeps external nodes read-only (stop disabled with a reason)', () => {
    const items = menuItems({ kind: 'node', nodeId: '/ext' }, ctx({ node: node('/ext') }));
    expect(actions(items)).toEqual(['stop', 'params', 'isolate', 'details']);
    expect(enabled(items, 'stop')).toBe(false);
    expect(items[0]?.reason).toContain('roshanavi が起動したノードではない');
  });
});

describe('map menu for topics, edges and the blank area', () => {
  it('topic menu follows monitoring state and type', () => {
    const entry = { monitored: true } as TrafficEntry;
    const items = menuItems({ kind: 'topic', topic: '/t' }, ctx({ traffic: entry, topicTypes: ['std_msgs/msg/String'] }));
    expect(actions(items)).toEqual(['view', 'tryInject', 'createInput', 'createTransform', 'record', 'monitorOff', 'typeDef', 'flowOnly']);
    expect(items.find((i) => i.action === 'createTransform')?.label).toBe('このトピックを受けて変換するノードを作る');
    const heavy = menuItems({ kind: 'topic', topic: '/img' }, ctx({ traffic: { monitored: false } as TrafficEntry, topicTypes: ['a/msg/A', 'b/msg/B'] }));
    expect(actions(heavy)).toContain('monitorOn');
    expect(enabled(heavy, 'typeDef')).toBe(false);
  });

  it('edge and blank menus', () => {
    expect(actions(menuItems({ kind: 'edge', topic: '/t', node: '/n', dir: 'sub' }, ctx()))).toEqual(['qosDetails', 'whyNotDelivered']);
    expect(actions(menuItems({ kind: 'blank' }, ctx()))).toEqual(['addTopic', 'launchNode', 'relayout', 'fit']);
  });

  it('titles', () => {
    expect(menuTitle({ kind: 'edge', topic: '/t', node: '/n', dir: 'pub' })).toBe('/n → /t');
    expect(menuTitle({ kind: 'blank' })).toBe('地図');
  });
});

describe('lifecycle item', () => {
  it('is offered only for lifecycle nodes, external ones included', () => {
    const lc = { id: '/lc', name: 'lc', namespace: '/', role: 'other' as const, lifecycle: true };
    const items = menuItems({ kind: 'node', nodeId: '/lc' }, ctx({ node: lc }));
    expect(items.map((i) => i.action)).toContain('lifecycle');
    expect(items.find((i) => i.action === 'lifecycle')?.enabled).toBe(true);
    const plain = menuItems({ kind: 'node', nodeId: '/x' }, ctx({ node: { ...lc, lifecycle: false } }));
    expect(plain.map((i) => i.action)).not.toContain('lifecycle');
  });
});
