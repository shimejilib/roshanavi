import { describe, expect, it } from 'vitest';
import { detectedPort } from './DataKindField';
import { readAdvanced, writeAdvanced } from './advancedMode';
import { describeType, filterGroups, kindOfType, portFromKind, portFromType, portOfSpec, shortType, type KindCatalog } from './kinds';

const catalog: KindCatalog = {
  kinds: [
    { id: 'string', type: 'std_msgs/msg/String', available: true, python: 'str' },
    { id: 'float', type: 'std_msgs/msg/Float64', available: true, python: 'float' },
    { id: 'json', type: 'std_msgs/msg/String', available: true, python: 'dict' },
    { id: 'audio', type: 'std_msgs/msg/Int16MultiArray', available: true, python: 'ndarray' },
  ],
  type_kinds: { 'std_msgs/msg/String': 'string', 'std_msgs/msg/Float64': 'float', 'std_msgs/msg/Float32': 'float' },
  common_types: ['std_msgs/msg/String'],
};

describe('data kinds', () => {
  it('labels existing types with the kind and the short ROS name', () => {
    expect(describeType('std_msgs/msg/String', catalog)).toBe('文字列 (std_msgs/String)');
    expect(describeType('std_msgs/Float32', catalog)).toBe('数値 (小数) (std_msgs/Float32)');
    expect(describeType('geometry_msgs/msg/Twist', catalog)).toBe('専用の型: geometry_msgs/Twist');
    expect(shortType('a/msg/B')).toBe('a/B');
    expect(kindOfType('std_msgs/Float64', catalog)).toBe('float');
  });

  it('turns a kind into its server-chosen type and back', () => {
    expect(portFromKind('json', catalog)).toEqual({ kind: 'json', type: 'std_msgs/msg/String' });
    expect(portFromKind('audio', catalog).type).toBe('std_msgs/msg/Int16MultiArray');
    expect(portFromKind('', catalog)).toEqual({ kind: '', type: '' });
    expect(portFromType('geometry_msgs/Twist', catalog)).toEqual({ kind: 'message', type: 'geometry_msgs/msg/Twist' });
    expect(portOfSpec('float', 'std_msgs/msg/Float32', catalog)).toEqual({ kind: 'float', type: 'std_msgs/msg/Float32' });
    expect(portOfSpec(undefined, 'std_msgs/msg/String', catalog)).toEqual({ kind: 'string', type: 'std_msgs/msg/String' });
    expect(portOfSpec('string', undefined, catalog)).toEqual({ kind: 'string', type: 'std_msgs/msg/String' });
  });

  it('fixes the port to an existing topic type, keeping a JSON choice on a String topic', () => {
    expect(detectedPort([], { kind: 'float', type: '' }, catalog)).toBeNull();
    expect(detectedPort(['std_msgs/msg/String'], { kind: 'float', type: 'std_msgs/msg/Float64' }, catalog))
      .toEqual({ kind: 'string', type: 'std_msgs/msg/String' });
    expect(detectedPort(['std_msgs/msg/String'], { kind: 'json', type: '' }, catalog)?.kind).toBe('json');
    expect(detectedPort(['a/msg/X', 'std_msgs/msg/Float32'], { kind: 'float', type: 'std_msgs/msg/Float32' }, catalog))
      .toEqual({ kind: 'float', type: 'std_msgs/msg/Float32' });
  });

  it('filters the 詳細設定 groups by search without reordering them', () => {
    const groups = [
      { id: 'common' as const, types: ['std_msgs/msg/String', 'geometry_msgs/msg/Twist'] },
      { id: 'workspace' as const, types: ['my_pkg/msg/Thing'] },
      { id: 'package' as const, package: 'geometry_msgs', types: ['geometry_msgs/msg/Accel', 'geometry_msgs/msg/TwistStamped'] },
    ];
    expect(filterGroups(groups, 'twist').map((g) => [g.id, g.types])).toEqual([
      ['common', ['geometry_msgs/msg/Twist']],
      ['package', ['geometry_msgs/msg/TwistStamped']],
    ]);
    expect(filterGroups(groups, '')).toEqual(groups);
    expect(filterGroups(groups, 'nothing')).toEqual([]);
  });

  it('remembers 詳細設定モード and survives storage that throws', () => {
    const store = new Map<string, string>();
    const storage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v) };
    expect(readAdvanced(storage)).toBe(false);
    writeAdvanced(true, storage);
    expect(readAdvanced(storage)).toBe(true);
    const broken = { getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); } };
    expect(readAdvanced(broken)).toBe(false);
    expect(() => writeAdvanced(true, broken)).not.toThrow();
    expect(readAdvanced(null)).toBe(false);
  });
});
