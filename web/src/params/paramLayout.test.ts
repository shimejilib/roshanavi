import { describe, expect, it } from 'vitest';
import type { ParamInfo } from '../api/nodeTypes';
import { arrangeParams, isInternalParam } from './paramLayout';

const p = (name: string): ParamInfo => ({
  name, type: 'double', value: 1, description: '', read_only: false, dynamic_typing: false,
  declared_type: 'double', additional_constraints: '', range: null,
});
const names = (list: ParamInfo[]) => list.map((x) => x.name);

describe('parameter layout', () => {
  it('recognises the settings ROS adds to every node', () => {
    expect(isInternalParam('use_sim_time')).toBe(true);
    expect(isInternalParam('start_type_description_service')).toBe(true);
    expect(isInternalParam('qos_overrides./chatter.publisher.depth')).toBe(true);
    expect(isInternalParam('qos_overrides')).toBe(false);
    expect(isInternalParam('window')).toBe(false);
  });

  it('orders a class node by its __init__ signature, not alphabetically', () => {
    const params = ['alpha', 'use_sim_time', 'zeta', 'mid', 'start_type_description_service'].map(p);
    const { main, internal } = arrangeParams(params, ['zeta', 'mid', 'alpha']);
    expect(names(main)).toEqual(['zeta', 'mid', 'alpha']);
    expect(names(internal)).toEqual(['start_type_description_service', 'use_sim_time']);
  });

  it('puts settings missing from the signature after it, alphabetically', () => {
    const { main } = arrangeParams(['b', 'x', 'a', 'w'].map(p), ['b']);
    expect(names(main)).toEqual(['b', 'a', 'w', 'x']);
  });

  it('falls back to alphabetical for other nodes (no order, or an empty one)', () => {
    const params = ['rate', 'label', 'fixed'].map(p);
    expect(names(arrangeParams(params).main)).toEqual(['fixed', 'label', 'rate']);
    expect(names(arrangeParams(params, null).main)).toEqual(['fixed', 'label', 'rate']);
    expect(names(arrangeParams(params, []).main)).toEqual(['fixed', 'label', 'rate']);
  });

  it('folds qos_overrides.* and keeps a node with only internal settings valid', () => {
    const { main, internal } = arrangeParams(['qos_overrides./a.publisher.depth', 'use_sim_time'].map(p));
    expect(main).toEqual([]);
    expect(names(internal)).toEqual(['qos_overrides./a.publisher.depth', 'use_sim_time']);
  });

  it('does not modify its input', () => {
    const params = ['b', 'a'].map(p);
    arrangeParams(params);
    expect(names(params)).toEqual(['b', 'a']);
  });
});
