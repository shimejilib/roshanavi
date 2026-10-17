// Test helpers for the tour unit tests (not imported by the app).

import type { RecordEvent } from '../api/scenarioTypes';
import type { Target } from '../api/types';
import type { DomEl, DomProbe, TourContext } from './types';

export interface FakeEl extends Partial<DomEl> {
  selector: string;
  attrs?: Record<string, string>;
}

export function fakeDom(elements: readonly FakeEl[] = []): DomProbe {
  return {
    all: (selector) =>
      elements
        .filter((el) => el.selector === selector || selector.startsWith(`${el.selector} `))
        .map((el) => ({ value: el.value ?? '', checked: el.checked ?? false, text: el.text ?? '', attr: (name: string) => el.attrs?.[name] ?? null })),
  };
}

export function ctxOf(over: Partial<TourContext> = {}): TourContext {
  return {
    tab: 'graph', selection: null, dialog: null, graph: null, targets: [], recordActive: false,
    recordEvents: [] as readonly RecordEvent[], scenarioRun: null, baseline: { targets: [], scenarios: [] }, dom: fakeDom(), ...over,
  };
}

export function dummyTarget(id: string, topic: string, extra: Record<string, unknown> = {}): Target {
  return { id, kind: 'dummy', role: 'dummy', status: 'running', spec: { id, name: id, topic, type: 'std_msgs/msg/String', mode: 'periodic', ...extra } } as unknown as Target;
}

export function functionTarget(id: string, outputTopic: string): Target {
  return { id, kind: 'function', role: 'function', status: 'running', spec: { id, output: { topic: outputTopic } } } as unknown as Target;
}
