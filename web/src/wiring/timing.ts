// 呼ばれ方の表示: when the code behind a node's ports runs (pure; docs/design/wiring.md §2).
// Shown in the create dialogs and in the ports' tooltips.

import { t } from '../i18n';
import type { Timing } from './ports';

function rate(hz: number | null): string {
  return hz == null ? '?' : String(Number(hz.toFixed(3)));
}

/** One sentence: 「この入力が届くたびに呼ばれます」 / 「10 Hz で呼ばれます」 … */
export function timingText(timing: Timing): string {
  const { owner, mode } = timing;
  if (owner === 'dummy') {
    if (mode === 'once') return t('wiring.timing.dummyOnce');
    if (mode === 'media') return t('wiring.timing.dummyMedia');
    if (mode === 'stream') return t('wiring.timing.dummyStream', { hz: rate(timing.rateHz) });
    return t('wiring.timing.dummyPeriodic', { hz: rate(timing.rateHz) });
  }
  if (owner === 'transform') {
    if (mode === 'relay') return t('wiring.timing.relay');
    if (mode === 'map') return t('wiring.timing.transform');
  }
  if (mode === 'periodic') return t('wiring.timing.periodic', { hz: rate(timing.rateHz) });
  if (mode === 'multi_input') return multiText(timing);
  return t('wiring.timing.onMessage');
}

function multiText(timing: Timing): string {
  if (timing.trigger === 'any' || !timing.inputs.includes(timing.trigger)) return t('wiring.timing.multiAny');
  const others = timing.inputs.filter((name) => name !== timing.trigger).join(t('wiring.timing.and'));
  return t('wiring.timing.multiOne', { trigger: timing.trigger, others });
}

/** The second line under the sentence (what waits for what). '' when there is nothing to add. */
export function timingDetail(timing: Timing): string {
  if (timing.mode === 'multi_input') return t('wiring.timing.multiWait');
  if (timing.mode === 'periodic' && timing.owner !== 'dummy') return t('wiring.timing.periodicArgs');
  return '';
}

/** The diagram rows: each input with whether its arrival calls the code. */
export interface TimingRow {
  name: string;
  triggers: boolean;
}

export function timingRows(timing: Timing): TimingRow[] {
  if (timing.mode === 'periodic' || timing.owner === 'dummy') return [];
  const any = timing.trigger === 'any' || !timing.inputs.includes(timing.trigger);
  return timing.inputs.map((name) => ({ name, triggers: any || name === timing.trigger }));
}

/** The timing of a dialog's form (function, or one bound method of a class): `inputs` are the
 *  argument names and their topics; `trigger` is the spec's value ('any' or an input topic). */
export function formTiming(owner: 'function' | 'class', mode: Timing['mode'], rateHz: string, inputs: readonly { name: string; topic: string }[], trigger: string): Timing {
  const hz = Number(rateHz);
  const named = inputs.find((x) => x.topic && x.topic === trigger)?.name ?? 'any';
  return { owner, mode, rateHz: Number.isFinite(hz) && hz > 0 ? hz : null, trigger: named, inputs: inputs.map((x) => x.name) };
}

/** What can call the code when there are several inputs: any of them, or one (wired) input. */
export function triggerChoices(inputs: readonly { name: string; topic: string }[]): { value: string; label: string; disabled: boolean }[] {
  return [
    { value: 'any', label: t('wiring.timing.triggerAny'), disabled: false },
    ...inputs.map((x) => ({ value: x.topic || `#${x.name}`, label: x.name, disabled: !x.topic })),
  ];
}
