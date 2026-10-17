import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import type { GraphSnapshot } from '../api/types';
import { ja } from '../i18n/messages';
import { messageKey, settle, startRun, stepOf, targetSelector } from './engine';
import { ctxOf, dummyTarget, fakeDom, functionTarget } from './testing';
import { isShouted } from './tours/functionNode';
import { TOURS, tourById } from './tours';
import type { TourContext } from './types';

const SRC = join(__dirname, '..');

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === 'tour' ? [] : sourceFiles(path);
    return /\.tsx?$/.test(name) && !/\.test\./.test(name) ? [path] : [];
  });
}

/** Every `data-tour` the screens render, as exact names or `${…}` patterns. */
function renderedNames(): { exact: Set<string>; patterns: RegExp[] } {
  const exact = new Set<string>();
  const patterns: RegExp[] = [];
  for (const file of [...sourceFiles(SRC), join(SRC, 'tour', 'TourSettings.tsx')]) {
    const text = readFileSync(file, 'utf8');
    for (const match of text.matchAll(/data-tour=(?:"([^"]+)"|\{`([^`]+)`\}|\{[^}]*'([^']+)'[^}]*\})/g)) {
      const [, quoted, template, ternary] = match;
      if (quoted) exact.add(quoted);
      if (ternary) exact.add(ternary);
      if (template) patterns.push(new RegExp(`^${template.replace(/\$\{[^}]*\}/g, '.+')}$`));
    }
  }
  return { exact, patterns };
}

const graph = (over: Partial<GraphSnapshot> = {}): GraphSnapshot =>
  ({ hash: 'h', nodes: [], topics: [], edges: [], diagnostics: [], ...over }) as GraphSnapshot;
const pub = (node: string, topic: string) => ({ node, topic, dir: 'pub' as const, qos: { reliability: 'reliable', durability: 'volatile', depth: 10 } });

describe('tour definitions', () => {
  it('has the five tours, each with unique step ids and a "show" step at the end', () => {
    expect(TOURS.map((t) => t.id)).toEqual(['overview', 'firstInput', 'qosFix', 'functionNode', 'scenario']);
    for (const tour of TOURS) {
      const ids = tour.steps.map((s) => s.id);
      expect(new Set(ids).size, tour.id).toBe(ids.length);
      expect(tour.steps.at(-1)?.kind, tour.id).toBe('show');
      expect(tourById(tour.id)).toBe(tour);
    }
  });

  it('has Japanese text for every step (title + body) and every tour (name + summary)', () => {
    for (const tour of TOURS) {
      expect(ja[`tour.name.${tour.id}` as keyof typeof ja], `name ${tour.id}`).toBeTruthy();
      expect(ja[`tour.summary.${tour.id}` as keyof typeof ja], `summary ${tour.id}`).toBeTruthy();
      for (const step of tour.steps) {
        for (const part of ['title', 'body'] as const) {
          expect(ja[messageKey(tour, step, part) as keyof typeof ja], messageKey(tour, step, part)).toBeTruthy();
        }
      }
    }
  });

  it('has no message that no step uses (keeps the dictionary honest)', () => {
    const used = new Set(TOURS.flatMap((t) => t.steps.flatMap((s) => (['title', 'body', 'hint'] as const).map((p) => messageKey(t, s, p)))));
    const stepKeys = Object.keys(ja).filter((k) => /^tour\.(overview|firstInput|qosFix|functionNode|scenario)\./.test(k) && !k.startsWith('tour.name') && !k.startsWith('tour.summary'));
    expect(stepKeys.filter((k) => !used.has(k))).toEqual([]);
  });

  it('only points at data-tour names that a screen renders (a UI change that drops one fails here)', () => {
    const { exact, patterns } = renderedNames();
    const ctx = ctxOf({ dom: fakeDom() });
    const missing: string[] = [];
    for (const tour of TOURS) {
      for (const step of tour.steps) {
        const probe: TourContext = { ...ctx, baseline: { targets: [], scenarios: ['x'] } };
        const selector = targetSelector(step, probe);
        if (!selector) continue;
        const names = [...selector.matchAll(/data-tour="([^"]+)"/g)].map((m) => m[1] as string);
        for (const name of names) {
          if (!exact.has(name) && !patterns.some((re) => re.test(name))) missing.push(`${tour.id}/${step.id}: ${name}`);
        }
      }
    }
    expect(missing).toEqual([]);
  });
});

describe('tour conditions', () => {
  it('firstInput: knows the topic however it is typed, and only counts input nodes made after the start', () => {
    const tour = tourById('firstInput');
    const typed = (value: string) => ctxOf({ dom: fakeDom([{ selector: '[data-tour="input-topic"]', value }]) });
    const topicStep = tour.steps.find((s) => s.id === 'topic');
    expect(topicStep?.done?.(typed('/hello'))).toBe(true);
    expect(topicStep?.done?.(typed(' hello '))).toBe(true);
    expect(topicStep?.done?.(typed('/hallo'))).toBe(false);
    const createStep = tour.steps.find((s) => s.id === 'create');
    const old = dummyTarget('old_hello', '/hello');
    expect(createStep?.done?.(ctxOf({ targets: [old], baseline: { targets: ['old_hello'], scenarios: [] } }))).toBe(false);
    expect(createStep?.done?.(ctxOf({ targets: [old, dummyTarget('dummy_hello', '/hello')], baseline: { targets: ['old_hello'], scenarios: [] } }))).toBe(true);
  });

  it('firstInput: walks from the open dialog to the end of the lesson', () => {
    const tour = tourById('firstInput');
    const run = startRun(tour, { targets: [], scenarios: [] }, []);
    const afterOpen = settle(tour, run, ctxOf({ dialog: { kind: 'createInput' } }));
    expect(stepOf(tour, afterOpen).id).toBe('kind'); // a show step waits for 次へ
    const g = graph({ edges: [pub('/dummy_hello', '/hello')] });
    const atTopic = { ...afterOpen, step: tour.steps.findIndex((s) => s.id === 'create') };
    const ctx = ctxOf({ graph: g, targets: [dummyTarget('dummy_hello', '/hello')], selection: { kind: 'node', id: '/dummy_hello' } });
    const done = settle(tour, atTopic, ctx);
    expect(stepOf(tour, done).id).toBe('topicClick');
    expect(done.fixtures).toEqual([{ kind: 'target', id: 'dummy_hello' }]);
  });

  it('qosFix: starts when the red line exists and ends when it is gone', () => {
    const tour = tourById('qosFix');
    const bad = graph({ diagnostics: [{ code: 'qos_incompatible', severity: 'error', topic: '/tour_qos', nodes: [], detail: {} }] });
    const [prepare, , , , , , save, fixed] = tour.steps;
    expect(prepare?.done?.(ctxOf({ graph: bad }))).toBe(true);
    expect(prepare?.done?.(ctxOf({ graph: graph() }))).toBe(false);
    expect(fixed?.done?.(ctxOf({ graph: bad }))).toBe(false);
    expect(fixed?.done?.(ctxOf({ graph: graph() }))).toBe(true);
    const sent = (reliability: string) => ctxOf({ targets: [dummyTarget('tour_qos_pub', '/tour_qos', { qos: { reliability } })] });
    expect(save?.done?.(sent('best_effort'))).toBe(false);
    expect(save?.done?.(sent('reliable'))).toBe(true);
  });

  it('qosFix: editing the sender is recognised only for the tour node', () => {
    const edit = tourById('qosFix').steps.find((s) => s.id === 'edit');
    expect(edit?.done?.(ctxOf({ dialog: { kind: 'createInput', dummyId: 'tour_qos_pub' } }))).toBe(true);
    expect(edit?.done?.(ctxOf({ dialog: { kind: 'createInput', dummyId: 'other' } }))).toBe(false);
    expect(edit?.done?.(ctxOf({ dialog: { kind: 'createInput' } }))).toBe(false);
  });

  it('functionNode: the demo project function node (same output topic) does not count as made by the learner', () => {
    const create = tourById('functionNode').steps.find((s) => s.id === 'create');
    const demo = functionTarget('text_shout', '/shouted');
    const base = { targets: ['text_shout'], scenarios: [] };
    expect(create?.done?.(ctxOf({ targets: [demo], baseline: base }))).toBe(false);
    expect(create?.done?.(ctxOf({ targets: [demo, functionTarget('shout', '/shouted')], baseline: base }))).toBe(true);
  });

  it('functionNode: recognises an upper-case echo', () => {
    expect(isShouted('data: HELLO WORLD: 12!')).toBe(true);
    expect(isShouted('{\n  "data": "HELLO WORLD: 12!"\n}')).toBe(true);
    expect(isShouted('{\n  "data": "Hello World: 12"\n}')).toBe(false);
    expect(isShouted('data: Hello World: 12')).toBe(false);
    expect(isShouted('')).toBe(false);
    expect(isShouted('data: 42')).toBe(false);
  });

  it('scenario: finds the scenario saved during the tour and targets its 実行 button', () => {
    const tour = tourById('scenario');
    const items = fakeDom([
      { selector: '[data-tour="scn-item"]', attrs: { 'data-scn-id': 'project:old.yaml', 'data-scn-source': 'project' } },
      { selector: '[data-tour="scn-item"]', attrs: { 'data-scn-id': 'example:state.yaml', 'data-scn-source': 'example' } },
    ]);
    const before = ctxOf({ dom: items, baseline: { targets: [], scenarios: ['project:old.yaml'] } });
    expect(tour.adopt?.(before, before.baseline)).toEqual([]);
    const withNew = fakeDom([
      { selector: '[data-tour="scn-item"]', attrs: { 'data-scn-id': 'project:old.yaml', 'data-scn-source': 'project' } },
      { selector: '[data-tour="scn-item"]', attrs: { 'data-scn-id': 'project:tour_scenario.yaml', 'data-scn-source': 'project' } },
    ]);
    const after = ctxOf({ dom: withNew, baseline: before.baseline });
    expect(tour.adopt?.(after, after.baseline)).toEqual([{ kind: 'scenario', id: 'project:tour_scenario.yaml' }]);
    const run = tour.steps.find((s) => s.id === 'run');
    expect(targetSelector(run!, after)).toBe('[data-tour="scn-run"][data-scn-id="project:tour_scenario.yaml"]');
  });

  it('scenario: counts the send as done once the recording has the inject on /tour_in', () => {
    const send = tourById('scenario').steps.find((s) => s.id === 'send');
    const op = (topic: string) => ({ seq: 1, t: 0, kind: 'op' as const, op: { kind: 'inject' as const, job_id: 'j', request: { topic } } });
    expect(send?.done?.(ctxOf({ recordEvents: [op('/other')] }))).toBe(false);
    expect(send?.done?.(ctxOf({ recordEvents: [op('/tour_in')] }))).toBe(true);
  });
});

describe('scenario tour: a result that was already on screen does not count', () => {
  const run = (id: string, status: string) => ({ run_id: id, status }) as unknown as TourContext['scenarioRun'];
  const steps = tourById('scenario').steps;
  const started = steps.find((s) => s.id === 'run');
  const passed = steps.find((s) => s.id === 'passed');

  it('waits for a run started after the tour began', () => {
    const baseline = { targets: [], scenarios: [], runId: 'old' };
    expect(started?.done?.(ctxOf({ baseline, scenarioRun: run('old', 'passed') }))).toBe(false);
    expect(started?.done?.(ctxOf({ baseline, scenarioRun: run('new', 'running') }))).toBe(true);
    expect(passed?.done?.(ctxOf({ baseline, scenarioRun: run('old', 'passed') }))).toBe(false);
    expect(passed?.done?.(ctxOf({ baseline, scenarioRun: run('new', 'running') }))).toBe(false);
    expect(passed?.done?.(ctxOf({ baseline, scenarioRun: run('new', 'passed') }))).toBe(true);
  });

  it('counts the first run when none existed before', () => {
    expect(started?.done?.(ctxOf({ baseline: { targets: [], scenarios: [], runId: null }, scenarioRun: run('first', 'running') }))).toBe(true);
    expect(started?.done?.(ctxOf({ scenarioRun: null }))).toBe(false);
  });
});
