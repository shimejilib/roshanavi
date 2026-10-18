// Wiring without a mouse (pure; docs/design/wiring.md): select a port (Tab + Enter on the map) ->
// choose what to connect it to from a list (arrow keys) -> confirm (Enter). The same options
// the drag shows: incompatible channels are listed but disabled, with the reason.

import type { GraphTopic, Target } from '../api/types';
import type { KindCatalog } from '../datakind/kinds';
import { t } from '../i18n';
import { termPair } from '../i18n/glossary';
import type { WireStatus } from './compat';
import { checkTypes, planConnect } from './edit';
import { suggestTopic, type NodePorts, type Port } from './ports';

export type WireChoice = { kind: 'topic'; topic: string } | { kind: 'new'; topic: string } | { kind: 'disconnect' };

export interface WireOption {
  id: string;
  choice: WireChoice;
  label: string;
  /** Reason (disabled), conversion note, or what happens. */
  detail: string;
  status: WireStatus;
  disabled: boolean;
  /** The port is wired to this channel now. */
  current: boolean;
}

/** Every choice for port `p`: new channel (outputs), the channels on the map, take the wire off. */
export function wireOptions(np: NodePorts, p: Port, target: Target, topics: readonly GraphTopic[], catalog: KindCatalog): WireOption[] {
  const options: WireOption[] = [];
  if (p.ref.side === 'out') {
    const name = suggestTopic(np, p, new Set(topics.map((tp) => tp.name)));
    options.push({ id: 'new', choice: { kind: 'new', topic: name }, label: t('wiring.option.new', { channel: termPair('topic') }), detail: name, status: 'same', disabled: false, current: false });
  }
  const listed = topics.map((tp): WireOption => {
    const current = tp.name === p.topic;
    const plan = current ? null : planConnect(np, p, target, tp.name, tp.types, catalog);
    const status: WireStatus = plan && !plan.ok ? 'refuse' : checkTypes(p, tp.types, catalog).verdict[0];
    const detail = current ? t('wiring.option.current') : plan && !plan.ok ? plan.reason : plan?.note ?? '';
    return { id: `topic:${tp.name}`, choice: { kind: 'topic', topic: tp.name }, label: tp.name, detail, status, disabled: current || status === 'refuse', current };
  });
  const rank = (o: WireOption) => (o.current ? 0 : o.disabled ? 2 : 1);
  options.push(...[...listed].sort((a, b) => rank(a) - rank(b) || a.label.localeCompare(b.label)));
  if (p.topic && p.canUnwire) {
    options.push({ id: 'disconnect', choice: { kind: 'disconnect' }, label: t('wiring.option.disconnect'), detail: p.topic, status: 'same', disabled: false, current: false });
  }
  return options;
}

export interface FlowState {
  step: 'choose' | 'confirm';
  /** Option with the keyboard focus (choose step). */
  focus: number;
  /** Option chosen for the confirm step. */
  selected: number | null;
  /** Name of a new channel (editable in the confirm step). */
  newName: string;
}

export type FlowKey = 'ArrowDown' | 'ArrowUp' | 'Home' | 'End' | 'Enter' | ' ' | 'Escape';
export type FlowEvent = { type: 'key'; key: FlowKey } | { type: 'pick'; index: number } | { type: 'rename'; name: string };
export type FlowResult = FlowState | { done: WireChoice } | 'cancel';

export function initialFlow(options: readonly WireOption[]): FlowState {
  const first = options.findIndex((o) => !o.disabled);
  const fresh = options.find((o) => o.choice.kind === 'new');
  return { step: 'choose', focus: Math.max(0, first), selected: null, newName: fresh?.choice.kind === 'new' ? fresh.choice.topic : '' };
}

function move(options: readonly WireOption[], from: number, step: 1 | -1): number {
  for (let i = from + step; i >= 0 && i < options.length; i += step) if (!options[i]?.disabled) return i;
  return from;
}

function edge(options: readonly WireOption[], last: boolean): number {
  const order = last ? [...options.keys()].reverse() : [...options.keys()];
  return order.find((i) => !options[i]?.disabled) ?? 0;
}

function choiceOf(option: WireOption, newName: string): WireChoice {
  return option.choice.kind === 'new' ? { kind: 'new', topic: newName.trim() } : option.choice;
}

/** One key / click in the wiring list. Disabled options can be read but never chosen. */
export function flowStep(state: FlowState, event: FlowEvent, options: readonly WireOption[]): FlowResult {
  if (event.type === 'rename') return { ...state, newName: event.name };
  if (event.type === 'pick') {
    const option = options[event.index];
    if (!option || option.disabled) return state;
    return { ...state, focus: event.index, selected: event.index, step: 'confirm' };
  }
  const { key } = event;
  if (state.step === 'confirm') {
    if (key === 'Escape') return { ...state, step: 'choose', selected: null };
    const option = state.selected == null ? undefined : options[state.selected];
    if ((key === 'Enter') && option) return { done: choiceOf(option, state.newName) };
    return state;
  }
  switch (key) {
    case 'Escape':
      return 'cancel';
    case 'ArrowDown':
      return { ...state, focus: move(options, state.focus, 1) };
    case 'ArrowUp':
      return { ...state, focus: move(options, state.focus, -1) };
    case 'Home':
      return { ...state, focus: edge(options, false) };
    case 'End':
      return { ...state, focus: edge(options, true) };
    case 'Enter':
    case ' ':
      return flowStep(state, { type: 'pick', index: state.focus }, options);
    default:
      return state;
  }
}
