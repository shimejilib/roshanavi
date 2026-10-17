import { describe, expect, it } from 'vitest';
import type { WorkspacePackage } from '../api/types';
import { buildablePackages, filterPackages } from './packages';

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
  it('puts workspace packages first, then by name', () => {
    expect(filterPackages(ALL, '').map((m) => m.pkg.name)).toEqual(['my_robot', 'a_sys', 'demo_nodes_cpp']);
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
