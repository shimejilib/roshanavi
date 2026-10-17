// Small readers shared by the tour definitions (pure; they only look at the TourContext).

import type { FunctionSpec } from '../../api/functionTypes';
import type { DummySpec } from '../../api/types';
import { normalizeTopic } from '../../input/inputForm';
import type { TourContext } from '../types';

export const sel = (name: string): string => `[data-tour="${name}"]`;

export const domValue = (ctx: TourContext, name: string): string => ctx.dom.all(sel(name))[0]?.value ?? '';
export const domChecked = (ctx: TourContext, name: string): boolean => ctx.dom.all(sel(name))[0]?.checked ?? false;
export const domText = (ctx: TourContext, name: string): string => ctx.dom.all(sel(name))[0]?.text ?? '';
export const domExists = (ctx: TourContext, name: string): boolean => ctx.dom.all(sel(name)).length > 0;

/** The topic typed in a field, written the way the dialogs read it ("hello" == "/hello"). */
export const typedTopic = (ctx: TourContext, name: string): string => {
  const text = domValue(ctx, name).trim();
  return text ? normalizeTopic(text) : '';
};

export const publishersOf = (ctx: TourContext, topic: string): string[] =>
  (ctx.graph?.edges ?? []).filter((e) => e.topic === topic && e.dir === 'pub').map((e) => e.node);

export const hasQosProblem = (ctx: TourContext, topic: string): boolean =>
  (ctx.graph?.diagnostics ?? []).some((d) => d.code === 'qos_incompatible' && d.topic === topic);

export const isDialog = (ctx: TourContext, kind: string): boolean => ctx.dialog?.kind === kind;

/** Input nodes (dummy targets) that publish `topic` and did not exist before the tour. */
export function newInputsOn(ctx: TourContext, topic: string, knownIds: readonly string[]): string[] {
  return ctx.targets
    .filter((tg) => tg.kind === 'dummy' && (tg.spec as DummySpec).topic === topic && !knownIds.includes(tg.id))
    .map((tg) => tg.id);
}

/** Function nodes that publish `topic` and did not exist before the tour. */
export function newFunctionsTo(ctx: TourContext, topic: string, knownIds: readonly string[]): string[] {
  return ctx.targets
    .filter((tg) => tg.kind === 'function' && (tg.spec as FunctionSpec).output.topic === topic && !knownIds.includes(tg.id))
    .map((tg) => tg.id);
}
