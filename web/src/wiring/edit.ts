// Wiring = editing the existing config of a function / class / transform / input node (pure;
// docs/design/wiring.md). No new storage: a wire is the port's topic in the spec the dialogs
// edit (`functions:` / `classes:` / `transforms:` / `dummies:` of the project file).

import type { ClassMethodSpec, ClassOutputSpec, ClassSpec } from '../api/classTypes';
import type { FunctionPortSpec, FunctionSpec } from '../api/functionTypes';
import type { TransformSpec } from '../api/transformTypes';
import type { DummySpec, Target } from '../api/types';
import { normalizeType, type KindCatalog, type PortKind } from '../datakind/kinds';
import { t } from '../i18n';
import { termPair } from '../i18n/glossary';
import { TOPIC_RE } from '../function/functionForm';
import { typeFits, verdictText, wireCompat, type WireEnd, type WireVerdict } from './compat';
import type { NodePorts, Port } from './ports';

export type WireSpec = FunctionSpec | ClassSpec | TransformSpec | DummySpec;

export type WirePlan =
  | { ok: true; spec: WireSpec; note: string; unchanged: boolean }
  | { ok: false; reason: string };

/** What the port says about itself on each side of a wire. */
export function portEnd(p: Port): WireEnd {
  return { kind: p.kind, type: p.type };
}

const topicEnd = (type: string | null): WireEnd => ({ kind: null, type });

/** The sender / receiver of a wire between `p` and a channel of type `type` (null: new). */
export function wireEnds(p: Port, type: string | null): { sender: WireEnd; receiver: WireEnd } {
  return p.ref.side === 'in' ? { sender: topicEnd(type), receiver: portEnd(p) } : { sender: portEnd(p), receiver: topicEnd(type) };
}

export interface Checked {
  verdict: WireVerdict;
  /** The channel type the port will use (null: a new channel, the port decides). */
  type: string | null;
  text: string;
}

/** Can port `p` be wired to a channel with `types` (empty: a new channel)? Prefers a type that
 *  needs no conversion when the channel has several. */
export function checkTypes(p: Port, types: readonly string[], catalog: KindCatalog): Checked {
  if (types.length === 0) return { verdict: ['same', ''], type: null, text: '' };
  const tried = types.map((type) => {
    const { sender, receiver } = wireEnds(p, type);
    const verdict = wireCompat(sender, receiver, catalog.type_kinds);
    return { verdict, type, text: verdictText(verdict, sender, receiver, catalog.type_kinds, p.ref.side === 'in') };
  });
  const rank = (c: Checked) => ({ same: 0, convert: 1, refuse: 2 })[c.verdict[0]];
  return [...tried].sort((a, b) => rank(a) - rank(b))[0] as Checked;
}

// ---- function / class ports -----------------------------------------------------------------------
function wiredPort<T extends FunctionPortSpec>(old: T, p: Port, topic: string, type: string | null, catalog: KindCatalog): T {
  const kind = old.kind;
  if (topic === '' || type === null) {
    // Not wired / a new channel: the kind's own type (専用の型 keeps its type).
    const { type: _drop, ...rest } = old;
    return (kind === 'message' ? { ...old, topic } : { ...rest, topic }) as T;
  }
  const normalized = normalizeType(type);
  if (p.ref.side === 'out' && !typeFits(kind, normalized, catalog)) {
    // An allowed conversion on the sending side (an integer into a 数値 (小数) channel): the
    // port sends the channel's kind; the function's value is converted when it is sent.
    const channelKind = (catalog.type_kinds[normalized] ?? kind) as PortKind;
    return { ...old, topic, kind: channelKind, type: normalized };
  }
  return { ...old, topic, type: normalized };
}

const LOOP = () => t('wiring.refuse.loop');
const DUPLICATE = () => t('wiring.refuse.duplicate', { channel: termPair('topic') });

function wiredTopics(ports: readonly { topic: string }[]): string[] {
  return ports.map((x) => x.topic).filter(Boolean);
}

function retrigger(trigger: string | undefined, oldTopic: string, topic: string): string | undefined {
  if (!trigger || trigger === 'any' || trigger !== oldTopic) return trigger;
  return topic || 'any';
}

function editFunction(spec: FunctionSpec, p: Port, topic: string, type: string | null, catalog: KindCatalog): WirePlan | FunctionSpec {
  if (p.ref.side === 'in') {
    const old = (spec.inputs ?? [])[p.ref.index];
    if (!old) return { ok: false, reason: t('wiring.refuse.gone') };
    const inputs = (spec.inputs ?? []).map((x, i) => (i === p.ref.index ? wiredPort(x, p, topic, type, catalog) : x));
    if (topic && wiredTopics(inputs).filter((x) => x === topic).length > 1) return { ok: false, reason: DUPLICATE() };
    if (topic && topic === spec.output.topic) return { ok: false, reason: LOOP() };
    return { ...spec, inputs, trigger: retrigger(spec.trigger, old.topic, topic) };
  }
  if (topic && (spec.inputs ?? []).some((x) => x.topic === topic)) return { ok: false, reason: LOOP() };
  return { ...spec, output: wiredPort(spec.output, p, topic, type, catalog) };
}

function editClass(spec: ClassSpec, p: Port, topic: string, type: string | null, catalog: KindCatalog): WirePlan | ClassSpec {
  const method = (spec.methods ?? [])[p.ref.group];
  if (!method) return { ok: false, reason: t('wiring.refuse.gone') };
  let next: ClassMethodSpec;
  if (p.ref.side === 'in') {
    const old = (method.inputs ?? [])[p.ref.index];
    if (!old) return { ok: false, reason: t('wiring.refuse.gone') };
    const inputs = (method.inputs ?? []).map((x, i) => (i === p.ref.index ? wiredPort(x, p, topic, type, catalog) : x));
    if (topic && wiredTopics(inputs).filter((x) => x === topic).length > 1) return { ok: false, reason: DUPLICATE() };
    next = { ...method, inputs, trigger: retrigger(method.trigger, old.topic, topic) };
  } else {
    if (!(method.outputs ?? [])[p.ref.index]) return { ok: false, reason: t('wiring.refuse.gone') };
    next = { ...method, outputs: (method.outputs ?? []).map((x, i) => (i === p.ref.index ? wiredPort<ClassOutputSpec>(x, p, topic, type, catalog) : x)) };
  }
  const methods = (spec.methods ?? []).map((m, i) => (i === p.ref.group ? next : m));
  const outs = methods.flatMap((m) => wiredTopics(m.outputs ?? []));
  const ins = new Set(methods.flatMap((m) => wiredTopics(m.inputs ?? [])));
  if (new Set(outs).size !== outs.length) return { ok: false, reason: t('wiring.refuse.outputTaken') };
  if (outs.some((x) => ins.has(x))) return { ok: false, reason: LOOP() };
  return { ...spec, methods };
}

// ---- transform / input node ports (always wired; their ROS type is fixed in their own dialog) -----
function editTransform(spec: TransformSpec, p: Port, topic: string, type: string | null): WirePlan | TransformSpec {
  if (p.ref.side === 'in') {
    const old = (spec.inputs ?? [])[p.ref.index];
    if (!old) return { ok: false, reason: t('wiring.refuse.gone') };
    if (type && normalizeType(type) !== normalizeType(old.type)) return { ok: false, reason: t('wiring.refuse.transformType', { type: old.type }) };
    if (topic === spec.output.topic) return { ok: false, reason: LOOP() };
    if ((spec.inputs ?? []).some((x, i) => i !== p.ref.index && x.topic === topic)) return { ok: false, reason: DUPLICATE() };
    return { ...spec, inputs: (spec.inputs ?? []).map((x, i) => (i === p.ref.index ? { ...x, topic } : x)) };
  }
  const outType = spec.output.type ?? (spec.mode === 'relay' ? (spec.inputs ?? [])[0]?.type : undefined);
  if (type && outType && normalizeType(type) !== normalizeType(outType)) return { ok: false, reason: t('wiring.refuse.transformType', { type: outType }) };
  if ((spec.inputs ?? []).some((x) => x.topic === topic)) return { ok: false, reason: LOOP() };
  return { ...spec, output: { ...spec.output, topic } };
}

function editDummy(spec: DummySpec, topic: string, type: string | null, catalog: KindCatalog): WirePlan | DummySpec {
  if (type && normalizeType(type) !== normalizeType(spec.type)) {
    // Same kind (one `data` field, e.g. std_msgs vs example_interfaces String): send that type.
    const kind = spec.kind ?? catalog.type_kinds[normalizeType(spec.type)];
    if (!kind || kind === 'message' || catalog.type_kinds[normalizeType(type)] !== kind) {
      return { ok: false, reason: t('wiring.refuse.dummyType', { type: spec.type }) };
    }
    return { ...spec, topic, type: normalizeType(type) };
  }
  return { ...spec, topic };
}

function sameSpec(a: WireSpec, b: WireSpec): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/** Wire port `p` of `target` to channel `topic` whose types on the map are `types` (empty: a
 *  new channel). Refuses with a plain reason before anything is drawn or saved. */
export function planConnect(np: NodePorts, p: Port, target: Target, topic: string, types: readonly string[], catalog: KindCatalog): WirePlan {
  if (!TOPIC_RE.test(topic)) return { ok: false, reason: t('wiring.refuse.name', { name: topic || '—' }) };
  const checked = checkTypes(p, types, catalog);
  if (checked.verdict[0] === 'refuse') return { ok: false, reason: checked.text };
  const spec = target.spec as WireSpec;
  const next =
    np.owner === 'function' ? editFunction(spec as FunctionSpec, p, topic, checked.type, catalog)
      : np.owner === 'class' ? editClass(spec as ClassSpec, p, topic, checked.type, catalog)
        : np.owner === 'transform' ? editTransform(spec as TransformSpec, p, topic, checked.type)
          : editDummy(spec as DummySpec, topic, checked.type, catalog);
  if ('ok' in next) return next;
  return { ok: true, spec: next, note: checked.text, unchanged: sameSpec(spec, next) };
}

/** Take the wire off port `p` (function / class ports only: the others always need a channel). */
export function planDisconnect(np: NodePorts, p: Port, target: Target, catalog: KindCatalog): WirePlan {
  if (!p.canUnwire) return { ok: false, reason: t(np.owner === 'transform' ? 'wiring.refuse.unwireTransform' : 'wiring.refuse.unwireDummy') };
  if (!p.topic) return { ok: true, spec: target.spec as WireSpec, note: '', unchanged: true };
  const spec = target.spec as WireSpec;
  const next = np.owner === 'function'
    ? editFunction(spec as FunctionSpec, p, '', null, catalog)
    : editClass(spec as ClassSpec, p, '', null, catalog);
  if ('ok' in next) return next;
  return { ok: true, spec: next, note: '', unchanged: false };
}
