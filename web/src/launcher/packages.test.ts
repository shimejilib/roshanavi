import { describe, expect, it } from 'vitest';
import type { WorkspacePackage } from '../api/types';
import { buildablePackages, filterPackages, visiblePackages, workspaceConfigured } from './packages';

const pkg = (name: string, origin: 'workspace' | 'system', executables: string[] = [], launch: string[] = []): WorkspacePackage => ({
  name,
  origin,
  prefix: '/p',
  sourced: true,
  built: true,
  source_dir: origin === 'workspace' ? `/ws/src/${name}` : null,
  executables,
  launch_files: launch,
});

const ALL = [pkg('demo_nodes_cpp', 'system', ['talker', 'listener'], ['talker_listener_launch.py']), pkg('my_robot', 'workspace', ['driver']), pkg('a_sys', 'system')];

describe('package picker', () => {
  it('puts workspace packages first, then demo packages, then by name', () => {
    expect(filterPackages(ALL, '').map((m) => m.pkg.name)).toEqual(['my_robot', 'demo_nodes_cpp', 'a_sys']);
  });

  it('matches executables and launch files inside packages', () => {
    const match = filterPackages(ALL, 'TALK')[0]!;
    expect(match.pkg.name).toBe('demo_nodes_cpp');
    expect(match.executables).toEqual(['talker']);
    expect(match.launchFiles).toEqual(['talker_listener_launch.py']);
    expect(filterPackages(ALL, 'demo')[0]?.executables).toEqual(['talker', 'listener']);
    expect(filterPackages(ALL, 'zzz')).toEqual([]);
  });

  it('lists buildable packages', () => {
    expect(buildablePackages(ALL).map((p) => p.name)).toEqual(['my_robot']);
  });
});

describe('package filtering (P4.5)', () => {
  const list = [pkg('my_robot', 'workspace', ['driver']), pkg('demo_nodes_cpp', 'system', ['talker']), pkg('rclcpp_components', 'system', ['component_container']), pkg('roshanavi', 'workspace', ['server'])];

  it('shows workspace and demo packages by default, everything on request', () => {
    expect(visiblePackages(list, false).map((p) => p.name)).toEqual(['my_robot', 'demo_nodes_cpp', 'roshanavi']);
    expect(visiblePackages(list, true)).toHaveLength(4);
  });

  it('ranks demo packages right after the workspace', () => {
    expect(filterPackages(list, '').map((m) => m.pkg.name)).toEqual(['my_robot', 'roshanavi', 'demo_nodes_cpp', 'rclcpp_components']);
  });

  it('detects a workspace without the user\'s own packages', () => {
    expect(workspaceConfigured(list)).toBe(true);
    expect(workspaceConfigured(list.filter((p) => p.name !== 'my_robot'))).toBe(false);
    expect(workspaceConfigured([])).toBe(false);
  });
});
