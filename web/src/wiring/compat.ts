// Map wiring: can a sender (a topic, an output port) be wired into a receiver (an input port,
// a topic)? The same rules as the backend (roshanavi/data_kinds.py wire_compat); both sides are
// tested against ros2_ws/src/roshanavi/test/data/wire_compat_cases.json (docs/design/wiring.md).

import { t, type MessageKey } from '../i18n';
import { kindLabel, normalizeType, shortType, type KindCatalog, type KindId, type PortKind } from '../datakind/kinds';

export type WireStatus = 'same' | 'convert' | 'refuse';
export type WireVerdict = readonly [WireStatus, string];

/** One side of a wire. `kind` null: described by its type; `type` null: not known (new topic). */
export interface WireEnd {
  kind: PortKind | null;
  type: string | null;
}

/** sender kind > receiver kind -> the note shown for an allowed conversion. */
export const CONVERSIONS: Readonly<Record<string, string>> = {
  'int>float': 'int_to_float',
  'string>json': 'string_to_json',
  'json>string': 'json_to_string',
};

/** Refused pairs with their own reason; any other difference is `kind_mismatch`. */
export const REFUSALS: Readonly<Record<string, string>> = {
  'float>int': 'float_to_int',
};

function kindOf(end: WireEnd, typeKinds: Readonly<Record<string, KindId>>): PortKind | null {
  if (end.kind) return end.kind;
  return end.type ? (typeKinds[normalizeType(end.type)] ?? null) : null;
}

/** `same` / `convert` (with a note code) / `refuse` (with a reason code), like the backend. */
export function wireCompat(sender: WireEnd, receiver: WireEnd, typeKinds: Readonly<Record<string, KindId>>): WireVerdict {
  const s = kindOf(sender, typeKinds);
  const r = kindOf(receiver, typeKinds);
  if ((s === null && !sender.type) || (r === null && !receiver.type)) return ['same', ''];
  if (s === 'message' || r === 'message' || s === null || r === null) {
    if (sender.type && receiver.type && normalizeType(sender.type) === normalizeType(receiver.type)) return ['same', ''];
    return ['refuse', 'type_mismatch'];
  }
  if (s === r) return ['same', ''];
  const pair = `${s}>${r}`;
  if (pair in CONVERSIONS) return ['convert', CONVERSIONS[pair] ?? ''];
  return ['refuse', REFUSALS[pair] ?? 'kind_mismatch'];
}

/** True when `type` carries `kind` (a compatible type of an existing topic, or the kind's type). */
export function typeFits(kind: PortKind, type: string, catalog: KindCatalog): boolean {
  if (kind === 'message') return true;
  const normalized = normalizeType(type);
  return catalog.type_kinds[normalized] === kind || catalog.kinds.some((k) => k.id === kind && k.type === normalized);
}

/** How one side is named in a sentence: 「文字列」 or 「専用の型 geometry_msgs/Twist」. */
export function endLabel(end: WireEnd, typeKinds: Readonly<Record<string, KindId>>): string {
  const kind = kindOf(end, typeKinds);
  if (kind && kind !== 'message') return kindLabel(kind);
  return end.type ? t('kind.special', { type: shortType(end.type) }) : t('common.unknown');
}

/** The plain-language reason (refuse) or note (convert) for a verdict; '' for `same`.
 *  `receiverIsPort`: the receiver is an input port (else a channel the output port sends to). */
export function verdictText(verdict: WireVerdict, sender: WireEnd, receiver: WireEnd, typeKinds: Readonly<Record<string, KindId>>, receiverIsPort: boolean): string {
  const [status, code] = verdict;
  if (status === 'same' || !code) return '';
  const params = { from: endLabel(sender, typeKinds), to: endLabel(receiver, typeKinds) };
  const prefix = status === 'refuse' ? 'wiring.refuse' : 'wiring.note';
  const key = `${prefix}.${code}${status === 'refuse' && code === 'kind_mismatch' && !receiverIsPort ? 'Out' : ''}` as MessageKey;
  return t(key, params);
}
