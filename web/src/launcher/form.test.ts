import { describe, expect, it } from 'vitest';
import { buildTargetSpec, EMPTY_FORM, formFromSpec, makeTargetId, parseParamValue, type TargetForm } from './form';

const runForm = (patch: Partial<TargetForm> = {}): TargetForm => ({
  ...EMPTY_FORM,
  package: 'demo_nodes_cpp',
  executable: 'talker',
  ...patch,
});

describe('launcher form', () => {
  it('parses parameter values to their YAML type', () => {
    expect(parseParamValue('true')).toBe(true);
    expect(parseParamValue('42')).toBe(42);
    expect(parseParamValue('-1.5')).toBe(-1.5);
    expect(parseParamValue('1e3')).toBe('1e3');
    expect(parseParamValue('hello world')).toBe('hello world');
  });

  it('makes unique ids from names', () => {
    expect(makeTargetId('talker', [])).toBe('talker');
    expect(makeTargetId('talker', ['talker', 'talker-2'])).toBe('talker-3');
    expect(makeTargetId('talker_listener_launch.py', [])).toBe('talker_listener_launch');
    expect(makeTargetId('Camera Node!', [])).toBe('camera_node');
    expect(makeTargetId('_x', [])).toBe('x');
  });

  it('builds a run spec with params, remaps and role', () => {
    const result = buildTargetSpec(
      runForm({
        name: 'my_talker',
        namespace: '/robot1',
        params: [{ key: 'rate', value: '10' }, { key: '', value: '' }],
        remaps: [{ key: 'chatter', value: '/chat' }],
        args: '  --verbose  -x ',
      }),
      ['my_talker'],
    );
    expect(result).toEqual({
      ok: true,
      value: {
        id: 'my_talker-2',
        kind: 'run',
        package: 'demo_nodes_cpp',
        executable: 'talker',
        args: ['--verbose', '-x'],
        params: { rate: 10 },
        remaps: { chatter: '/chat' },
        name: 'my_talker',
        namespace: '/robot1',
        role: 'mine',
        autostart: false,
        auto_restart: false,
      },
    });
  });

  it('builds a launch spec with name:=value args', () => {
    const result = buildTargetSpec(
      { ...EMPTY_FORM, kind: 'launch', package: 'p', launchFile: 'a.launch.py', mine: false, launchArgs: [{ key: 'use_sim', value: 'true' }] },
      [],
    );
    expect(result.ok && result.value).toMatchObject({ id: 'a', kind: 'launch', launch_file: 'a.launch.py', args: ['use_sim:=true'], role: 'dependency' });
  });

  it('rejects bad names early with a plain message', () => {
    const cases: Partial<TargetForm>[] = [
      { name: 'bad name' },
      { namespace: 'a b' },
      { params: [{ key: 'a;b', value: '1' }] },
      { params: [{ key: 'ok', value: 'line\nbreak' }] },
      { remaps: [{ key: '__node', value: 'x' }] },
      { remaps: [{ key: 'in', value: 'has space' }] },
      { executable: '' },
      { package: '' },
    ];
    for (const patch of cases) {
      const result = buildTargetSpec(runForm(patch), []);
      expect(result.ok, JSON.stringify(patch)).toBe(false);
    }
  });

  it('round-trips through formFromSpec', () => {
    const built = buildTargetSpec(runForm({ name: 'n', params: [{ key: 'a', value: 'x' }], autostart: true }), []);
    if (!built.ok) throw new Error(built.error);
    const again = buildTargetSpec(formFromSpec(built.value), []);
    expect(again).toEqual(built);
    const launch = { id: 'l', kind: 'launch' as const, package: 'p', launch_file: 'x.launch.py', args: ['a:=b:=c'] };
    expect(formFromSpec(launch).launchArgs).toEqual([{ key: 'a', value: 'b:=c' }]);
  });
});
