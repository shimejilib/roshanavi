// Shared fixtures of the wiring unit tests (not a test file itself).

import type { ClassSpec } from '../api/classTypes';
import type { FunctionSpec } from '../api/functionTypes';
import type { TransformSpec } from '../api/transformTypes';
import type { DummySpec, GraphSnapshot, Target } from '../api/types';
import type { KindCatalog } from '../datakind/kinds';

/** The backend catalog (GET /api/data-kinds), trimmed to what the tests use. */
export const CATALOG: KindCatalog = {
  kinds: [
    { id: 'string', type: 'std_msgs/msg/String', available: true, python: 'str' },
    { id: 'float', type: 'std_msgs/msg/Float64', available: true, python: 'float' },
    { id: 'int', type: 'std_msgs/msg/Int64', available: true, python: 'int' },
    { id: 'bool', type: 'std_msgs/msg/Bool', available: true, python: 'bool' },
    { id: 'json', type: 'std_msgs/msg/String', available: true, python: 'dict' },
    { id: 'image', type: 'sensor_msgs/msg/Image', available: true, python: 'numpy' },
  ],
  type_kinds: {
    'std_msgs/msg/String': 'string',
    'example_interfaces/msg/String': 'string',
    'std_msgs/msg/Float64': 'float',
    'std_msgs/msg/Float32': 'float',
    'std_msgs/msg/Int64': 'int',
    'std_msgs/msg/Int32': 'int',
    'std_msgs/msg/Bool': 'bool',
    'sensor_msgs/msg/Image': 'image',
  },
  common_types: [],
};

export function target(kind: Target['kind'], spec: Target['spec'], status: Target['status'] = 'running'): Target {
  return {
    id: (spec as { id: string }).id, kind, role: kind === 'class' ? 'function' : (kind as Target['role']), spec, status,
    exit_code: null, problem: null, pid: 1, pids: [1], command: null, started_at: 0, uptime_sec: 1, restart_count: 0, pending_restart: false,
  };
}

export const SHOUT: FunctionSpec = {
  id: 'shout', name: 'shout', module: 'my_logic.logic', function: 'shout', call: 'on_message',
  inputs: [{ topic: '', kind: 'string' }], output: { topic: '', kind: 'string' },
};

export const ADD: FunctionSpec = {
  id: 'add', name: 'add', module: 'my_logic.logic', function: 'add', call: 'multi_input', trigger: '/a',
  inputs: [{ topic: '/a', kind: 'float' }, { topic: '/b', kind: 'float' }], output: { topic: '/sum', kind: 'float' },
};

export const AVG: ClassSpec = {
  id: 'avg', name: 'avg', module: 'ex.stateful', class_name: 'MovingAverage', params: {},
  methods: [{ method: 'process', call: 'on_message', inputs: [{ topic: '/number', kind: 'float' }], outputs: [{ topic: '/average', kind: 'float' }] }],
  actions: ['reset'],
};

export const RELAY: TransformSpec = {
  id: 'relay', name: 'relay', inputs: [{ topic: '/chatter', type: 'std_msgs/msg/String' }], output: { topic: '/copy' }, mode: 'relay',
};

export const HELLO: DummySpec = {
  id: 'hello', name: 'hello', topic: '/hello', type: 'std_msgs/msg/String', kind: 'string', mode: 'periodic', rate_hz: 1,
};

/** Graph with the nodes above running (mapped by target_id) and a few topics. */
export function graph(extraTopics: GraphSnapshot['topics'] = []): GraphSnapshot {
  return {
    nodes: [
      { id: '/shout', name: 'shout', namespace: '/', role: 'function', target_id: 'shout' },
      { id: '/add', name: 'add', namespace: '/', role: 'function', target_id: 'add' },
      { id: '/avg', name: 'avg', namespace: '/', role: 'function', target_id: 'avg' },
      { id: '/relay', name: 'relay', namespace: '/', role: 'transform', target_id: 'relay' },
      { id: '/hello', name: 'hello', namespace: '/', role: 'dummy', target_id: 'hello' },
      { id: '/talker', name: 'talker', namespace: '/', role: 'other' },
    ],
    topics: [
      { name: '/chatter', types: ['example_interfaces/msg/String'] },
      { name: '/image', types: ['sensor_msgs/msg/Image'] },
      { name: '/count', types: ['std_msgs/msg/Int32'] },
      { name: '/ratio', types: ['std_msgs/msg/Float64'] },
      { name: '/a', types: ['std_msgs/msg/Float64'] },
      { name: '/b', types: ['std_msgs/msg/Float64'] },
      { name: '/sum', types: ['std_msgs/msg/Float64'] },
      ...extraTopics,
    ],
    edges: [],
    diagnostics: [],
    hash: 'h',
  };
}

export function targets(): Target[] {
  return [target('function', SHOUT), target('function', ADD), target('class', AVG), target('transform', RELAY), target('dummy', HELLO),
    target('run', { id: 'talker_t', kind: 'run', package: 'demo_nodes_cpp', executable: 'talker' })];
}

export const ARGS = (tg: Target, group: number): string[] | undefined =>
  tg.id === 'shout' ? ['text'] : tg.id === 'add' ? ['a', 'b'] : tg.id === 'avg' && group === 0 ? ['x'] : undefined;
